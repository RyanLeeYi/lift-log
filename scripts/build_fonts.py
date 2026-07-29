"""F79：把三套 OFL 字型做成內嵌用的 woff2。

為什麼留著這支腳本而不是只留產物：字型是二進位、進了 repo 就看不出「怎麼來的」。
下次要換字重、補字元、或升級上游版本時，照著跑一次就好，不必重新考古。

用法（需要網路，會下載上游原始 ttf）：
    uv run python scripts/build_fonts.py

產物寫進 app/static/fonts/，授權檔一併帶著（OFL 要求散布時附授權）。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "app/static/fonts"
GF = "https://github.com/google/fonts/raw/main"

# 拉丁子集的基礎範圍：基本拉丁、常見標點與符號區。
# ⚠ 只有範圍不夠——實際 UI 會用到範圍外的字（例如 placeholder 裡的 ⋯ U+22EF 落在數學運算子區，
# 第一版就漏了，Codex 驗收才抓到）。所以真正的子集 = 這些範圍 ∪ 原始碼裡實際出現的非中日韓字元。
LATIN_UNICODES = ",".join([
    "U+0020-007E",   # 基本拉丁
    "U+00A0-00FF",   # 重音字母與 ×、÷
    "U+2000-206F",   # 標點（含 · 與各式引號、破折號）
    "U+2070-209F",   # 上下標
    "U+20A0-20BF",   # 貨幣
    "U+2190-21FF",   # 箭頭（← → ↑ ↓）
    "U+2212",        # 真正的減號（步進器用）
    "U+25A0-25FF",   # 幾何圖形（◀ ▶）
])

# 掃描哪些檔案取「實際用到的字元」——前端會渲染的來源
SCAN_GLOBS = ("app/static/**/*.js", "app/static/**/*.html", "app/static/**/*.css")


def used_latin_chars(repo: Path | None = None) -> set[str]:
    """回傳前端原始碼裡實際出現、且需要由拉丁字型負責的字元。

    中日韓字元交給 Noto Sans TC（全字集），這裡只留下拉丁字型該畫的部分。
    verify_f79.py 也用這個函式，確保「產生」與「驗證」看的是同一份清單。
    """
    root = repo or REPO
    chars: set[str] = set()
    for pattern in SCAN_GLOBS:
        for path in root.glob(pattern):
            for ch in path.read_text(encoding="utf-8", errors="ignore"):
                if ch.isspace() or ord(ch) < 0x20:
                    continue
                # 中日韓統一表意文字與全形標點交給 TC
                if "　" <= ch <= "〿" or "一" <= ch <= "鿿":
                    continue
                if "＀" <= ch <= "￯":
                    continue
                chars.add(ch)
    return chars

SOURCES = [
    # (上游路徑, 暫存檔名, 產物檔名, 是否只取拉丁子集)
    (f"{GF}/ofl/archivo/Archivo%5Bwdth,wght%5D.ttf", "archivo-var.ttf", "archivo-var.woff2", True),
    (f"{GF}/ofl/ibmplexmono/IBMPlexMono-Regular.ttf", "plex-400.ttf", "plexmono-400.woff2", True),
    (f"{GF}/ofl/ibmplexmono/IBMPlexMono-Medium.ttf", "plex-500.ttf", "plexmono-500.woff2", True),
    (f"{GF}/ofl/ibmplexmono/IBMPlexMono-SemiBold.ttf", "plex-600.ttf", "plexmono-600.woff2", True),
    # 中文不子集：自訂動作名與備註是自由輸入，缺字會在同一行裡混兩種字型
    # （Ryan 2026-07-29 決定全字集）
    (
        f"{GF}/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf",
        "notosanstc-var.ttf",
        "notosanstc-var.woff2",
        False,
    ),
]

LICENSES = [
    (f"{GF}/ofl/archivo/OFL.txt", "OFL-Archivo.txt"),
    (f"{GF}/ofl/ibmplexmono/OFL.txt", "OFL-IBMPlexMono.txt"),
    (f"{GF}/ofl/notosanstc/OFL.txt", "OFL-NotoSansTC.txt"),
]


def fetch(url: str, dest: Path) -> None:
    print(f"  下載 {dest.name}")
    with urllib.request.urlopen(url) as resp, dest.open("wb") as fh:
        fh.write(resp.read())


def subset(src: Path, dest: Path, latin_only: bool, extra_text: Path | None = None) -> None:
    args = [
        sys.executable, "-m", "fontTools.subset", str(src),
        "--flavor=woff2",
        "--layout-features=*",
        f"--output-file={dest}",
    ]
    if latin_only:
        args.append(f"--unicodes={LATIN_UNICODES}")
        if extra_text:
            args.append(f"--text-file={extra_text}")
    else:
        args.append("--unicodes=*")
    subprocess.run(args, check=True, capture_output=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        used = tmpdir / "used-chars.txt"
        chars = used_latin_chars()
        used.write_text("".join(sorted(chars)), encoding="utf-8")
        print(f"  前端原始碼實際用到的非中文字元：{len(chars)} 個（一併納入子集）")
        for url, raw_name, out_name, latin_only in SOURCES:
            raw = tmpdir / raw_name
            fetch(url, raw)
            dest = OUT / out_name
            subset(raw, dest, latin_only, extra_text=used)
            print(f"  → {out_name}  {dest.stat().st_size / 1024:,.0f} KB")
        for url, name in LICENSES:
            fetch(url, OUT / name)
    total = sum(f.stat().st_size for f in OUT.glob("*.woff2"))
    print(f"字型合計 {total / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
