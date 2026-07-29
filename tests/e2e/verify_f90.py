"""F90 E2E：進行中訓練在 app 被回收後不遺失（①–⑥）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f90.py`

**回收怎麼模擬**：清掉 `sessionStorage` 再 reload。這正是這條 feature 的核心——
在修好之前，狀態只存在 sessionStorage，清掉就等於「分頁被關 / app 被系統回收」；
修好之後狀態在 localStorage，清 sessionStorage 應該完全沒有影響。
所以這個動作同時是「模擬回收」與「RED/GREEN 的判別器」。

⚠ 量測一律問實際狀態（localStorage 內容、API 回傳的 set_number、按鈕文字），
不問實作手段——handoff 記過四次「測試綠但東西是壞的」，型態都是問了 class 名稱。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    REPO,
    TOKEN,
    free_port,
    setup_and_home,
    start_from_home,
    start_server,
)

WORKOUT_KEY = "liftlog.activeWorkout"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, path: str, method: str = "GET"):
    req = urllib.request.Request(
        base + path, headers={"Authorization": f"Bearer {TOKEN}"}, method=method
    )
    with urllib.request.urlopen(req) as r:
        body = r.read()
    return json.loads(body) if body else None


def stored(page, kind: str = "local"):
    """讀 storage 裡的 activeWorkout（解析過的 dict，沒有就 None）。"""
    raw = page.evaluate(f"() => {kind}Storage.getItem('{WORKOUT_KEY}')")
    return json.loads(raw) if raw else None


def home_button_label(page) -> str:
    for name in ("繼續訓練", "開始訓練", "挑一份課表"):
        if page.get_by_role("button", name=name).count():
            return name
    return "(找不到入口)"


def recycle(page, base: str) -> None:
    """模擬 app 被系統回收：清掉 sessionStorage（分頁級）後重新載入。"""
    page.evaluate("() => sessionStorage.clear()")
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)


def start_free_workout(page) -> None:
    start_from_home(page)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(600)
    page.locator(".ex-row, .exercise-row, button").filter(has_text="深蹲").first.click()
    page.wait_for_timeout(600)


def log_one_set(page) -> None:
    page.get_by_role("button", name="完成這組").click()
    page.wait_for_timeout(900)
    nxt = page.get_by_role("button", name="繼續下一組")
    if nxt.count():
        nxt.first.click()
        page.wait_for_timeout(700)


def main() -> int:  # noqa: C901
    port = free_port()
    db = REPO / f"liftlog_f90_e2e_{port}.db"
    release = REPO / f"liftlog_f90_release_{port}"
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

            # ---------- 前置：開一場訓練、記 2 組 ----------
            start_free_workout(page)
            log_one_set(page)
            log_one_set(page)
            page.wait_for_timeout(500)

            workouts = api(base, "/api/workouts")
            check(len(workouts) == 1, f"前置：伺服器上只有 1 場 workout（實際 {len(workouts)}）")
            wid = workouts[0]["id"]
            detail = api(base, f"/api/workouts/{wid}")
            check(
                len(detail["sets"]) == 2,
                f"前置：該場已記 2 組（實際 {len(detail['sets'])}）",
            )

            # ---------- ① 狀態存在 localStorage ----------
            local = stored(page, "local")
            session = stored(page, "session")
            check(local is not None, "① 進行中訓練狀態寫在 localStorage")
            check(
                session is None,
                f"① 不再依賴 sessionStorage（實際 session 值：{session}）",
            )
            check(
                bool(local) and local.get("workoutId") == wid,
                "① payload 帶著 workoutId",
            )
            check(
                bool(local) and isinstance(local.get("setCounts"), dict)
                and sum(local["setCounts"].values()) == 2,
                f"① payload 帶著 setCounts（實際 {local and local.get('setCounts')}）",
            )
            check(
                bool(local) and local.get("date") == date.today().isoformat(),
                f"② payload 帶著今天的日期（實際 {local and local.get('date')}）",
            )

            # ---------- ①⑤ 回收後仍在 ----------
            recycle(page, base)
            check(
                home_button_label(page) == "繼續訓練",
                f"③ 回收後首頁顯示「繼續訓練」（實際「{home_button_label(page)}」）",
            )
            check(stored(page, "local") is not None, "① 回收後 localStorage 狀態仍在")

            # ---------- ③⑤ 續接不新建、組號不重來 ----------
            start_from_home(page)
            page.wait_for_timeout(800)
            page.locator(".ex-row, .exercise-row, button").filter(
                has_text="深蹲"
            ).first.click()
            page.wait_for_timeout(700)
            set_no = page.evaluate(
                "async () => (await import('/js/state.js')).state.setNumber"
            )
            check(set_no == 3, f"⑤ 回收後第 3 組的 set_number 是 3（實際 {set_no}）")

            log_one_set(page)
            page.wait_for_timeout(500)
            workouts = api(base, "/api/workouts")
            check(
                len(workouts) == 1,
                f"③⑤ 回收後續接不另建 workout（實際 {len(workouts)} 場）",
            )
            detail = api(base, f"/api/workouts/{wid}")
            numbers = sorted(s["set_number"] for s in detail["sets"])
            check(
                numbers == [1, 2, 3],
                f"⑤ set_number 連續不撞號（實際 {numbers}）",
            )

            # ---------- ④ 伺服器說不存在 → 清掉本地 ----------
            # 前提：本地要先有狀態才驗得了「被清掉」。RED 階段這裡本來就沒有，
            # 直接補一筆假的，讓 ④ 仍是真的在驗還原路徑而不是空跑（handoff「前提失效＝空跑」）。
            page.evaluate(
                """([key, today]) => {
                    const saved = JSON.parse(localStorage.getItem(key)) || {};
                    saved.workoutId = 999999;
                    saved.date = today;
                    localStorage.setItem(key, JSON.stringify(saved));
                }""",
                [WORKOUT_KEY, date.today().isoformat()],
            )
            check(
                stored(page, "local") is not None,
                "前置：④ 驗證前本地有一筆指向不存在 workout 的狀態",
            )
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            check(
                stored(page, "local") is None,
                "④ 伺服器 404 時清掉本地狀態",
            )
            check(
                home_button_label(page) != "繼續訓練",
                f"④ 404 後退回開始訓練（實際「{home_button_label(page)}」）",
            )

            # ---------- ② 非今天的訓練不續接 ----------
            start_free_workout(page)
            log_one_set(page)
            page.wait_for_timeout(500)
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            page.evaluate(
                """([key, d]) => {
                    const saved = JSON.parse(localStorage.getItem(key)) || {};
                    saved.date = d;
                    localStorage.setItem(key, JSON.stringify(saved));
                }""",
                [WORKOUT_KEY, yesterday],
            )
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            check(
                stored(page, "local") is None,
                "② 日期不是今天就清掉，不做跨日續接",
            )
            check(
                home_button_label(page) != "繼續訓練",
                f"② 跨日後退回開始訓練（實際「{home_button_label(page)}」）",
            )

            # ---------- ④ 離線（網路錯誤）不得誤清 ----------
            start_free_workout(page)
            log_one_set(page)
            page.wait_for_timeout(500)
            before = stored(page, "local")
            check(before is not None, "前置：離線測試前本地有狀態")
            ctx.set_offline(True)
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            after = stored(page, "local")
            check(
                after is not None and after.get("workoutId") == before.get("workoutId"),
                "④ 離線時不得把本地狀態誤判成「伺服器說不存在」而清掉",
            )
            ctx.set_offline(False)

            # ---------- ⑥ 與 F66 分工：這條不碰休息倒數 ----------
            payload_keys = set((after or {}).keys())
            check(
                "restStartedAt" not in payload_keys,
                f"⑥ 休息倒數不在本條範圍（F66 負責）；實際欄位 {sorted(payload_keys)}",
            )

            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        # Windows 上 uvicorn 收工後檔案握把可能還沒放掉，直接 unlink 會 WinError 32。
        # 清不掉不該讓整支測試失敗（它只是暫存檔），重試幾次就放行。
        for leftover in (db, REPO / f"{db.name}-wal", REPO / f"{db.name}-shm"):
            for _ in range(10):
                try:
                    leftover.unlink(missing_ok=True)
                    break
                except OSError:
                    time.sleep(0.3)
        if release.exists():
            for f in release.iterdir():
                f.unlink()
            release.rmdir()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    if passed != len(results):
        print("\nFAILED:")
        for ok, label in results:
            if not ok:
                print(f"  - {label}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
