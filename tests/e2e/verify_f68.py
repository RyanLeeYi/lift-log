"""F68 E2E：更新提示改懸浮視窗（①–⑧）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f68.py`

沿用 F67 的假 plugin 與導流設定（同一套執行環境），只驗 F68 新增的呈現與記憶行為。
下載／安裝的原生路徑由 F67 覆蓋，這裡不重驗（⑤ 明文如此）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    REPO,
    free_port,
    native,
    setup_and_home,
    start_server,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def modal(page):
    return page.locator(".update-modal")


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f68_e2e_{port}.db"
    release = REPO / f"liftlog_f68_release_{port}"
    release.mkdir(exist_ok=True)
    (release / "lift-log-v99.apk").write_bytes(b"PK\x03\x04" + b"x" * 2_000_000)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # ① 開 app 進首頁即自動彈窗
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=64)
            setup_and_home(page)
            check(modal(page).count() == 1, f"① 有新版時首頁自動彈出視窗（{modal(page).count()}）")
            text = modal(page).inner_text() if modal(page).count() else ""
            check("v99" in text, f"① 視窗顯示新版版號：{text!r}")
            check("MB" in text, "① 視窗顯示檔案大小")
            check(page.locator(".modal-overlay").count() == 1, "① 是懸浮置中視窗（有遮罩）")
            check(page.get_by_role("button", name="立即更新").count() == 1, "① 有「立即更新」")
            check(page.get_by_role("button", name="稍後再說").count() == 1, "① 有「稍後再說」")

            # ② 稍後再說 → 關閉並記住該版本
            page.get_by_role("button", name="稍後再說").click()
            page.wait_for_timeout(400)
            check(modal(page).count() == 0, "② 稍後再說會關閉視窗")
            dismissed = page.evaluate("() => localStorage.getItem('liftlog.updateDismissed')")
            check(dismissed == "99", f"② 記住的是版本號而非布林（{dismissed!r}）")

            # ③ 關閉後不留橫幅，提示與入口都併進版號
            check(page.locator(".update-banner").count() == 0, "③ 不再有獨立的更新橫幅")
            entry = page.locator(".version-tag-btn.has-update")
            check(entry.count() == 1, "③ 版號標示有新版（提示與入口合一）")
            check("v99" in entry.inner_text(),
                  f"③ 版號顯示目標版本：{entry.inner_text()!r}")
            entry.click()
            page.wait_for_timeout(400)
            check(modal(page).count() == 1, "③ 點版號可重新開啟視窗——稍後再說不是死路")
            page.get_by_role("button", name="稍後再說").click()
            page.wait_for_timeout(300)

            # ④ 只在首頁：進到別的畫面不得有視窗或橫幅
            page.get_by_role("button").first.click()  # 開練
            page.wait_for_timeout(900)
            check(modal(page).count() == 0
                  and page.locator(".version-tag-btn.has-update").count() == 0,
                  "④ 離開首頁後視窗與更新入口都不出現（訓練中不打斷）")
            ctx.close()

            # ② 同一版本重開 app 不再自動彈（靜音只對該版本）
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=64)
            page.evaluate("() => localStorage.setItem('liftlog.updateDismissed', '99')")
            setup_and_home(page)
            check(modal(page).count() == 0, "② 同一版本已按過稍後再說 → 不再自動彈")
            check(page.locator(".version-tag-btn.has-update").count() == 1,
                  "② 但版號仍標著有新版（還能主動更新）")

            # ② 出現更新的版本 → 重新自動彈
            page.evaluate("() => localStorage.setItem('liftlog.updateDismissed', '70')")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            check(modal(page).count() == 1, "② 有更新的版本時重新自動彈（不是按一次就永久靜音）")
            ctx.close()

            # ⑦ 版號可點手動檢查：已是最新 → 短暫提示
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=99)
            setup_and_home(page)
            check(page.locator(".version-tag-btn").count() == 1, "⑦ app 版版號是可點的按鈕")
            check(page.locator(".version-tag-btn.has-update").count() == 0,
                  "⑦ 沒有更新時版號不標示（純版號）")
            page.locator(".version-tag-btn").click()
            page.wait_for_timeout(600)
            flash = page.locator(".update-flash")
            check(flash.count() == 1 and "最新" in flash.inner_text(),
                  f"⑦ 沒有新版時提示已是最新：{flash.inner_text() if flash.count() else '(無)'}")
            ctx.close()

            # ⑦ 手動檢查查到新版 → 直接開視窗，且不受靜音影響
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=64)
            page.evaluate("() => localStorage.setItem('liftlog.updateDismissed', '99')")
            setup_and_home(page)
            check(modal(page).count() == 0, "（前提）已靜音，開場沒有自動彈")
            page.locator(".version-tag-btn").click()
            page.wait_for_timeout(900)
            check(modal(page).count() == 1, "⑦ 手動檢查到新版會開視窗，不受稍後再說的靜音影響")
            ctx.close()

            # ⑧ web 版：不彈視窗、版號不可點
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            check(modal(page).count() == 0, "⑧ web 版不彈更新視窗")
            check(page.locator(".version-tag-btn").count() == 0, "⑧ web 版版號不可點")
            check(page.locator(".version-tag").count() == 1, "⑧ web 版版號仍顯示（純文字）")
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
