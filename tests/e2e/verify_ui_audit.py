"""F74–F77 驗證：ui-ux-pro-max 審視結果的四項修正。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_ui_audit.py`

一支涵蓋四條 feature，因為它們共用同一組量測手段（對比公式、boundingBox、原始碼掃描），
拆四支只會把同樣的 Playwright 啟動成本付四次。

⚠ 界線：F74 的浮動視窗尺寸是原生 view，只能靠原始碼常數與模擬器截圖驗（acceptance ⑥）；
這裡驗的是常數與版面參數，實際觸控感受在裝置上。
"""

from __future__ import annotations

import re
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


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    parts = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def token(css: str, name: str) -> str:
    m = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", css)
    return m.group(1) if m else ""


def f75_colours() -> None:
    """F75 的門檻在 F78 換色後只剩這幾條仍然成立。

    ⚠ F78 起，`--text-mute` / `--text-faint` / `--over` / `--line` 由 Ryan（2026-07-29）明確授權
    照抄陶土夜色的設計值，四者的 4.5:1（`--line` 3:1）門檻**有意識地放行**——不是退化沒被發現。
    這四條的實測值改由 verify_f78.py 記錄下來（只印不擋），避免留一條永遠紅的斷言。
    """
    css = (REPO / "app/static/css/app.css").read_text(encoding="utf-8")
    bg = token(css, "bg")
    pairs = [("text", 4.5), ("text-mid", 4.5), ("text-dim", 4.5), ("accent", 4.5), ("good", 4.5)]
    for name, need in pairs:
        value = token(css, name)
        ratio = contrast(value, bg) if value else 0
        check(ratio >= need, f"F75 {name}={value} 對比 {ratio}（需 ≥{need}）")
    # 沙金按鈕上的字：主要動作用的就是它
    check(contrast(token(css, "on-accent"), token(css, "accent")) >= 4.5,
          "F75 --on-accent 在 --accent 上 ≥4.5")


def f76_icons(page, base: str) -> None:
    app_js = (REPO / "app/static/js/app.js").read_text(encoding="utf-8")
    code = "\n".join(
        ln for ln in app_js.splitlines() if not ln.lstrip().startswith("//")
    )
    # ①：結構性 emoji 不該再出現在會被渲染的字串裡（註解裡談論它們沒關係）
    structural = ["📋", "📅", "📈", "⚖", "🔔", "🪟", "🏋", "⏱", "⏸", "⏹", "✎", "🗑", "⏳"]
    leftover = [e for e in structural if e in code]
    check(not leftover, f"F76 ① 程式碼裡沒有殘留的結構性 emoji（{leftover}）")

    sw = (REPO / "app/static/sw.js").read_text(encoding="utf-8")
    check("/js/icons.js" in sw, "F76 ② 圖示模組進了 SW 離線清單（app 版離線也要畫得出來）")

    icons_js = (REPO / "app/static/js/icons.js").read_text(encoding="utf-8")
    check("http" not in icons_js.replace("http://www.w3.org/2000/svg", ""),
          "F76 ② 圖示不依賴任何外部網址（除 SVG namespace）")
    check('stroke", "currentColor"' in icons_js.replace("'", '"'),
          "F76 ④ 顏色走 currentColor（深色主題與各狀態自動正確）")
    check(icons_js.count('stroke-width", "2"') == 1, "F76 ③ 線寬統一（單一出處）")

    drawable = REPO / "android/app/src/main/res/drawable"
    for name in ("ic_rest_pause", "ic_rest_play", "ic_rest_stop", "ic_rest_close"):
        check((drawable / f"{name}.xml").is_file(), f"F76 ⑤ 原生向量圖示 {name} 存在")
    overlay = (REPO / "android/app/src/main/java/com/ryanleeyi/liftlog/RestOverlay.java").read_text(
        encoding="utf-8")
    check("setImageResource" in overlay and "setImageTintList" in overlay,
          "F76 ⑤ 浮動視窗改用 vector drawable + tint（emoji 吃不到 tint）")

    # 實際渲染出來的是 <svg> 而不是文字
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    svg_count = page.locator(".home-actions svg.icon, section svg.icon").count()
    check(svg_count >= 4, f"F76 首頁入口渲染成向量圖示（{svg_count} 個 svg）")


def f77_touch_targets(page, base: str) -> None:
    """④：量真實的 boundingBox，不是讀 CSS 推論。"""
    page.get_by_role("button", name="開練").click()
    page.wait_for_timeout(600)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(600)
    page.locator("button").filter(has_text="深蹲").first.click()
    page.wait_for_timeout(600)
    page.get_by_role("button", name="完成這組").click()
    page.wait_for_timeout(900)

    small: list[str] = []
    for i in range(page.locator("button").count()):
        b = page.locator("button").nth(i)
        if not b.is_visible():
            continue
        box = b.bounding_box()
        if not box:
            continue
        if box["height"] < 44 or box["width"] < 44:
            label = (b.inner_text() or b.get_attribute("aria-label") or "?").strip()[:14]
            small.append(f"{label}({int(box['width'])}x{int(box['height'])})")
    check(not small, f"F77 ① 計時頁所有按鈕觸控區 ≥44px（不足：{small}）")

    # ②③：編輯與刪除相鄰，量它們的間距
    icons = page.locator(".done-row .icon-btn")
    if icons.count() >= 2:
        a, b = icons.nth(0).bounding_box(), icons.nth(1).bounding_box()
        gap = b["x"] - (a["x"] + a["width"]) if a and b else 0
        check(gap >= 8, f"F77 ③ 編輯與刪除之間 ≥8px（實測 {round(gap, 1)}px）")
        check(a and a["height"] >= 44, f"F77 ② 編輯鈕 ≥44px（{int(a['height']) if a else 0}）")

    check(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"),
          "F77 ④ 加大後仍無水平捲動")


def f74_overlay_constants() -> None:
    overlay = (REPO / "android/app/src/main/java/com/ryanleeyi/liftlog/RestOverlay.java").read_text(
        encoding="utf-8")
    check("TOUCH_TARGET_DP = 48" in overlay, "F74 ① 浮動視窗按鈕觸控區 48dp")
    check("BUTTON_GAP_DP = 8" in overlay, "F74 ② 按鈕間距 8dp")
    check("setAlpha(0.5f)" in overlay and "setAlpha(1f)" in overlay,
          "F74 ④ 按下有回饋且只改透明度（不動版面）")


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_uiaudit_{port}.db"
    release = REPO / f"liftlog_uiaudit_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        f75_colours()
        f74_overlay_constants()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            f76_icons(page, base)
            f77_touch_targets(page, base)
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
