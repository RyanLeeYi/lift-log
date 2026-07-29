"""F91 E2E：workout 結束狀態進伺服器（④⑤⑥⑦⑨）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f91.py`

核心情境（⑨）＝驗收 F90 ④ 時 fail 的那條：
在 A 裝置結束訓練，B 裝置那份**結束前的舊快取**重載後不得把它接下去。
這裡用「把舊快取字串存回 localStorage」模擬 B 裝置——B 裝置的本質就是
「一份不知道結束已發生的快取」，跟它跑在哪台機器無關。

①②③⑧（欄位、端點冪等、migration）由 pytest 涵蓋，不在這裡重複。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
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


def raw_cache(page) -> str | None:
    return page.evaluate(f"() => localStorage.getItem('{WORKOUT_KEY}')")


def put_cache(page, raw: str) -> None:
    page.evaluate(
        f"(v) => localStorage.setItem('{WORKOUT_KEY}', v)",
        raw,
    )


def home_button_label(page) -> str:
    for name in ("繼續訓練", "開始訓練", "挑一份課表"):
        if page.get_by_role("button", name=name).count():
            return name
    return "(找不到入口)"


def start_free_workout(page) -> None:
    start_from_home(page)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(600)
    page.locator(".ex-row, .exercise-row, button").filter(has_text="深蹲").first.click()
    page.wait_for_timeout(600)


def finish_workout(page) -> None:
    """結束這場訓練。「結束訓練」只在選動作頁，logger 要先退回去（同 verify_f70 的做法）。"""
    if not page.get_by_role("button", name="結束訓練").count():
        page.locator(".logger-back").first.click()
        page.wait_for_timeout(600)
    page.get_by_role("button", name="結束訓練").first.click()
    page.wait_for_timeout(2000)


def log_one_set(page) -> None:
    page.get_by_role("button", name="完成這組").click()
    page.wait_for_timeout(900)
    nxt = page.get_by_role("button", name="繼續下一組")
    if nxt.count():
        nxt.first.click()
        page.wait_for_timeout(700)


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f91_e2e_{port}.db"
    release = REPO / f"liftlog_f91_release_{port}"
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

            # ---------- 前置：記 2 組，留下「B 裝置的快取」 ----------
            start_free_workout(page)
            log_one_set(page)
            log_one_set(page)
            page.wait_for_timeout(500)
            wid = api(base, "/api/workouts")[0]["id"]
            device_b_cache = raw_cache(page)
            check(device_b_cache is not None, "前置：取得結束前的快取（模擬 B 裝置那份）")
            check(
                api(base, f"/api/workouts/{wid}")["ended_at"] is None,
                "③ 進行中的 workout，ended_at 為 null",
            )

            # ---------- ④ 前端結束訓練會通知伺服器 ----------
            finish_workout(page)
            ended_at = api(base, f"/api/workouts/{wid}")["ended_at"]
            check(
                ended_at is not None,
                f"④ 按「結束訓練」後伺服器記下 ended_at（實際 {ended_at}）",
            )
            check(
                home_button_label(page) != "繼續訓練",
                f"④ 結束後回到首頁且不顯示繼續訓練（實際「{home_button_label(page)}」）",
            )

            # ---------- ⑤⑨ B 裝置的舊快取不得續接（F90 ④ fail 的那條） ----------
            put_cache(page, device_b_cache)
            check(raw_cache(page) is not None, "前置：把結束前的舊快取放回去（B 裝置重整前的狀態）")
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2200)
            check(
                raw_cache(page) is None,
                "⑤⑨ 伺服器說已結束 → 清掉本地狀態",
            )
            check(
                home_button_label(page) != "繼續訓練",
                f"⑤⑨ 已結束的訓練不得續接（實際「{home_button_label(page)}」）",
            )

            # ---------- ⑥ 已結束的 workout 仍接受寫入 ----------
            # 離線佇列裡先記的組必須補得進去；擋下來會讓那些組被標 failed 而遺失。
            queued_set = {
                "client_uuid": "f91e2e00-0000-4000-8000-000000000001",
                "exercise_id": api(base, f"/api/workouts/{wid}")["sets"][0]["exercise_id"],
                "set_number": 99,
                "weight_kg": 60.0,
                "reps": 5,
            }
            req = urllib.request.Request(
                f"{base}/api/workouts/{wid}/sets",
                data=json.dumps(queued_set).encode(),
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req) as r:
                status = r.status
            check(status in (200, 201), f"⑥ 已結束的 workout 仍接受 POST sets（HTTP {status}）")
            numbers = sorted(s["set_number"] for s in api(base, f"/api/workouts/{wid}")["sets"])
            check(numbers == [1, 2, 99], f"⑥ 補傳的組真的寫進去了（實際 {numbers}）")

            # ---------- ⑦ F90 的行為不回歸 ----------
            start_free_workout(page)
            log_one_set(page)
            page.wait_for_timeout(500)
            page.evaluate("() => sessionStorage.clear()")
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2200)
            check(
                home_button_label(page) == "繼續訓練",
                f"⑦ F90 不回歸：新開的訓練被回收後仍可續接（實際「{home_button_label(page)}」）",
            )
            check(
                raw_cache(page) is not None,
                "⑦ F90 不回歸：未結束的訓練不得被 ended_at 檢查誤殺",
            )

            # ⑦ 離線仍不清（F90 ④ 的離線分支）
            before = raw_cache(page)
            ctx.set_offline(True)
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            check(
                raw_cache(page) == before,
                "⑦ F90 不回歸：離線時不得把本地狀態清掉",
            )
            ctx.set_offline(False)

            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
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
