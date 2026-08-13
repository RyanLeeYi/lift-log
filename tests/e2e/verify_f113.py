"""F113 E2E：組列的編輯改成懸浮視窗（取代行內展開）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f113.py`

Ryan 2026-08-01：「訓練頁面的編輯動作按鈕改成點了以後出現懸浮視窗」。

⚠ 這支的重點不是「有沒有跳視窗」，而是 ③——**資料行為完全沒變**。
編輯是唯一會回頭改動已記資料的入口，換一個殼很容易把 PATCH 那條路弄丟，
而畫面上看起來一切正常（視窗有開、按了儲存、視窗關了），只有資料是舊的。
所以儲存之後要驗**組列上真的變成新值**，而且**重整後仍是新值**（＝真的寫到伺服器）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


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


def into_logger(page) -> None:
    wait_home(page)
    start_from_home(page)
    page.wait_for_timeout(1200)
    page.locator(".exercise-item").first.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(500)


def log_set(page) -> None:
    page.locator(".log-btn").first.click()
    page.wait_for_timeout(800)
    stop = page.locator(".rest-card").get_by_role("button", name="停止")
    if stop.count():
        stop.first.click()
        page.wait_for_timeout(500)


def modal(page):
    return page.locator(".edit-set-modal")


def list_height(page) -> float:
    box = page.locator(".done-list").first.bounding_box()
    return box["height"] if box else 0


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f113-"))
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
        into_logger(page)
        for _ in range(3):
            log_set(page)
        check(page.locator(".done-row").count() == 3, "前提：記了三組")

        # ── ① 點編輯 → 開視窗，不是就地展開 ──────────────────────
        h_before = list_height(page)
        page.locator(".done-row .edit-set").first.click()
        page.wait_for_timeout(600)
        check(modal(page).count() == 1, "① 點編輯鈕開懸浮視窗")
        check(
            page.locator(".done-row.editing").count() == 0,
            "① 反面：不再就地展開成行內表單（.done-row.editing 不存在）",
        )
        check(
            "#" in modal(page).locator(".modal-head").inner_text(),
            f"② 視窗標題指出在編輯第幾組"
            f"（{modal(page).locator('.modal-head').inner_text()!r}）",
        )
        check(
            modal(page).locator(".stepper").count() == 2
            and modal(page).locator(".rpe-picker, .rpe-axis, [class*=rpe]").count() >= 1,
            "② 視窗內有重量／次數步進器與累度軸",
        )

        # ── ⑤ 清單高度不因編輯改變 ──────────────────────────────
        check(
            abs(list_height(page) - h_before) <= 1,
            f"⑤ 開視窗時組列清單高度不變（{h_before:.0f} → {list_height(page):.0f}）——"
            f"行內展開時代為了讓表單可見會取消限高，那個理由已經消失",
        )

        # ── ④ 點遮罩＝取消 ─────────────────────────────────────
        before_text = page.locator(".done-row").first.inner_text()
        page.locator(".modal-overlay").first.click(position={"x": 5, "y": 5})
        page.wait_for_timeout(600)
        check(modal(page).count() == 0, "④ 點遮罩關窗")
        check(
            page.locator(".done-row").first.inner_text() == before_text,
            "④ 反面：取消不得改動那一組",
        )

        # ── ③ 儲存：資料行為不變（本支的重點）────────────────────
        # 從實際值推期望值，不寫死——種子資料的預設重量改了就會讓斷言變成假的
        before_kg = float(
            page.locator(".done-row").first.inner_text().split("kg")[0].split()[-1]
        )
        expected = before_kg + 5  # +2.5 兩下
        page.locator(".done-row .edit-set").first.click()
        page.wait_for_timeout(600)
        plus = modal(page).locator(".stepper").first.locator(".pair .btn").last
        plus.click()
        plus.click()
        page.wait_for_timeout(400)
        modal(page).get_by_role("button", name="儲存").click()
        page.wait_for_timeout(1200)
        check(modal(page).count() == 0, "③ 儲存後關窗")
        top = page.locator(".done-row").first.inner_text()
        check(
            f"{expected:g}" in top,
            f"③ 組列上是修改後的值（{before_kg:g} → 期望 {expected:g}；實際 {top!r}）",
        )

        # 真的寫到伺服器：重整之後仍是新值
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        into_logger(page)
        if page.locator(".rest-card").count():
            page.locator(".log-btn").first.click()
            page.wait_for_timeout(800)
        top = page.locator(".done-row").first.inner_text()
        check(
            f"{expected:g}" in top,
            f"③ **重整後仍是新值**＝真的寫到伺服器，不是只改了畫面（{top!r}）",
        )

        # ── ⑦ 不回歸：刪除仍是單擊即刪 ──────────────────────────
        rows = page.locator(".done-row").count()
        page.locator(".done-row .del-set").first.click()
        page.wait_for_timeout(1200)
        check(
            page.locator(".done-row").count() == rows - 1,
            f"⑦ F19 不回歸：刪除仍是單擊即刪（{rows} → {page.locator('.done-row').count()}）",
        )

        # ── ⑧ 觸控與溢出 ───────────────────────────────────────
        page.locator(".done-row .edit-set").first.click()
        page.wait_for_timeout(600)
        small = [
            b
            for b in (
                modal(page).locator("button").nth(i).bounding_box()
                for i in range(modal(page).locator("button").count())
            )
            if b and (b["width"] < 44 or b["height"] < 44)
        ]
        check(not small, f"⑧ 視窗內按鈕都 ≥44px（不足 {len(small)} 顆）")
        for size in (RYAN, {"width": 360, "height": 640}):
            page.set_viewport_size(size)
            page.wait_for_timeout(400)
            fits = page.evaluate(
                """() => {
                     const m = document.querySelector('.edit-set-modal');
                     if (!m) return null;
                     const r = m.getBoundingClientRect();
                     return r.top >= -1 && r.bottom <= window.innerHeight + 1
                       && r.left >= -1 && r.right <= window.innerWidth + 1;
                   }"""
            )
            check(fits is True, f"⑧ {size['width']}×{size['height']} 視窗完整在畫面內")

        ctx.close()
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
