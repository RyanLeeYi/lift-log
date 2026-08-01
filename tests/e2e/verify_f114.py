"""F114 E2E：日曆頁不產生頁面捲動，標題與「補記這一天」同時可見。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f114.py`

Ryan 2026-08-01：「訓練日曆那邊是不是能夠調整訓練組數的高度，畫面不要能夠上下滑
就能夠同時看到訓練日曆字樣跟補記這一天的按鈕」。

⚠ 這支要驗的是**版面關係**，不是某個 px 值：
  - 頁面本身不得捲動（docH ≤ winH）
  - 標題與補記鈕同時在可視區內
  - 被截斷的是**動作區塊**（內部捲動），不是整頁
  - 補記鈕在捲動區**外**（捲動時它不會跟著跑掉）
寫死高度的斷言會在字級或間距一改就變成假的——F99 已經上過這一課。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
    wait_home,
)

RYAN = {"width": 384, "height": 727}

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


LAYOUT = """() => {
  const q = s => document.querySelector(s);
  const head = q('.screen-head h1');
  const add = [...document.querySelectorAll('button')]
    .find(b => b.textContent.includes('補記這一天'));
  const scroller = q('.cal-ex-scroll');
  const hb = head && head.getBoundingClientRect();
  const ab = add && add.getBoundingClientRect();
  return {
    over: document.documentElement.scrollHeight - window.innerHeight,
    headVisible: !!(hb && hb.top >= 0 && hb.bottom <= window.innerHeight),
    addVisible: !!(ab && ab.top >= 0 && ab.bottom <= window.innerHeight),
    hasScroller: !!scroller,
    scrollerClips: scroller ? scroller.scrollHeight > scroller.clientHeight + 1 : false,
    addInsideScroller: !!(scroller && add && scroller.contains(add)),
  };
}"""


def log_sets_on(page, index: int, n: int) -> None:
    """在第 index 個動作上記 n 組，然後回菜單。"""
    page.locator(".exercise-item").nth(index).click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(400)
    for _ in range(n):
        page.locator(".log-btn").first.click()
        page.wait_for_timeout(700)
        stop = page.locator(".rest-card").get_by_role("button", name="停止")
        if stop.count():
            stop.first.click()
            page.wait_for_timeout(400)
    page.locator(".logger-back").first.click()
    page.wait_for_timeout(700)


def open_calendar(page) -> None:
    page.get_by_role("button", name="回首頁").first.click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="日曆").first.click()
    page.wait_for_timeout(1500)
    page.locator(".cal-day:not(.future)").last.click()
    page.wait_for_timeout(1200)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f114-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        run_checks(base)
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


def run_checks(base: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=RYAN)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)

        wait_home(page)
        start_from_home(page)
        page.wait_for_timeout(1200)

        # ── 一個動作 ────────────────────────────────────────────
        log_sets_on(page, 0, 4)
        open_calendar(page)
        m = page.evaluate(LAYOUT)
        check(m["over"] <= 1, f"① 一個動作：頁面不捲動（溢出 {m['over']}px）")
        check(m["headVisible"] and m["addVisible"], "① 標題與「補記這一天」同時可見")
        check(m["hasScroller"], "② 動作區塊永遠在捲動容器裡（不再是 >3 個才捲）")
        check(not m["addInsideScroller"], "③ 補記鈕在捲動區**外**，捲動時不會跟著跑掉")

        # ── 多個動作：被截斷的是清單，不是整頁 ───────────────────
        page.get_by_role("button", name="回首頁").first.click()
        page.wait_for_timeout(1000)
        start_from_home(page)
        page.wait_for_timeout(1200)
        for i in (1, 2, 3):
            log_sets_on(page, i, 3)
        open_calendar(page)
        m = page.evaluate(LAYOUT)
        check(m["over"] <= 1, f"① 四個動作：頁面仍不捲動（溢出 {m['over']}px）")
        check(m["headVisible"] and m["addVisible"], "① 四個動作時兩者仍同時可見")
        check(
            m["scrollerClips"],
            "② 內容變多時被截斷的是**動作區塊**（它自己捲），不是整頁",
        )
        check(not m["addInsideScroller"], "③ 補記鈕仍在捲動區外")

        # ── ⑤ 其他尺寸 ─────────────────────────────────────────
        for size in ({"width": 390, "height": 844}, {"width": 360, "height": 640}):
            page.set_viewport_size(size)
            page.wait_for_timeout(500)
            m = page.evaluate(LAYOUT)
            label = f"{size['width']}×{size['height']}"
            check(m["over"] <= 1, f"⑤ {label} 不捲動（溢出 {m['over']}px）")
            check(m["headVisible"] and m["addVisible"], f"⑤ {label} 兩者同時可見")

        # ── ⑥ 不回歸：休息日仍不顯示明細卡、補記入口還在 ─────────
        page.set_viewport_size(RYAN)
        page.wait_for_timeout(400)
        page.locator(".cal-day:not(.future)").first.click()  # 月初，多半沒練
        page.wait_for_timeout(1000)
        rest_day = page.evaluate(
            """() => ({
                 empty: !!document.querySelector('.cal-empty'),
                 add: [...document.querySelectorAll('button')]
                   .some(b => b.textContent.includes('補記這一天')),
                 over: document.documentElement.scrollHeight - window.innerHeight,
               })"""
        )
        check(rest_day["add"], "⑥ F41 不回歸：休息日仍有補記入口")
        check(rest_day["over"] <= 1, f"① 休息日也不捲動（溢出 {rest_day['over']}px）")

        ctx.close()
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
