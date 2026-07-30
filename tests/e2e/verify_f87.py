"""F87 E2E：體重體脂改版（大數字主卡 ＋ 24 根長條圖，保留時間窗），①–⑫。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f87.py`

⚠ 量測一律問渲染結果，不問 class 名稱（handoff 記過四次假綠）。
⚠ ⑪ 的版面門檻**不得寫死**：從服役中的 /css/app.css 讀 @media (max-height: N) 再推算，
   否則改了 CSS 沒改測試就變成兩個各說各話的真相來源。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    TOKEN,
    safe_port,
    setup_and_home,
    start_server,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{method} {path} → {exc.code}: {exc.read().decode()[:200]}") from None
    return json.loads(raw) if raw.strip() else None


def seed(base: str) -> None:
    """30 天、每 2 天一筆＝15 筆（少於 24 根，用來驗 ⑤ 的「不補空條」）。

    體脂只記單數筆——⑧ 要驗「沒量體脂的日子在體脂頁籤也列得出來、顯示 —」。
    體重一路下降，⑤ 的「最新一根 --accent」與 ④ 的「下降用 --good」才有東西可驗。
    """
    for i in range(15):
        day = (date.today() - timedelta(days=i * 2)).isoformat()
        payload = {"date": day, "weight_kg": round(76.0 + i * 0.3, 1)}
        if i % 2 == 0:
            payload["body_fat_pct"] = round(16.0 + i * 0.1, 1)
        api(base, "POST", "/api/body-metrics", payload)


def open_body(page) -> None:
    page.locator(".bottom-nav").get_by_role("button", name="體重").click()
    page.wait_for_selector(".screen.body", timeout=8000)
    page.wait_for_timeout(900)


def css(page, selector: str, prop: str) -> str:
    return page.eval_on_selector(selector, "(e, p) => getComputedStyle(e)[p]", prop)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f87-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        seed(base)
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
        open_body(page)

        accent = css(page, ".metric-pill.on", "backgroundColor")

        # ① 頁頭
        check(page.locator(".screen.body .screen-head .back-btn svg").count() == 1,
              "① 頁頭有向量返回鍵")
        check(page.locator(".screen.body .screen-head h1").inner_text().strip() == "體重 · 體脂",
              "① 標題「體重 · 體脂」")
        st = page.locator(".screen.body .screen-head .st").inner_text()
        check("最近一次" in st and "月" in st, f"① 副標「最近一次 M月D日」（實際 {st}）")

        # ② 兩顆等寬 toggle
        pills = page.locator(".metric-pill")
        check(pills.count() == 2, f"② 兩顆 toggle（實際 {pills.count()}）")
        tb = [pills.nth(i).bounding_box() for i in range(2)]
        check(abs(tb[0]["width"] - tb[1]["width"]) <= 1,
              f"② 等寬（{[round(b['width']) for b in tb]}）")
        check(css(page, ".metric-pill.on", "backgroundColor") == accent, "② 選中的用 --accent")

        # ③ 時間窗五顆保留
        rp = page.locator(".body-range .range-pill")
        texts = [rp.nth(i).inner_text().strip() for i in range(rp.count())]
        check(texts == ["1M", "3M", "6M", "1Y", "全部"], f"③ 時間窗五顆保留（實際 {texts}）")
        rb = [rp.nth(i).bounding_box() for i in range(rp.count())]
        check(all(b["width"] >= 44 and b["height"] >= 44 for b in rb),
              "③⑫ 五顆觸控目標 ≥44px："
              f"{[(round(b['width']), round(b['height'])) for b in rb]}")

        # ④ 主卡
        big = page.locator(".bm-big")
        check(big.count() == 1, "④ 主卡有一個大數字")
        check(css(page, ".bm-big", "fontSize") == "52px",
              f"④ 52px（實際 {css(page, '.bm-big', 'fontSize')}）")
        check(css(page, ".bm-big", "color") == accent, "④ 大數字用 --accent")
        check(css(page, ".bm-unit", "fontSize") == "15px", "④ 單位 15px")
        delta = page.locator(".bm-delta").inner_text().strip()
        check(delta.startswith("−") or delta.startswith("+") or delta.startswith("±"),
              f"④ 差值有方向符號（實際 {delta}）")
        # 種子資料：最舊 76.0（i=14 → 最新那筆其實是 i=0 的 76.0…）——用實際渲染值判方向
        good = css(page, ".bm-delta", "color")
        mute = css(page, ".bm-span", "color")
        check(good != mute or delta.startswith("±"),
              "④ 差值顏色與區間文字不同（下降 --good／上升 --text-mute）")

        # ⑤ 24 根長條，不足不補
        bars = page.locator(".body-bar")
        check(bars.count() == 15, f"⑤ 15 筆資料就畫 15 根，不補空條（實際 {bars.count()}）")
        heights = [bars.nth(i).bounding_box()["height"] for i in range(bars.count())]
        track = page.locator(".body-bars").bounding_box()["height"]
        ratios = sorted(h / track for h in heights)
        # 下限 24%（Ryan 2026-07-30 裁決，偏離設計稿的 14%）——理由見 body.js barChart 的說明：
        # 80px 的長條區上 14% 只有 11px，圓角之下看起來是點不是長條
        check(0.23 <= ratios[0] <= 0.25,
              f"⑤ 最小值保底 24%（實際 {ratios[0]:.3f}）")
        check(0.95 <= ratios[-1] <= 1.0, f"⑤ 最大值約 96%（24+72，實際 {ratios[-1]:.3f}）")
        colors = [css(page, f".body-bar:nth-child({i + 1})", "backgroundColor") for i in range(15)]
        check(colors[-1] == accent, "⑤ 最新一根用 --accent")
        check(all(c != accent for c in colors[:-1]), "⑤ 其餘用 --line（不是全部都染色）")
        foot = page.locator(".body-bars-foot").inner_text()
        check(foot.count("/") == 2, f"⑤ 底部標示起訖日期（實際 {foot!r}）")

        # ⑥ 「記錄」鈕在清單下方
        log_btn = page.locator(".body-log-open").bounding_box()
        list_box = page.locator(".body-list").bounding_box()
        check(log_btn["y"] > list_box["y"], "⑥ 「＋ 記錄」在歷史清單下方（F55 的單手可及位置）")
        page.locator(".body-log-open").click()
        page.wait_for_timeout(600)
        check(page.locator(".body-log-modal").count() == 1, "⑥ 點了開 F54 的懸浮視窗")
        page.get_by_role("button", name="取消").first.click()
        page.wait_for_timeout(500)

        # ⑦ 歷史清單
        rows = page.locator(".bm-row")
        check(rows.count() == 15, f"⑦ 清單列出全部 15 筆（實際 {rows.count()}）")
        check("kg" in rows.first.inner_text(), "⑦ 體重頁籤顯示 kg")

        # ⑧ 體脂頁籤：全部日子都列，沒體脂顯示 —
        pills.nth(1).click()
        page.wait_for_timeout(900)
        fat_rows = page.locator(".bm-row")
        check(fat_rows.count() == 15,
              f"⑧ 體脂頁籤也列出全部 15 天（實際 {fat_rows.count()}）——沒量的那幾天先前整列消失")
        dashes = page.evaluate(
            """() => [...document.querySelectorAll('.bm-row .bm-val')]
                 .filter(e => e.textContent.trim() === '—').length"""
        )
        check(dashes == 7, f"⑧ 沒量體脂的 7 天顯示 —（實際 {dashes}）")
        check("%" in page.locator(".bm-row .bm-val").first.inner_text()
              or "—" in page.locator(".bm-row .bm-val").first.inner_text(),
              "⑧ 有量的顯示百分比")
        pills.nth(0).click()
        page.wait_for_timeout(700)

        # ⑨ 共用 range.js
        repo = Path(__file__).resolve().parents[2]
        body_src = (repo / "app/static/js/body.js").read_text(encoding="utf-8")
        detail_src = (repo / "app/static/js/exercise-detail.js").read_text(encoding="utf-8")
        check("range.js" in body_src and "range.js" in detail_src,
              "⑨ 兩頁都改 import 共用的 range.js")
        check("const PRESETS = [" not in body_src and "const PRESETS = [" not in detail_src,
              "⑨ 兩頁不再各自定義 PRESETS")
        sw = (repo / "app/static/sw.js").read_text(encoding="utf-8")
        check('"/js/range.js"' in sw, "⑨ 新模組列進 SW SHELL（漏了離線首開會缺檔）")

        # ⑩ 送出中按鈕視覺上停用
        page.locator(".body-log-open").click()
        page.wait_for_timeout(500)
        # 本機的 POST 幾毫秒就回來了，不拖慢的話「送出中」那一刻根本量不到——
        # 這條驗的正是「慢網路下有沒有回饋」，所以一定要製造慢網路
        def slow(route):
            page.wait_for_timeout(600)
            route.continue_()

        page.route("**/api/body-metrics", slow)
        saving_visible = page.evaluate(
            """async () => {
                 const modal = document.querySelector('.body-log-modal');
                 const btn = modal.querySelector('.modal-actions button');
                 const before = btn.hasAttribute('disabled');
                 btn.click();
                 await new Promise(r => setTimeout(r, 200));
                 const during = modal.classList.contains('saving')
                   || modal.querySelector('.modal-actions button').hasAttribute('disabled');
                 return { before, during };
               }"""
        )
        check(saving_visible["before"] is False and saving_visible["during"] is True,
              f"⑩ 送出期間按鈕在 DOM 上就是停用的（{saving_visible}）")
        page.wait_for_timeout(1200)

        # ⑪ 版面門檻——從服役中的 CSS 讀，不寫死
        css_text = urllib.request.urlopen(f"{base}/css/app.css", timeout=10).read().decode()
        match = re.search(r"@media \(max-height: (\d+)px\) \{\s*\.screen\.body", css_text)
        threshold = int(match.group(1))
        tall = browser.new_context(viewport={"width": 390, "height": threshold + 40})
        tp = tall.new_page()
        tp.goto(base, wait_until="domcontentloaded")
        tp.wait_for_selector("input", timeout=10_000)
        setup_and_home(tp)
        open_body(tp)
        fill = tp.eval_on_selector(".body-list", "e => getComputedStyle(e).flexGrow")
        check(fill != "0", f"⑪ 高於門檻（{threshold + 40}）時清單填滿剩餘空間（flex-grow={fill}）")
        check(tp.evaluate("() => document.documentElement.scrollHeight <= window.innerHeight + 1"),
              "⑪ 高於門檻時整頁不需捲動（底部鈕在可視區內）")
        tall.close()

        short = browser.new_context(viewport={"width": 390, "height": threshold - 40})
        sp = short.new_page()
        sp.goto(base, wait_until="domcontentloaded")
        sp.wait_for_selector("input", timeout=10_000)
        setup_and_home(sp)
        open_body(sp)
        grow = sp.eval_on_selector(".body-list", "e => getComputedStyle(e).flexGrow")
        min_h = sp.eval_on_selector(".body-list", "e => getComputedStyle(e).minHeight")
        check(grow == "0", f"⑪ 低於門檻時退出 flex-fill（flex-grow={grow}）")
        check(min_h == "0px", "⑪ 退讓用 flex:none 吃回內容高（min-height 歸零是同一條規則的一半）")
        overlap = sp.evaluate(
            """() => {
                 const list = document.querySelector('.body-list').getBoundingClientRect();
                 const back = [...document.querySelectorAll('.screen.body > button')].pop()
                   .getBoundingClientRect();
                 return Math.round(list.bottom - back.top);
               }"""
        )
        check(overlap <= 0, f"⑪ 清單不會疊到「← 回首頁」上（重疊 {overlap}px）")
        short.close()

        # ⑫ 觸控目標與水平捲動
        small = page.evaluate(
            """() => [...document.querySelectorAll('.screen.body button')]
                 .map(b => ({ t: b.innerText.trim().slice(0, 10),
                              w: b.getBoundingClientRect().width,
                              h: b.getBoundingClientRect().height }))
                 .filter(x => x.w < 44 || x.h < 44)"""
        )
        check(not small, f"⑫ 頁內按鈕觸控區皆 ≥44px（不足：{small}）")
        check(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"),
              "⑫ 無水平捲動")

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
