"""F92 E2E：空的 workout 不該看起來像練過（②③⑥⑧）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f92.py`

①④ 是定義與熱力格子——熱力圖本來就 join sets 濾軟刪除（`calendar_tonnage`），
這裡驗它與明細卡對同一天的說法一致。⑤⑩ 的端點兩條路由 pytest 涵蓋。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date
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

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, path: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as r:
        body = r.read()
    return json.loads(body) if body else None


def open_calendar(page) -> None:
    page.locator(".bottom-nav").get_by_role("button", name="日曆").click()
    page.wait_for_selector(".screen.calendar", timeout=10_000)
    page.wait_for_timeout(600)


def click_today_cell(page) -> None:
    page.locator(f'.cal-day[aria-label="{date.today().isoformat()}"]').click()
    page.wait_for_timeout(900)


def detail_text(page) -> str:
    node = page.locator(".cal-detail-head .d, .cal-empty").first
    return node.inner_text() if node.count() else "(沒有明細)"


def start_free_workout(page) -> None:
    start_from_home(page)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(600)


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f92_e2e_{port}.db"
    release = REPO / f"liftlog_f92_release_{port}"
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

            # ---------- ② 只有空 workout 的一天要顯示「休息日」 ----------
            empty_id = api(base, "/api/workouts", "POST", {})["id"]
            check(
                len(api(base, "/api/workouts")) == 1,
                "前置：伺服器上有一場空 workout",
            )
            open_calendar(page)
            click_today_cell(page)
            text = detail_text(page)
            check(
                "休息日" in text,
                f"② 只有空 workout 的一天顯示「休息日」（實際「{text}」）",
            )
            check(
                "·" not in text or "休息日" in text,
                f"③ 不顯示課表名（實際「{text}」）",
            )

            # ---------- ①④ 熱力格子與明細卡對同一天說法一致 ----------
            today = date.today()
            stats = api(base, f"/api/stats/calendar?year={today.year}&month={today.month}")
            check(
                date.today().isoformat() not in stats["days"],
                f"①④ 空 workout 不進熱力圖（days={list(stats['days'])}）",
            )

            # ---------- ⑤ 端點：空的可刪 ----------
            req = urllib.request.Request(
                f"{base}/api/workouts/{empty_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
                method="DELETE",
            )
            with urllib.request.urlopen(req) as r:
                check(r.status == 204, f"⑤ 空 workout 可刪除（HTTP {r.status}）")

            # ---------- ⑥ 沒記東西就結束 → 刪掉而不是留一場空的 ----------
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            start_free_workout(page)
            before = len(api(base, "/api/workouts"))
            check(before == 1, f"前置：按開始訓練後伺服器有 1 場（實際 {before}）")
            page.get_by_role("button", name="結束訓練").first.click()
            page.wait_for_timeout(2200)
            after = len(api(base, "/api/workouts"))
            check(
                after == 0,
                f"⑥ 一組都沒記就結束 → 那場被刪掉，不留空 workout（實際剩 {after} 場）",
            )

            # ---------- ⑥ 有記東西就不刪，走正常結束 ----------
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            start_free_workout(page)
            page.locator(".ex-row, .exercise-row, button").filter(
                has_text="深蹲"
            ).first.click()
            page.wait_for_timeout(700)
            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(1000)
            nxt = page.get_by_role("button", name="繼續下一組")
            if nxt.count():
                nxt.first.click()
                page.wait_for_timeout(600)
            page.locator(".logger-back").first.click()
            page.wait_for_timeout(700)
            page.get_by_role("button", name="結束訓練").first.click()
            page.wait_for_timeout(2200)
            kept = api(base, "/api/workouts")
            check(
                len(kept) == 1,
                f"⑥ 有記組的訓練不得被刪（實際剩 {len(kept)} 場）",
            )
            check(
                kept and kept[0]["ended_at"] is not None,
                "⑥ 有記組時走正常結束流程（F91 的 ended_at 有設）",
            )

            # ---------- ②③ 有練的一天照常顯示課表名／明細 ----------
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            open_calendar(page)
            click_today_cell(page)
            text = detail_text(page)
            check(
                "休息日" not in text,
                f"②③ 真的練過的一天不得顯示休息日（實際「{text}」）",
            )

            # ---------- ⑧ F90／F91 不回歸（快速冒煙） ----------
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            start_free_workout(page)
            page.locator(".ex-row, .exercise-row, button").filter(
                has_text="深蹲"
            ).first.click()
            page.wait_for_timeout(700)
            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(1000)
            page.evaluate("() => sessionStorage.clear()")
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2200)
            resumed = page.get_by_role("button", name="繼續訓練").count() > 0
            check(resumed, "⑧ F90 不回歸：被回收後仍可續接")

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
