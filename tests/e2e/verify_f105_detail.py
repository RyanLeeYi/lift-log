"""F105 E2E：動作詳情頁的 PR 卡與統計依 mode 分流（時間型 vs 次數型），①–④。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f105_detail.py`

⚠ 量測一律問**渲染結果**（節點數量、bounding_box、實際文字），不問 class 名稱有沒有掛上去
（同 verify_f86／verify_f136 的教訓）。

① 時間型動作：PR 卡恰好兩張（最長單組秒數／單次訓練總秒數），數值對得上種子資料，
   「推估 1RM」整格不出現（DOM 裡沒有那個節點，不是顯示 —）。
② 兩張卡等分（實際渲染寬度，允許 1–2px 誤差）。
③ 組列表顯示「N 秒」，不是「N 次」。
④ 次數型動作仍是三張卡、內容與數值不變——沿用 verify_f86.seed 的深蹲種子資料
   （回歸斷言，這條最重要：確保時間型分支沒有動到次數型既有行為）。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ①②③④、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138 同款防呆）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, TOKEN, safe_port, setup_and_home, start_server  # noqa: E402
from verify_f86 import seed as seed_squat  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{method} {path} → {exc.code}: {exc.read().decode()[:300]}") from None
    return json.loads(raw) if raw.strip() else None


def seed_plank(base: str) -> dict:
    """一個時間型動作、兩次訓練：

    session A（10 天前）兩組 40s／55s——總秒數 95s，session 內最長是 55s。
    session B（3 天前）一組 60s——總秒數 60s，也是**全期**最長單組。

    刻意讓「全期最長單組」（60s，出自 B）與「單次訓練總秒數」（95s，出自 A）
    來自不同次訓練——兩張 PR 卡才不會剛好算出同一個數字，能證明各自獨立計算。
    """
    # 名稱刻意不用「棒式」——app/seed.py 的預載動作庫已經有一筆同名的次數型「棒式」，
    # 撞名會被 exercises API 擋掉（名稱唯一）。
    ex = api(base, "POST", "/api/exercises", {
        "name_zh": "計時撐體", "name_en": "Timed Hold", "muscle_group": "核心",
        "is_bodyweight": True, "mode": "time",
    })
    ex_id = ex["id"]

    day_a = (date.today() - timedelta(days=10)).isoformat()
    wa = api(base, "POST", "/api/workouts", {"date": day_a})
    for i, dur in enumerate((40, 55), start=1):
        api(base, "POST", f"/api/workouts/{wa['id']}/sets", {
            "client_uuid": f"f105-plank-a-{i:03d}", "exercise_id": ex_id, "set_number": i,
            "weight_kg": 0, "duration_seconds": dur,
        })

    day_b = (date.today() - timedelta(days=3)).isoformat()
    wb = api(base, "POST", "/api/workouts", {"date": day_b})
    api(base, "POST", f"/api/workouts/{wb['id']}/sets", {
        "client_uuid": "f105-plank-b-001", "exercise_id": ex_id, "set_number": 1,
        "weight_kg": 0, "duration_seconds": 60,
    })

    return {"exercise_id": ex_id, "day_a": day_a, "day_b": day_b}


def open_detail(page, muscle: str, name: str) -> None:
    """底部導覽「表現」→ 選部位 → 選動作（同 verify_f86／verify_f134 的既有走法）。"""
    page.locator(".bottom-nav").get_by_role("button", name="表現").click()
    page.wait_for_timeout(900)
    page.get_by_role("button", name=muscle).first.click()
    page.wait_for_timeout(700)
    page.get_by_role("button", name=name).first.click()
    page.wait_for_selector(".exercise-detail", timeout=8000)
    page.wait_for_timeout(600)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f105-detail-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        plank = seed_plank(base)
        seed_squat(base)
        run_checks(base, plank)
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


def run_checks(base: str, plank: dict) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)

        # ---- 時間型動作（計時撐體） ----
        open_detail(page, "核心", "計時撐體")

        cards = page.locator(".pr-card")
        check(cards.count() == 2, f"① 時間型 PR 卡恰好兩張（實際 {cards.count()} 張）")

        body_text = page.locator(".exercise-detail").inner_text()
        check("推估 1RM" not in body_text,
              "① 「推估 1RM」整格不出現（DOM 裡沒有這段文字，不是顯示 —）")

        labels = [page.locator(".pr-card .pr-k").nth(i).inner_text().strip() for i in range(2)]
        check(labels == ["最長單組秒數", "單次訓練總秒數"],
              f"① 兩張卡分別是最長單組秒數／單次訓練總秒數（實際 {labels}）")

        values = [page.locator(".pr-card .pr-v").nth(i).inner_text().strip() for i in range(2)]
        check(values[0].startswith("60"),
              f"① 最長單組秒數＝種子資料的 60（來自 B 那次；實際 {values[0]}）")
        check(values[1].startswith("95"),
              f"① 單次訓練總秒數＝種子資料的 95（來自 A 那次；實際 {values[1]}）")

        # ② 兩張卡等分
        boxes = [cards.nth(i).bounding_box() for i in range(2)]
        widths = [round(b["width"]) for b in boxes]
        check(abs(widths[0] - widths[1]) <= 2, f"② 兩張卡等分（實際寬度 {widths}）")
        check(len({round(b["y"]) for b in boxes}) == 1, "② 兩張卡在同一列")

        # ③ 組列表顯示「N 秒」不是「N 次」——歷史卡按新→舊排序，第一張是 session B（單組 60s）
        first_card = page.locator(".hist-card").first
        chips = first_card.locator(".set-chip")
        check(chips.count() == 1, f"③ session B 只有一組（實際 {chips.count()} 顆 chip）")
        chip_text = chips.first.inner_text()
        check("60秒" in chip_text, f"③ 組列表顯示『60秒』（實際 {chip_text!r}）")
        check("次" not in chip_text, f"③ 組列表不顯示『次』（實際 {chip_text!r}）")

        # session A（兩組 40s/55s）：hist-vol 是總秒數（95），不是噸位
        second_card = page.locator(".hist-card").nth(1)
        vol_text = second_card.locator(".hist-vol").inner_text()
        check("95" in vol_text and "秒" in vol_text,
              f"③ session A 的統計是總秒數 95（實際 {vol_text!r}）")
        a_chips = second_card.locator(".set-chip")
        check(a_chips.count() == 2, f"③ session A 兩組 chip（實際 {a_chips.count()}）")
        a_texts = [a_chips.nth(i).inner_text() for i in range(2)]
        check(any("55秒" in t for t in a_texts) and any("40秒" in t for t in a_texts),
              f"③ session A 兩組分別顯示 40秒／55秒（實際 {a_texts}）")

        # ---- 次數型動作（深蹲）：回歸——依然三張卡，內容與數值不變 ----
        # .exercise-detail 沒有 .bottom-nav（同 verify_f134 的走法：從首頁重新進一次）；
        # token 已存在 localStorage，重新 goto 會直接回到已登入的首頁，不必再輸入一次。
        page.goto(base, wait_until="domcontentloaded")
        setup_and_home(page)
        open_detail(page, "腿", "深蹲")

        reps_cards = page.locator(".pr-card")
        check(reps_cards.count() == 3,
              f"④ 次數型動作仍是三張 PR 卡（實際 {reps_cards.count()} 張）")

        reps_labels = [page.locator(".pr-card .pr-k").nth(i).inner_text().strip() for i in range(3)]
        check(reps_labels == ["推估 1RM", "最重", "單次量"],
              f"④ 三張卡分別是推估 1RM／最重／單次量（未受時間型分支影響；實際 {reps_labels})")

        reps_values = [page.locator(".pr-card .pr-v").nth(i).inner_text().strip() for i in range(3)]
        check(reps_values[1].startswith("75"),
              f"④ 「最重」＝種子資料的 75kg（回歸；實際 {reps_values[1]}）")
        check(reps_values[0].startswith("88"),
              f"④ 「推估 1RM」＝Epley 87.5 四捨五入 88（回歸；實際 {reps_values[0]}）")

        reps_chip = page.locator(".hist-card").first.locator(".set-chip").first.inner_text()
        check("×" in reps_chip and "秒" not in reps_chip,
              f"④ 次數型組列表格式不變（weight×reps，不含『秒』；實際 {reps_chip!r}）")

        browser.close()


if __name__ == "__main__":
    sys.exit(main())
