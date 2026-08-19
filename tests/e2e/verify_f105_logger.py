"""F105 E2E：時間型動作的前端 logger 切片——mode 換輸入、組列表分流、次數型不回歸。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f105_logger.py`

⚠ 範圍邊界（派工單 may-write 只有 app.js＋本檔）：本檔**刻意不驗**下列兩條凍結 acceptance
子句，因為要做到就得動派工單明列的 must-not-write 檔案，已在派工回報中列為阻塞，不在這裡
用假斷言充數：
  - 「自訂動作（F10）建立時可選 mode」——建立動作的整個表單在 `custom-exercise.js`
    （`app.js` 呼叫 `customExerciseModal()` 拿回一顆已經包好提交邏輯的 DOM，沒有任何注入點
    可以加欄位），不在 may-write 範圍。
  - 「首頁、上次訓練摘要在有時間型資料時同時講兩個數字」——首頁那張卡吃的是
    `GET /api/schedule/today` 的 `LastWorkout`（`app/services/schedule.py`／`app/schemas.py`），
    這支後端 schema 沒有 `duration_seconds` 欄位（F105 backend contract 那個 commit 沒碰
    `schedule.py`），app.js 端沒有資料可畫，不在可寫檔案內補。
  兩者都需要主 session 決定要不要放寬 may-write 或另開派工單。

量測一律問**渲染結果**（實際文字、輸入框存在與否、送出的 request payload），
不問 class 名稱有沒有掛上（同 verify_f136 起訂的規則）。

時間型動作用直接呼叫後端 API 種子（`api()` helper），不透過 UI 建立——上面那條阻塞
正是「UI 建不出時間型動作」，這裡用種子繞過建立步驟，只驗證**建好之後** logger／組列表
的 mode 分流行為。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ①②③⑥⑧⑨、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138 同款防呆）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    TOKEN,
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
    wait_home,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, method: str, path: str, body=None):
    """直接打後端 API 種子資料（同 verify_f86 的慣例）。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        raise AssertionError(f"{method} {path} -> {exc.code}: {detail}") from None
    return json.loads(raw) if raw.strip() else None


TIME_EX_ZH = "F105計時棒式"
REPS_EX_ZH = "深蹲"  # app/seed.py 的預設動作，次數型，用來驗回歸


def steppers(page):
    """logger 主畫面的兩顆步進器（KG、REPS／秒數）——scope 在 `.steppers` 底下，
    避免跟休息參考秒數那顆（在 `.rest-preset` 裡，class 同樣是 `.stepper`）搞混。
    """
    return page.locator(".logger-foot .steppers .stepper")


def stepper_name(page, index: int) -> str:
    return steppers(page).nth(index).locator(".name").inner_text()


def stepper_value(page, index: int) -> str:
    return steppers(page).nth(index).locator("output.editable").inner_text()


def type_into(page, index: int, text: str) -> None:
    """同 verify_f102：點數字 → 進入輸入態 → 輸入 → Enter 送出。"""
    cell = steppers(page).nth(index)
    cell.locator("output.editable").click()
    page.wait_for_timeout(200)
    cell.locator(".value-input").fill(text)
    page.wait_for_timeout(100)
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f105-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        time_ex = api(base, "POST", "/api/exercises", {
            "name_zh": TIME_EX_ZH, "name_en": "F105 Timed Plank",
            "mode": "time", "is_bodyweight": True,
        })
        check(time_ex.get("mode") == "time", "種子：時間型動作建立成功，mode 是 time")
        run_checks(base, time_ex)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    if passed != len(results):
        print("\nFAILED:")
        for ok, label in results:
            if not ok:
                print(f"  - {label}")
    return 0 if passed == len(results) else 1


def run_checks(base: str, time_ex: dict) -> None:  # noqa: C901
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        wait_home(page)

        # ---------- ⑥ 自由訓練：時間型動作走 picker 搜尋（不經過今日菜單） ----------
        start_from_home(page)
        page.wait_for_timeout(700)
        page.locator(".exercise-item", has_text=TIME_EX_ZH).first.click()
        page.wait_for_selector(".logger-foot", timeout=8000)
        page.wait_for_timeout(400)

        stepper_count = steppers(page).count()
        check(stepper_count == 2, f"⑥ logger 仍是兩顆直接輸入步進器（實際 {stepper_count}）")
        second_name = stepper_name(page, 1)
        check("REPS" not in second_name and "次" not in second_name,
              f"⑥ 時間型 logger 沒有次數輸入（第二顆步進器標籤「{second_name}」不含 REPS／次）")
        check("秒" in second_name, f"⑥ 時間型 logger 第二顆步進器標「秒」（實際「{second_name}」）")
        kg0 = stepper_value(page, 0)
        check(kg0 == "0", f"④ 自體重時間型第一次做，KG 預設 0（實際 {kg0}）")

        type_into(page, 1, "60")
        sec_value = stepper_value(page, 1)
        check(sec_value == "60", f"⑥ 秒數可直接輸入 60（實際 {sec_value}）")

        with page.expect_request(
            lambda r: r.url.endswith("/sets") and r.method == "POST"
        ) as req_info:
            page.locator(".log-btn").first.click()
        page.wait_for_timeout(600)
        payload = req_info.value.post_data_json
        check(payload.get("duration_seconds") == 60,
              f"⑥ payload 帶 duration_seconds=60（實際 {payload}）")
        sent_reps = payload.get("reps")
        check(sent_reps is None,
              f"② reps／duration_seconds 互斥，時間型不送 reps（實際 {sent_reps!r}）")
        sent_weight = payload.get("weight_kg")
        check(sent_weight == 0,
              f"④ 無負重送出的 weight_kg 是 0 不是 null／空字串（實際 {sent_weight!r}）")

        row = page.locator(".done-row").first.inner_text()
        check("60 秒" in row, f"⑥ 組列表顯示「60 秒」而不是「60 次」（實際「{row.strip()[:40]}」）")
        check("60 次" not in row, f"⑥ 組列表不應出現「60 次」（實際「{row.strip()[:40]}」）")

        # ---------- ⑨ 回歸：次數型動作（深蹲）的 logger／組列表行為不變 ----------
        page.locator(".logger-back").click()
        page.wait_for_timeout(500)
        page.locator(".exercise-item", has_text=REPS_EX_ZH).first.click()
        page.wait_for_selector(".logger-foot", timeout=8000)
        page.wait_for_timeout(400)

        reps_name = stepper_name(page, 1)
        check(reps_name == "REPS", f"⑨ 次數型 logger 第二顆步進器仍叫 REPS（實際「{reps_name}」）")
        reps_value = stepper_value(page, 1)
        check(reps_value == "8", f"⑨ 次數型預設仍是 8（實際 {reps_value}）")

        # F108：換了動作但上一顆時間型還在跑休息倒數，記這組前會先跳「還在休息」確認視窗
        # （與 F105 本身無關，既有行為）——確認後才真的送出。
        with page.expect_request(
            lambda r: r.url.endswith("/sets") and r.method == "POST"
        ) as req_info2:
            page.locator(".log-btn").first.click()
            page.wait_for_timeout(300)
            confirm = page.get_by_role("button", name="記這組")
            if confirm.count():
                confirm.click()
        page.wait_for_timeout(600)
        payload2 = req_info2.value.post_data_json
        check(payload2.get("reps") == 8, f"⑨ 次數型送出 reps=8（實際 {payload2}）")
        check("duration_seconds" not in payload2 or payload2.get("duration_seconds") is None,
              f"⑨ 次數型不送 duration_seconds（實際 {payload2.get('duration_seconds')!r}）")

        row2 = page.locator(".done-row").first.inner_text()
        check("× 8" in row2 and "秒" not in row2,
              f"⑨ 次數型組列表格式不變，沒有秒單位（實際「{row2.strip()[:40]}」）")

        page.locator(".logger-back").click()  # 「結束訓練」在 picker 畫面，logger 裡沒有
        page.wait_for_timeout(500)
        page.get_by_role("button", name="結束訓練").click()
        page.wait_for_timeout(800)

        # ---------- ⑥ 今日菜單／課表路徑：menuCard 與「接著做」兩個入口都要補得到 mode ----------
        # TemplateExerciseOut 不帶 mode（後端契約沒補這欄），app.js 的 nextUpItem()／menuCard()
        # 各自組出的 exercise 物件原本會漏掉 mode，導致從課表菜單進 logger 一律被當成次數型。
        template = api(base, "POST", "/api/templates", {
            "name": "F105課表",
            "exercises": [{"exercise_id": time_ex["id"], "default_sets": 2}],
        })
        check(template.get("id") is not None, "種子：含時間型動作的課表建立成功")

        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input, .home-head", timeout=10_000)
        wait_home(page)
        start_from_home(page)
        page.wait_for_timeout(700)
        page.locator(".tpl-choice", has_text="F105課表").first.click()
        page.wait_for_timeout(900)

        # 「接著做」＝ nextUpItem() 組出來的 exercise 物件
        page.locator(".next-up").click()
        page.wait_for_selector(".logger-foot", timeout=8000)
        page.wait_for_timeout(400)
        check(steppers(page).count() == 2 and "秒" in stepper_name(page, 1),
              f"⑥ 課表「接著做」入口也正確分流成秒數輸入（實際標籤「{stepper_name(page, 1)}」）")
        type_into(page, 1, "45")
        page.locator(".log-btn").first.click()
        page.wait_for_timeout(700)
        page.locator(".logger-back").click()
        page.wait_for_timeout(500)

        # menuCard() 組出來的 exercise 物件（同一個動作，第二個入口）
        page.locator(".menu-card", has_text=TIME_EX_ZH).first.click()
        page.wait_for_selector(".logger-foot", timeout=8000)
        page.wait_for_timeout(400)
        check(steppers(page).count() == 2 and "秒" in stepper_name(page, 1),
              f"⑥ 課表「動作卡」入口也正確分流成秒數輸入（實際標籤「{stepper_name(page, 1)}」）")

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
