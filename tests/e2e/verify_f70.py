"""F70 E2E：休息倒數跨畫面存活（①②③④⑦）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f70.py`

這支**走真實 UI 流程**（開練→記組→換動作→回來→再記一組），並且回頭打 API 查
真的寫進資料庫的 `rest_seconds`——③ 是會進訓練資料的欄位，不能只驗畫面。
⑤⑥ 牽涉通知與浮動視窗，只能在裝置上驗（acceptance ⑧ 亦如此規定）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, TOKEN, free_port, setup_and_home, start_server  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, path: str):
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {TOKEN}"})
    return json.load(urllib.request.urlopen(req))


def rest_state(page) -> dict:
    return page.evaluate(
        "async () => {"
        "  const s = await import('/js/state.js');"
        "  return { elapsed: s.restElapsedSeconds(), remaining: s.restRemainingSeconds(),"
        "           screen: s.state.screen, started: s.state.restStartedAt !== null };"
        "}"
    )


def start_free_workout(page) -> None:
    """開練 → 自由訓練 → 選第一個動作。"""
    page.get_by_role("button", name="開練").click()
    page.wait_for_timeout(600)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(600)
    page.locator(".ex-row, .exercise-row, button").filter(has_text="深蹲").first.click()
    page.wait_for_timeout(600)


def log_one_set(page) -> None:
    page.get_by_role("button", name="完成這組").click()
    page.wait_for_timeout(900)


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f70_e2e_{port}.db"
    release = REPO / f"liftlog_f70_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)

            start_free_workout(page)
            log_one_set(page)
            r = rest_state(page)
            check(r["started"] is True, "前置：記完一組後休息開始")
            check(r["screen"] == "logger", "前置：停在計時頁")

            # ① 換動作（返回選動作）→ 休息不被取消
            page.locator(".logger-back").first.click()
            page.wait_for_timeout(600)
            r = rest_state(page)
            check(r["screen"] == "picker", f"① 已離開計時頁（{r['screen']}）")
            check(r["started"] is True, "① 離開計時頁後休息倒數仍在跑（不再被取消）")
            check(r["remaining"] is not None,
                  f"④ 離開計時頁後仍算得出剩餘秒數（{r['remaining']}）")

            # ① 再往外一層：回首頁（課表／日曆／體重都掛在這裡）
            home = page.get_by_role("button", name="← 回首頁")
            if home.count():
                home.first.click()
                page.wait_for_timeout(600)
                r = rest_state(page)
                check(r["screen"] == "home" and r["started"] is True,
                      "① 回到首頁休息仍在跑（課表／日曆／體重都從這裡進）")
                # 有進行中的訓練時首頁那顆按鈕是「繼續訓練」，不是「開練」
                page.locator("button.btn-primary").first.click()
                page.wait_for_timeout(800)

            # ④ 回到計時頁：剩餘秒數依實際經過時間續算，不是離開時凍結的值
            before = rest_state(page)["elapsed"]
            page.wait_for_timeout(2200)
            page.locator(".ex-row, .exercise-row, button").filter(has_text="深蹲").first.click()
            page.wait_for_timeout(600)
            r = rest_state(page)
            check(r["screen"] == "logger", "④ 回到計時頁")
            check(r["elapsed"] >= before + 2,
                  f"④ 經過秒數持續累加（離開時 {before}s → 回來 {r['elapsed']}s）")
            check(page.locator(".rest-led").count() == 1, "④ REST 卡片回來就在")

            # ③ 記下一組 → 寫進資料庫的 rest_seconds ≈ 實際經過時間。
            # 休息中按鈕是「繼續下一組」（結束休息、凍結經過秒數），再按「完成這組」——
            # 這是既有的兩步流程，F70 沒有改它，改的只是中途切頁不會讓計時歸零。
            elapsed_at_log = rest_state(page)["elapsed"]
            page.get_by_role("button", name="繼續下一組").click()
            page.wait_for_timeout(500)
            log_one_set(page)
            sets = []
            for w in api(base, "/api/workouts"):
                sets = api(base, f"/api/workouts/{w['id']}")["sets"]
                if sets:
                    break
            second = [s for s in sets if s["set_number"] == 2]
            got = second[0]["rest_seconds"] if second else None
            check(got is not None, f"③ 第二組有寫入 rest_seconds（{got}）")
            check(got is not None and abs(got - elapsed_at_log) <= 3,
                  f"③ rest_seconds 是實際經過時間（記錄 {got}s vs 實際 {elapsed_at_log}s）")
            first = [s for s in sets if s["set_number"] == 1]
            check(first and first[0]["rest_seconds"] is None,
                  "③ 第一組仍不帶 rest_seconds（沒有上一組可比）")

            # ② 「繼續下一組」仍取消休息
            r = rest_state(page)
            check(r["started"] is True, "前置：第二組記完又開始休息")
            page.get_by_role("button", name="繼續下一組").click()
            page.wait_for_timeout(600)
            check(rest_state(page)["started"] is False, "② 繼續下一組仍結束休息")

            # ② 收工仍取消休息
            log_one_set(page)
            check(rest_state(page)["started"] is True, "前置：再記一組開始休息")
            page.get_by_role("button", name="繼續下一組").click()
            page.wait_for_timeout(400)
            log_one_set(page)
            # F42 起「收工」在選動作頁叫「結束訓練」——先退回去（此時休息仍在跑，正是 ① 的效果）
            page.locator(".logger-back").first.click()
            page.wait_for_timeout(500)
            check(rest_state(page)["started"] is True, "① 退回選動作頁時休息還在跑")
            page.get_by_role("button", name="結束訓練").first.click()
            page.wait_for_timeout(900)
            r = rest_state(page)
            check(r["started"] is False, "② 結束訓練仍結束休息（訓練狀態改變，不是換個地方看）")
            check(r["screen"] == "home", "② 結束訓練後回到首頁")

            ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for _ in range(20):
            try:
                db.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.25)
        for f in release.iterdir():
            f.unlink()
        release.rmdir()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
