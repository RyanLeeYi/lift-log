"""F99 E2E：計時頁組列清單的固定高度必須是整數列，不得切在半列上。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f99.py`

⚠ 量的是**實際渲染高度**與**實際列高**的關係，不是讀 CSS 宣告值——
   宣告 `calc(var(--done-row-h) * 2 + …)` 看起來很對，但 --done-row-h 猜錯一樣會切半列。
   唯一能揭穿它的方式是拿可視高度去除以量到的列高。

⚠ 反面：1／2 筆時**不得**限高（沒有東西被截斷卻先把自己關進盒子裡是另一種壞）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
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


def start_workout(page) -> None:
    """從首頁開始一次訓練並進到某個動作的 logger。"""
    wait_home(page)
    start_from_home(page)
    page.wait_for_timeout(1200)
    page.locator(".exercise-item").first.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(500)


def log_sets(page, n: int) -> None:
    for _ in range(n):
        page.locator(".log-btn").first.click()
        page.wait_for_timeout(700)
        # 記完會進休息態；把休息停掉才看得到就緒態的版面
        stop = page.locator(".rest-card").get_by_role("button", name="停止")
        if stop.count():
            stop.first.click()
            page.wait_for_timeout(400)


def metrics(page) -> dict:
    return page.evaluate(
        """() => {
             const list = document.querySelector('.done-list');
             if (!list) return null;
             const rows = [...list.querySelectorAll('.done-row')];
             const cs = getComputedStyle(list);
             const padY = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
             const gap = parseFloat(cs.rowGap) || 0;
             return {
               scrollable: list.classList.contains('scrollable'),
               clientH: list.clientHeight,
               scrollH: list.scrollHeight,
               rowH: rows.length ? rows[0].getBoundingClientRect().height : 0,
               rows: rows.length,
               padY, gap,
               masked: cs.maskImage !== 'none' || cs.webkitMaskImage !== 'none',
             };
           }"""
    )


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f99-"))
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


def whole_rows(m: dict) -> float:
    """可視區裝得下幾列（含列間距）。整數＝沒有切半列。"""
    usable = m["clientH"] - m["padY"]
    return (usable + m["gap"]) / (m["rowH"] + m["gap"])


def run_checks(base: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        start_workout(page)

        # 1 筆與 2 筆：反面——沒有東西被截斷就不該限高
        log_sets(page, 1)
        m = metrics(page)
        check(m is not None and m["rows"] == 1, f"前提：記一組後有一列（{m and m['rows']}）")
        check(not m["scrollable"], "反面：1 筆不限高（沒東西被截斷就不要關進盒子）")

        log_sets(page, 1)
        m = metrics(page)
        check(m["rows"] == 2, f"前提：兩筆（{m['rows']}）")
        check(not m["scrollable"], "反面：2 筆不限高（F20 訂的門檻是 >2）")
        h2 = m["clientH"]  # F111：第三筆之後不得比這個還矮

        # 3 筆：開始限高，這裡是本條的重點
        log_sets(page, 1)
        m = metrics(page)
        check(m["rows"] == 3 and m["scrollable"], f"3 筆時限高生效（rows={m['rows']}）")
        n = whole_rows(m)
        check(
            abs(n - round(n)) <= 0.06,
            f"① 可視區是**整數列**，沒有切在半列上（實測裝得下 {n:.2f} 列；"
            f"clientH={m['clientH']:.0f} rowH={m['rowH']:.0f} pad={m['padY']:.0f}）",
        )
        check(n >= 1, f"③ 至少裝得下一整列（{n:.2f}）")
        check(round(n) == 2, f"① 維持 F20 的「約兩列」意圖（實測 {round(n)} 列）")
        # F111（Ryan 2026-08-01：「超過兩組的時候，最少要能顯示兩組的大小」）：
        # ⚠ 這條是本支最容易被漏掉的——原本只驗「高度是列高的整數倍」，而 69px（1 列）
        # 完全符合那個條件，所以「記到第三組時清單在眼前縮掉一半」是**全綠**通過的。
        # 驗的是「不得比上一個狀態更矮」，不是「符合某個公式」。
        check(
            m["clientH"] >= h2 - 1,
            f"F111：記到第三筆**不得**讓清單變矮（2 筆 {h2:.0f} → 3 筆 {m['clientH']:.0f}）",
        )
        check(m["scrollH"] > m["clientH"] + 1, "3 筆時真的捲得動（有東西被截斷）")
        check(m["masked"], "④ 有下緣淡出當「下面還有」的線索")

        # 6 筆：列數再多，可視高度不變（下方 steppers 位置不被推走）
        h3 = m["clientH"]
        log_sets(page, 3)
        m = metrics(page)
        check(m["rows"] == 6, f"前提：六筆（{m['rows']}）")
        check(
            abs(m["clientH"] - h3) <= 1,
            f"① 列數再多，可視高度不變（3 筆 {h3:.0f} → 6 筆 {m['clientH']:.0f}）",
        )
        n = whole_rows(m)
        check(abs(n - round(n)) <= 0.06, f"① 六筆時仍是整數列（{n:.2f}）")

        # F111：矮螢幕不再降成一列。原本降一列的後果是「記到第三組時清單縮掉一半」，
        # 比 F99 要修的那個 bug 更難看；而 2 筆時清單本來就是兩列高且不溢出，
        # 可見「矮螢幕放不下兩列」這個假設本身是錯的（384×727 實測）。
        for size in ({"width": 384, "height": 727}, {"width": 390, "height": 640}):
            page.set_viewport_size(size)
            page.wait_for_timeout(400)
            m = metrics(page)
            n = whole_rows(m)
            label = f"{size['width']}×{size['height']}"
            check(
                round(n) >= 2,
                f"F111 {label}：超過兩組時至少顯示兩列（實測 {n:.2f} 列；"
                f"clientH={m['clientH']:.0f} rowH={m['rowH']:.0f}）",
            )
            check(abs(n - round(n)) <= 0.06, f"③ {label} 仍是整數列（{n:.2f}）")

        # ⑤ F16 不回歸：進入行內編輯時不限高（編輯表單要完整可見）
        page.set_viewport_size(PHONE)
        page.wait_for_timeout(300)
        page.locator(".done-row .icon-btn").first.click()
        page.wait_for_timeout(600)
        m = metrics(page)
        check(
            not m["scrollable"],
            "⑤ F16 不回歸：行內編輯時不限高（編輯表單要完整可見）",
        )

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
