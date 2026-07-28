"""F73 E2E：鬧鐘響起時「停止」變色提示（①③⑤ 的可驗面）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f73.py`

② 浮動視窗的變色只能在裝置上看（acceptance ⑥ 也這樣寫），這裡驗原生原始碼的靜態約束
與 app 內按鈕的實際 class 切換——後者用真實 UI 跑到超時，不是讀 code 推論。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, free_port, setup_and_home, start_server  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def source_checks() -> None:
    overlay = (REPO / "android/app/src/main/java/com/ryanleeyi/liftlog/RestOverlay.java").read_text(
        encoding="utf-8")
    check("applyAlarmTint" in overlay, "② 浮動視窗的停止鈕會換色")
    # 實測抓到的坑：⏹ 是 emoji，emoji 是彩色字形，setTextColor 對它無效——
    # 第一版改文字色，畫面上完全看不出變化。要改的是 view 的底色。
    tint = overlay.split("applyAlarmTint(boolean alarming)")[1].split("\n    }")[0]
    check("setBackground" in tint and "setTextColor" not in tint,
          "② 用底色而非文字色（emoji 吃不到 setTextColor）")
    check("remainingSeconds < 0 && !paused" in overlay,
          "③ 只有「超時且非暫停」才算響著（暫停中不變色）")

    css = (REPO / "app/static/css/app.css").read_text(encoding="utf-8")
    check(".alarming" in css, "① 警示樣式存在")

    app_js = (REPO / "app/static/js/app.js").read_text(encoding="utf-8")
    ticker = app_js.split("restTicker = setInterval")[1].split("}, 1000)")[0]
    # 跨越 0 的那一刻沒有 render()，所以 ticker 也要切 class，否則要等下次重繪才變色
    check("alarming" in ticker, "① 跨越 0 秒的當下就變色（不必等下一次重繪）")


def start_free_workout(page) -> None:
    page.get_by_role("button", name="開練").click()
    page.wait_for_timeout(600)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(600)
    page.locator("button").filter(has_text="深蹲").first.click()
    page.wait_for_timeout(600)


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f73_e2e_{port}.db"
    release = REPO / f"liftlog_f73_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        source_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            start_free_workout(page)
            page.get_by_role("button", name="✓ 完成這組").click()
            page.wait_for_timeout(900)

            stop_btn = page.locator(".rest-controls .stop-rest")
            check(stop_btn.count() == 1, "① 停止鈕存在")
            cls = stop_btn.get_attribute("class") or ""
            check("alarming" not in cls, f"③ 倒數還沒歸零時不變色（{cls}）")

            # 把休息起點往回撥，讓它立刻進入超時——等 60 秒只是浪費驗收時間
            page.evaluate(
                "async () => {"
                "  const s = await import('/js/state.js');"
                "  s.state.restResumedAt -= 61_000;"
                "  s.state.restAccumulatedMs += 0;"
                "}"
            )
            page.wait_for_timeout(1600)  # 讓 ticker 跑一輪
            cls = page.locator(".rest-controls .stop-rest").get_attribute("class") or ""
            check("alarming" in cls and "btn-danger" in cls,
                  f"① 響著時停止鈕轉警示色（{cls}）")

            # ③ 暫停中不算響著
            page.get_by_role("button", name="⏸ 暫停").click()
            page.wait_for_timeout(600)
            cls = page.locator(".rest-controls .stop-rest").get_attribute("class") or ""
            check("alarming" not in cls, f"③ 暫停中不變色（{cls}）")

            # ⑤ 停止之後回到就緒態（F72 行為未被破壞）
            page.get_by_role("button", name="⏹ 停止").click()
            page.wait_for_timeout(600)
            check(page.get_by_role("button", name="✓ 完成這組").count() == 1,
                  "⑤ 停止後回到就緒態（F71／F72 行為不變）")
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
