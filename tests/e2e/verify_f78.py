"""F78 驗證：陶土夜色設計 token 與基礎元件。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f78.py`

驗的是「換皮的地基」：token 值必須與 handoff 逐字相同、舊 token 與硬編色不得殘留、
圓角規則成立、觸控目標不退步。實際渲染的圓角與尺寸用 Playwright 量，不靠讀 CSS 推論——
CSS 寫了不代表算得出來（F77 就是量了才發現三處不足）。
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

# 報告裡有 ≥、①、⑦ 這些字，Windows console 預設 CP950 編不出來會直接 UnicodeEncodeError exit 1
# ——驗收者照文件跑就踩到（Codex 2026-07-29 實測）。這裡自己把 stdout 轉成 UTF-8，不再依賴環境變數。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, free_port, setup_and_home, start_server  # noqa: E402

results: list[tuple[bool, str]] = []

CSS = REPO / "app/static/css/app.css"

# handoff README「Design Tokens」那段的實測值，逐字對照
HANDOFF_TOKENS = {
    "bg": "#221E1A",
    "card": "#2E2822",
    "card-hi": "#3B342C",
    "line": "#544A3D",
    "text": "#F0E9DF",
    "text-mid": "#C9BFB1",
    "text-dim": "#A99C8C",
    "text-mute": "#8F8375",
    "text-faint": "#6E6357",
    "accent": "#D9B25F",
    "on-accent": "#241E14",
    "over": "#C96A4E",
    "good": "#8FA37A",
}

# Ryan 2026-07-29 授權照抄、明知對比低於 F75 門檻的四個 token（只記錄不擋）
WAIVED = ("text-mute", "text-faint", "over", "line")


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


def static_checks() -> str:
    css = CSS.read_text(encoding="utf-8")

    # ① token 值逐字照抄
    for name, want in HANDOFF_TOKENS.items():
        got = token(css, name)
        check(got.upper() == want, f"① --{name} = {want}（實際 {got or '未定義'}）")

    # ② 舊 token 不得殘留（註解裡也不留，避免下一個人照著抄）
    for old in ("--led", "--led-dim", "--card-edge", "--danger"):
        check(not re.search(rf"{re.escape(old)}\b", css), f"② 舊 token {old} 已完全移除")

    # ③ 沒有散落的硬編色：所有字面色只能出現在 :root 裡。
    #   rgb()/rgba() 也算——光暈與遮罩同樣是「換色時要找出來改」的東西（Codex P2）。
    root = css.split("}", 1)[0]
    body = css[len(root):]
    strays = sorted(set(re.findall(r"#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)", body)))
    check(not strays, f"③ :root 之外沒有硬編色（殘留：{strays}）")

    # 死 token 也是債：定義了沒人用，下一個人會以為它生效
    # --good 是 acceptance ① 指定的 13 色之一，但它的唯一用途（體重下降／進步）在 F87 才做，
    # 提早塞去別處只會用錯語意——這一個明確例外，其餘一律要有人用。
    for name in re.findall(r"--([a-z0-9-]+):\s*(?:#|rgba?\(|[0-9])", root):
        if name.startswith("app-pad") or name == "good":
            continue
        check(f"var(--{name})" in body, f"③ --{name} 有實際被引用（不留死 token）")

    # ④ 圓角走 token（藥丸 99px、卡片 22/26、輸入 18、日曆格 10）
    check(token_px(css, "r-pill") == "99px", "④ --r-pill = 99px")
    check(token_px(css, "r-card") == "22px", "④ --r-card = 22px")
    check(token_px(css, "r-card-lg") == "26px", "④ --r-card-lg = 26px")
    check(token_px(css, "r-input") == "18px", "④ --r-input = 18px")
    check(token_px(css, "r-cell") == "10px", "④ --r-cell = 10px")
    check(".btn {" in css and "border-radius: var(--r-pill)" in css, "④ 按鈕吃藥丸 token")

    # ⑤ 卡片不靠外框：整份 CSS 只剩「刻意保留」的 1px 邊
    borders = re.findall(r"^\s*border: 1px solid var\(--[a-z-]+\);", body, re.M)
    check(len(borders) <= 1, f"⑤ 幾乎不用外框做分隔（殘留 {len(borders)} 條，僅允許錯誤橫幅）")
    check("--sans: Archivo" in css and '--mono: "IBM Plex Mono"' in css,
          "字型堆疊已指向 Archivo / IBM Plex Mono（字型檔本身是 F79）")

    # ⑥ 外觀入口三處同步換色
    check('content="#221E1A"' in (REPO / "app/static/index.html").read_text(encoding="utf-8"),
          "⑥ index.html theme-color = #221E1A")
    manifest = (REPO / "app/static/manifest.webmanifest").read_text(encoding="utf-8")
    check(manifest.count("#221E1A") == 2, "⑥ manifest 的 background_color 與 theme_color 都換了")
    icon = (REPO / "app/static/icon.svg").read_text(encoding="utf-8")
    check("#221E1A" in icon and "#D9B25F" in icon and "#F0E9DF" in icon,
          "⑥ icon.svg 改新色（底／槓片／握把）")

    # 對比：守得住的照守，被授權放行的四個只記錄
    bg = HANDOFF_TOKENS["bg"]
    for name in ("text", "text-mid", "text-dim", "accent", "good"):
        ratio = contrast(HANDOFF_TOKENS[name], bg)
        check(ratio >= 4.5, f"對比 --{name} vs --bg = {ratio}（需 ≥4.5）")
    for name in WAIVED:
        ratio = contrast(HANDOFF_TOKENS[name], HANDOFF_TOKENS["card"])
        print(f"NOTE  --{name} vs --card = {ratio}（Ryan 授權照抄設計值，不擋）")
    return css


def token_px(css: str, name: str) -> str:
    m = re.search(rf"--{name}:\s*([0-9]+px)", css)
    return m.group(1) if m else ""


def undersized(page, allow_narrow: set[str] | None = None) -> list[str]:
    """回傳畫面上觸控區不足 44px 的可見按鈕。

    `allow_narrow` 是「高度達標但寬度受同列顆數限制」的明確例外（時間窗 8 顆一列，
    寬度拉到 44 會換行並讓 /body 的高度門檻算式失準——理由寫在 app.css 的同一段註解）。
    """
    allow_narrow = allow_narrow or set()
    out: list[str] = []
    for i in range(page.locator("button").count()):
        b = page.locator("button").nth(i)
        if not b.is_visible():
            continue
        box = b.bounding_box()
        if not box:
            continue
        label = (b.inner_text() or b.get_attribute("aria-label") or "?").strip()[:14]
        too_short = box["height"] < 44
        too_narrow = box["width"] < 44 and label not in allow_narrow
        if too_short or too_narrow:
            out.append(f"{label}({int(box['width'])}x{int(box['height'])})")
    return out


def rendered_checks(page, base: str) -> None:
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)

    body_bg = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    check(body_bg == "rgb(34, 30, 26)", f"① 頁面底實際渲染為 #221E1A（{body_bg}）")

    start = page.get_by_role("button", name="開練")
    radius = start.evaluate("el => getComputedStyle(el).borderTopLeftRadius")
    check(radius == "99px", f"④ 主按鈕實際圓角 99px（{radius}）")
    colour = start.evaluate("el => getComputedStyle(el).backgroundColor")
    check(colour == "rgb(217, 178, 95)", f"① 主按鈕是沙金（{colour}）")
    border = start.evaluate("el => getComputedStyle(el).borderTopWidth")
    check(border == "0px", f"⑤ 按鈕不再有外框（{border}）")

    # ⑦ 觸控目標不退步——換皮最容易悄悄吃掉高度的就是外框那 2px。
    #   逐畫面量，不只量首頁：verify_ui_audit 只涵蓋計時頁，日曆／表現／體重／picker 的缺口
    #   因此一路假綠到 F78（Codex 2026-07-29 驗收抓到）。
    check(not undersized(page), f"⑦ 首頁觸控區全部 ≥44px（不足：{undersized(page)}）")
    for label, name in (("日曆", "日曆"), ("動作表現", "動作表現"), ("體重", "體重")):
        page.get_by_role("button", name=name).first.click()
        page.wait_for_timeout(800)
        small = undersized(page, allow_narrow={"1M", "3M", "6M", "9M", "1Y", "2Y", "3Y"})
        check(not small, f"⑦ {label}頁觸控區 ≥44px（不足：{small}）")
        check(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"),
              f"⑦ {label}頁無水平捲動")
        page.get_by_role("button", name="回首頁").first.click()
        page.wait_for_timeout(600)

    page.get_by_role("button", name="開練").click()
    page.wait_for_timeout(800)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(700)
    check(not undersized(page), f"⑦ 選動作頁觸控區 ≥44px（不足：{undersized(page)}）")
    check(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"),
          "⑦ 換色後仍無水平捲動")


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f78_{port}.db"
    release = REPO / f"liftlog_f78_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        static_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            rendered_checks(page, base)
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
