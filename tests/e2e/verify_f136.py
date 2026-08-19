"""F136 E2E：折線圖浮動資訊的鍵盤與螢幕閱讀器入口（承 F134 code review 開出的 P3），①–③。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f136.py`

沿用 verify_f86.seed 的五筆遞增深蹲資料（verify_f134 也用同一份種子），不重種另一份——
動作表現頁本身的圖表行為（PR 標記、命中判定、邊界情況）已由 verify_f134／verify_f86 覆蓋，
這裡只加鍵盤／aria 這條新入口。量測一律問渲染結果（getAttribute／document.activeElement／
實際文字），不問 class 名稱有沒有掛上去。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ①②③ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138 同款防呆）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, safe_port, setup_and_home, start_server  # noqa: E402
from verify_f86 import seed as seed_squat  # noqa: E402
from verify_f134 import open_detail, tip_texts  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def md(iso_date: str) -> str:
    """跟 exercise-detail.js 的日期渲染同一份算式：MM-DD → MM/DD。"""
    return iso_date[5:].replace("-", "/")


def active_label(page) -> str | None:
    return page.evaluate(
        "() => document.activeElement && document.activeElement.getAttribute('aria-label')"
    )


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f136-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        seed_squat(base)
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


def run_checks(base: str) -> None:  # noqa: C901
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        open_detail(page, "腿", "深蹲")

        pts = page.locator(".line-pt")
        n = pts.count()
        check(n == 5, f"（前置）五次訓練＝五個資料點（實際 {n}）")

        # ① 每個資料點都是鍵盤可達的 button
        labels = page.eval_on_selector_all(
            ".line-pt", "els => els.map(e => e.getAttribute('aria-label'))"
        )
        roles = page.eval_on_selector_all(
            ".line-pt", "els => els.map(e => e.getAttribute('role'))"
        )
        tabs = page.eval_on_selector_all(
            ".line-pt", "els => els.map(e => e.getAttribute('tabindex'))"
        )
        check(all(r == "button" for r in roles),
              f"① 每個 .line-pt 都有 role=button（實際 {roles}）")
        check(all(t == "0" for t in tabs), f"① 每個 .line-pt 都有 tabindex=0（實際 {tabs}）")

        dates = [lbl.split(" ")[0] for lbl in labels]
        check(dates == sorted(dates), f"③ .line-pt 的 DOM 順序已是日期左舊右新（{dates}）")

        # ③ 真正用 Tab 走過去：從最後一顆檔位藥丸（「全部」，圖表正上方最後一個可聚焦元素）
        # 依序按 Tab，落點應該剛好是五個資料點、順序與上面量到的日期順序一致——
        # 這是「Tab 走到資料點」＋「焦點順序＝視覺順序」的直接證據，不是只驗屬性存在。
        page.locator('.range-pills button:has-text("全部")').focus()
        for i in range(n):
            page.keyboard.press("Tab")
            page.wait_for_timeout(80)
            check(active_label(page) == labels[i],
                  f"③ 第 {i + 1} 次 Tab 落在第 {i + 1} 個資料點（{active_label(page)!r}）")

        # 焦點現在停在最後一個點（Tab 迴圈跑完）。用 focus() 跳回第一個點測 Enter/Esc/Space——
        # 等價於使用者繼續按 Shift+Tab 回到第一個點，這裡省開發時間，不改變上面已經用
        # 真正的 Tab 鍵驗過整條順序這個事實。
        pts.nth(0).focus()
        check(active_label(page) == labels[0], "（前置）焦點回到第一個資料點")

        # ① Enter 開啟：走跟滑鼠點擊同一個選中分支（selectChartPoint）
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "① Enter 開啟浮動資訊")
        check(page.locator(".line-pt.sel").count() == 1, "① Enter 開啟後選中狀態可見（.sel）")
        check(active_label(page) == labels[0],
              "① Enter 開啟後焦點仍在該點上（rerender 整個換 DOM，已補焦點還原）")

        # ② 內容出現在 role=status 節點，且與選中的點一致
        check(page.locator('.line-tip[role="status"]').count() == 1,
              "② .line-tip 是 role=status（隱含 aria-live=polite），內容變更會被朗讀")
        d, s, b = tip_texts(page)
        check(d == md(dates[0]), f"② 浮動資訊日期與選中點一致（{d!r} vs {md(dates[0])!r}）")

        # ① 換到另一個點按 Enter：只換內容、不累積第二個框——證明鍵盤與滑鼠共用同一個
        # toggle 分支（不是各自維護一套邏輯），對應 F134 ⑤ 滑鼠版本的同一條斷言。
        pts.nth(2).focus()
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1,
              "① 換到別的點按 Enter：只有一個浮動框（不累積）")
        d2, _s2, _b2 = tip_texts(page)
        check(d2 == md(dates[2]), f"① 內容已換成新選中的點（{d!r} → {d2!r}）")

        # 換回第一個點，接續驗 Esc／Space
        pts.nth(0).focus()
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "（前置）第一個點重新選中")

        # ③ Esc 關閉浮動資訊，且焦點保留在該點上
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 0, "③ Esc 關閉浮動資訊")
        check(page.locator(".line-pt.sel").count() == 0, "③ Esc 關閉：選中狀態一併清除")
        check(active_label(page) == labels[0],
              "③ Esc 關閉後焦點仍保留在該點上（document.activeElement）")

        # ① Space 亦可開啟（同一個選中分支）
        page.keyboard.press(" ")
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "① Space 也能開啟浮動資訊")
        d3, _s3, _b3 = tip_texts(page)
        check(d3 == md(dates[0]), f"① Space 開啟的內容正確（{d3!r}）")
        check(active_label(page) == labels[0], "① Space 開啟後焦點仍在該點上")

        # ① Space 再按一次同一個已選中的點：走同一個 toggle 分支關閉
        page.keyboard.press(" ")
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 0,
              "① Space 再按一次同一個已選中的點：toggle 關閉（同滑鼠 F134 ⑤ 行為）")

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
