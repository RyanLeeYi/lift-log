"""F79 驗證：Archivo／IBM Plex Mono／Noto Sans TC 內嵌。

跑法：`uv run python tests/e2e/verify_f79.py`

重點不是「CSS 有沒有寫 @font-face」，而是**瀏覽器真的用了這些字**——
所以除了靜態檢查，還用 document.fonts.check() 與實際量測字寬來確認字型有載入並生效
（掉回系統字時字寬會不同，這是唯一騙不了的證據）。
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告有全形字，Windows console 預設 CP950 會炸（F78 驗收踩過）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, free_port, setup_and_home, start_server  # noqa: E402

results: list[tuple[bool, str]] = []

FONT_DIR = REPO / "app/static/fonts"
EXPECTED = {
    "archivo-var.woff2": (50_000, 200_000),
    # 全字集（Ryan 2026-07-29 選定，不子集）
    "notosanstc-var.woff2": (3_000_000, 8_000_000),
    "plexmono-400.woff2": (8_000, 60_000),
    "plexmono-500.woff2": (8_000, 60_000),
    "plexmono-600.woff2": (8_000, 60_000),
}


def is_emoji(ch: str) -> bool:
    """彩色 emoji 一律由系統 emoji 字型畫——任何文字字型都不會有這些字符。"""
    cp = ord(ch)
    return (
        0x1F300 <= cp <= 0x1FAFF   # 各式 emoji 區塊
        or 0x2600 <= cp <= 0x27BF  # 雜項符號與裝飾符號（⚠ ✓ ✕ ✎ 等）
        or 0x2B00 <= cp <= 0x2BFF
        or cp in (0x23F3, 0x23F9)  # ⏳ ⏹
    )


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def static_checks() -> None:
    css = (REPO / "app/static/css/app.css").read_text(encoding="utf-8")
    faces = re.findall(r"@font-face\s*\{(.*?)\}", css, re.S)
    check(len(faces) == 5, f"① 五個 @font-face（Archivo／TC／Plex 三字重），實際 {len(faces)}")

    # ① 不得有任何外部來源——CDN 掛掉或離線時整套設計就垮了
    urls = re.findall(r"url\((['\"]?)([^'\")]+)\1\)", css)
    external = [u for u in urls if u[1].startswith("http")]
    check(not external, f"① @font-face 沒有任何外部網址（發現：{external}）")

    for name, (lo, hi) in EXPECTED.items():
        f = FONT_DIR / name
        size = f.stat().st_size if f.is_file() else 0
        check(lo <= size <= hi, f"① {name} 存在且大小合理（{size:,} bytes）")

    for face in faces:
        check("font-display: swap" in face,
              "⑥ 每個 @font-face 都有 font-display: swap（不出現隱形文字）")

    # ② 字型堆疊以內嵌字型為首，系統字只當 fallback
    check(re.search(r"--sans:\s*Archivo,\s*\"Noto Sans TC\"", css) is not None,
          "② --sans 以 Archivo → Noto Sans TC 開頭")
    check(re.search(r"--mono:\s*\"IBM Plex Mono\",\s*\"Noto Sans TC\"", css) is not None,
          "② --mono 以 IBM Plex Mono → Noto Sans TC 開頭（mono 情境的中文才不會掉字）")

    # ③ 離線：字型要進 SW 快取清單
    sw = (REPO / "app/static/sw.js").read_text(encoding="utf-8")
    for name in EXPECTED:
        check(f"/fonts/{name}" in sw, f"③ {name} 已列進 sw.js 的 SHELL")

    # ④ OFL 要求散布時附授權（repo 已公開，這條不是形式）
    for name in ("OFL-Archivo.txt", "OFL-IBMPlexMono.txt", "OFL-NotoSansTC.txt"):
        f = FONT_DIR / name
        check(f.is_file() and f.stat().st_size > 1000, f"④ 授權檔 {name} 一併附上")

    # ⑤ 涵蓋率直接查字型的 cmap——比讀 build 腳本的參數可靠（參數對不代表產物對）。
    #   而且要**掃過原始碼實際用到的每個字元**，不是抽查幾個符號：
    #   第一版抽查 −／×／· 全過，卻漏了 placeholder 裡的 ⋯（U+22EF，落在數學運算子區），
    #   Codex 2026-07-29 驗收才抓出來。抽查會給假綠，全掃不會。
    from fontTools.ttLib import TTFont

    sys.path.insert(0, str(REPO / "scripts"))
    from build_fonts import used_latin_chars  # noqa: PLC0415

    used = used_latin_chars(REPO)
    with TTFont(FONT_DIR / "archivo-var.woff2") as font:
        latin_cmap = font.getBestCmap()
    with TTFont(FONT_DIR / "notosanstc-var.woff2") as font:
        tc_cmap_all = font.getBestCmap()

    # 拉丁字型該負責的部分（字母、數字、標點、−／×／·）一個都不能被子集砍掉。
    # 三套字型都沒有的字元不會變豆腐字——瀏覽器的 fallback 會一路走到系統字，
    # 跟換皮前的行為相同；那些只記錄、不擋（見下方 NOTE）。
    for name in ("archivo-var.woff2", "plexmono-400.woff2", "plexmono-500.woff2",
                 "plexmono-600.woff2"):
        with TTFont(FONT_DIR / name) as font:
            cmap = font.getBestCmap()
        dropped = sorted(ch for ch in used if ch.isascii() and ord(ch) not in cmap)
        check(not dropped, f"⑤ {name} 涵蓋所有 ASCII 字元（缺：{''.join(dropped)}）")

    fallback = sorted(
        ch for ch in used
        if ord(ch) not in latin_cmap and ord(ch) not in tc_cmap_all and not is_emoji(ch)
    )
    emoji = sorted(ch for ch in used if is_emoji(ch))
    print(f"NOTE  走系統字型的字元：{''.join(fallback) or '無'}；"
          f"走系統 emoji 的：{''.join(emoji) or '無'}")
    # ⋯ 之類的中式標點由內嵌的 Noto Sans TC 負責（Archivo 本來就沒有這個字符）
    for ch, why in ((0x22EF, "刪節號 ⋯"), (0x25B6, "實心三角 ▶")):
        check(ch in tc_cmap_all or ch in latin_cmap, f"⑤ {why} 由內嵌字型畫（不掉回系統字）")
    # acceptance ⑤ 點名的符號：這些 Archivo 有，子集不可漏
    symbols = ((0x2212, "減號 −"), (0x2192, "箭頭 →"), (0x00D7, "乘號 ×"), (0x00B7, "間隔號 ·"))
    for ch, why in symbols:
        check(ch in latin_cmap, f"⑤ Archivo 子集涵蓋 {why}")

    with TTFont(FONT_DIR / "notosanstc-var.woff2") as font:
        tc_cmap = font.getBestCmap()
    # 全字集：常用字與罕用字都要在（子集化過就會少）
    for ch in "槓鈴臥推深蹲硬舉鑫鱻饕餮":
        check(ord(ch) in tc_cmap, f"⑤ Noto Sans TC 為全字集，含 '{ch}'")
    # 上游 NotoSansTC[wght].ttf 本身就是 20,745 字（Noto Sans TC 的完整涵蓋範圍），
    # 這裡的門檻是「有沒有被子集化砍過」，不是猜一個更大的數字。
    check(len(tc_cmap) >= 20_000, f"⑤ Noto Sans TC 字符數 {len(tc_cmap):,}（未被子集化砍過）")


def rendered_checks(page, base: str) -> None:
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    page.evaluate("() => document.fonts.ready")
    page.wait_for_timeout(600)

    loaded = page.evaluate("() => [...document.fonts].map(f => f.family + '|' + f.status)")
    for family in ("Archivo", "Noto Sans TC", "IBM Plex Mono"):
        entries = [e for e in loaded if e.startswith(family + "|")]
        check(any(e.endswith("loaded") for e in entries), f"① {family} 實際載入（{entries}）")

    # fonts.check() 對「宣告了但還沒被用到」的字重會回 false（狀態 unloaded），
    # 所以先 load 再 check——這裡要驗的是宣告正確、字重取得到，不是它現在有沒有被畫在畫面上。
    for spec, label in (
        ("700 17px Archivo", "Archivo 700（可變字型的字重範圍宣告正確）"),
        ("500 14px \"IBM Plex Mono\"", "IBM Plex Mono 500"),
        ("600 14px \"IBM Plex Mono\"", "IBM Plex Mono 600"),
    ):
        ok = page.evaluate(
            "async (spec) => {"
            "  await document.fonts.load(spec);"
            "  return document.fonts.check(spec);"
            "}",
            spec,
        )
        check(ok, f"② 瀏覽器取得 {label}")

    # 真正用上了沒：拿同一段文字在「有／沒有 Archivo」下量寬度，掉回系統字寬度會不同
    widths = page.evaluate(
        "() => {"
        "  const measure = (family) => {"
        "    const el = document.createElement('span');"
        "    el.textContent = 'Bench Press 60.0 kg x 8';"
        "    el.style.cssText = 'position:absolute;visibility:hidden;font-size:17px;'"
        "                     + 'font-family:' + family;"
        "    document.body.append(el);"
        "    const w = el.getBoundingClientRect().width;"
        "    el.remove();"
        "    return w;"
        "  };"
        "  return { archivo: measure('Archivo'), fallback: measure('sans-serif'),"
        "           plex: measure('\"IBM Plex Mono\"'), mono: measure('monospace') };"
        "}"
    )
    check(abs(widths["archivo"] - widths["fallback"]) > 1,
          "① Archivo 真的生效（與系統 sans 字寬不同："
          f"{widths['archivo']:.1f} vs {widths['fallback']:.1f}）")
    check(abs(widths["plex"] - widths["mono"]) > 1,
          f"① Plex Mono 真的生效（{widths['plex']:.1f} vs {widths['mono']:.1f}）")

    # 中文不能用「量字寬」驗——CJK 一律全形等寬，換字型寬度不變（第一版測法就是這樣自欺）。
    # 改問瀏覽器：這串字（含罕用字）能不能只靠 Noto Sans TC 畫出來。
    ok = page.evaluate(
        "async () => {"
        "  await document.fonts.load('400 17px \"Noto Sans TC\"', '槓鈴臥推鑫鱻');"
        "  return document.fonts.check('400 17px \"Noto Sans TC\"', '槓鈴臥推鑫鱻');"
        "}"
    )
    check(ok, "① 中文（含罕用字 鑫鱻）能由 Noto Sans TC 畫出")

    body_font = page.evaluate("() => getComputedStyle(document.body).fontFamily")
    check(body_font.startswith("Archivo"), f"② body 的 font-family 以 Archivo 開頭（{body_font}）")


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f79_{port}.db"
    release = REPO / f"liftlog_f79_release_{port}"
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
