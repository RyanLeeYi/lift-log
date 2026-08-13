"""F53 體重頁 toggle 切換體重／體脂＋紀錄清單填滿剩餘空間 E2E。
用法：PYTHONUTF8=1 uv run python verify_f53_own.py
涵蓋 acceptance ①–⑩。
"""

import datetime
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from verify_f67 import (  # noqa: E402
    read_version,
    wait_home,
)

REPO = Path(__file__).resolve().parents[2]
TOKEN = "f53-own-token"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def api(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw.strip() else None


def wait_up(url, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def box_h(page, sel):
    b = page.locator(sel).first.bounding_box()
    return round(b["height"]) if b else None


def fully_visible(page, sel):
    b = page.locator(sel).first.bounding_box()
    if b is None:
        return False
    return b["y"] >= 0 and b["y"] + b["height"] <= page.viewport_size["height"] + 1


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f53_{port}.db"
    if tmpdb.exists():
        tmpdb.unlink()
    env = dict(os.environ, LIFTLOG_TOKEN=TOKEN, LIFTLOG_DB=str(tmpdb))
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app_factory",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    try:
        if not wait_up(base + "/"):
            print("SERVER FAILED")
            return 1

        # 10 天體重，其中只有 4 天有體脂（驗「有記的點才連線」與清單只列有體脂的日子）
        today = datetime.date.today()
        fat_days = set()
        all_days = set()
        for i in range(10, 0, -1):
            d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            payload = {"date": d, "weight_kg": 100.0 + i * 0.3}
            all_days.add(d)
            if i % 3 == 0:
                payload["body_fat_pct"] = 24.0 + i * 0.1
                fat_days.add(d)
            api(base, "POST", "/api/body-metrics", payload)

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            wait_home(page)

            # ⑩ 版本
            ver = read_version(page)  # F81 把版號搬進設定畫面
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            check(
                "⑩ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v54）",
                ver.startswith("v") and int(ver[1:]) >= 54 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)

            # ①⑤ 單卡＋toggle、預設體重
            cards = page.locator(".screen.body .body-card").count()
            on_label = page.locator(".metric-toggle .metric-pill.on").inner_text().strip()
            check(
                "①⑤ 圖表合成單卡＋toggle（體重／體脂），預設『體重』",
                page.locator(".metric-toggle .metric-pill").count() == 2
                and on_label == "體重"
                and cards == 2,  # 圖表卡＋紀錄卡
                f"tabs={page.locator('.metric-toggle .metric-pill').count()} on={on_label!r} cards={cards}",
            )

            # 記錄清單此時應列出全部 10 筆、單位 kg
            rows_w = page.locator(".bm-rows .bm-row").count()
            val_w = page.locator(".bm-rows .bm-row .bm-val").first.inner_text()
            latest_w = page.locator(".body-main-value").inner_text()
            check(
                "① 體重頁籤：清單列全部紀錄且顯示 kg、卡片最新值為 kg",
                rows_w == 10 and "kg" in val_w and "kg" in latest_w,
                f"rows={rows_w} val={val_w!r} latest={latest_w!r}",
            )

            # ⑥ 的目的是「切換不得清掉使用者輸入／不得破壞畫面狀態」。
            # F54 把輸入表單移進懸浮視窗（切 toggle 時表單不在畫面上），F58 又為了讓 chips 依當前 metric
            # 重畫而改走 rerender()——所以「節點不被替換」這個**手段**已不再適用（feature_list 有附註）。
            # 這裡改驗目的：切換後畫面該有的東西都在、且清單捲動位置由分頁籤記憶負責（見下方 P2-2 那條）。
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(500)
            intact = (
                page.locator(".body-log-open").count() == 1
                and page.locator(".screen.body > .body-card").count() >= 1
                and page.locator(".metric-toggle .metric-pill.on").inner_text().strip() == "體脂"
            )
            check("⑥ 切換後畫面完整（入口鈕、圖表卡、選中的頁籤都在）", intact, f"intact={intact}")

            # ②④ 體脂頁籤：圖表換體脂、單位 %。
            # ⚠ **F87 ⑧ 取代了「只列有體脂的日子」**：改成「全部日子都列、沒體脂顯示 —」，
            # 因為原本的做法讓沒量體脂的日子在該頁籤看不到也改不到（F53 ② 本來就沒明說要濾）。
            # 這裡因此驗「全部都列 ＋ 有體脂的那幾筆是 %」，不再驗筆數等於有體脂的天數。
            rows_f = page.locator(".bm-rows .bm-row").count()
            vals_f = page.locator(".bm-rows .bm-row .bm-val").all_inner_texts()
            pct_rows = [v for v in vals_f if "%" in v]
            latest_f = page.locator(".body-main-value").inner_text()
            foot_f = page.locator(".body-main-delta").inner_text()
            check(
                "②④ 體脂頁籤：全部日子都列（沒體脂顯示 —）、有值的顯示 %，卡片最新值與範圍也是 %",
                rows_f == len(all_days)
                and len(pct_rows) == len(fat_days)
                and "%" in latest_f
                and "%" in foot_f,
                f"rows={rows_f}（期望 {len(all_days)}）有%的={len(pct_rows)}"
                f"（期望 {len(fat_days)}）latest={latest_f!r}",
            )

            # ③ 體脂頁籤下編輯仍是整筆（編輯列有體重與體脂兩個輸入）
            page.locator(".bm-rows .bm-row .bm-edit").first.click()
            page.wait_for_timeout(300)
            editing = (
                page.locator(".bm-row.editing .bm-edit-weight").count() == 1
                and page.locator(".bm-row.editing .bm-edit-fat").count() == 1
            )
            page.locator('.bm-row.editing button:has-text("取消")').click()
            page.wait_for_timeout(300)
            check(
                "③ 體脂頁籤下編輯仍是整筆操作（編輯列同時有體重與體脂欄）",
                editing,
                f"editing={editing}",
            )

            # ⑧ 清單填滿剩餘空間：三種高度下 .bm-rows 高度不同，「← 回首頁」完整可見
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(300)
            heights, btn_ok = {}, {}
            for h in (1000, 900, 844):  # ≥700 的高視窗：清單填滿剩餘空間
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(300)
                heights[h] = box_h(page, ".bm-rows.scrollable")
                btn_ok[h] = fully_visible(page, '.screen.body .back-btn')
            check(
                "⑧ 高視窗：紀錄清單填滿剩餘空間（高度隨螢幕變化）、「← 回首頁」完整可見",
                heights[1000] > heights[900] > heights[844] and all(btn_ok.values()),
                f"heights={heights} btn_ok={btn_ok}",
            )

            # ⑧/⑨ 矮視窗（<700，含 iPhone SE 的 667）：/body 固定區塊實測 584px，放不下 → 整頁可捲
            # 判定用「行為」而非「數值」：667 時 height:auto 算出的內容高度剛好等於 639（＝667−28），
            # 與釘死的值撞在一起——拿數值當判準會誤判（同「測試載體不能用邊界值」那條教訓）。
            short_ok = {}
            for h in (667, 560):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(300)
                page.locator(
                    '.screen.body .back-btn'
                ).scroll_into_view_if_needed()
                page.wait_for_timeout(250)
                rows_h = box_h(page, ".bm-rows")
                short_ok[h] = {
                    "btn_visible": fully_visible(page, '.screen.body .back-btn'),
                    "rows_h": rows_h,
                    # 修正後矮螢幕的正確行為＝收在 40dvh 內（不吃剩餘空間、不被拉成滿高）
                    "not_stretched": rows_h is not None and rows_h <= h * 0.42,
                }
            check(
                "⑧/⑨ 矮視窗（667／560）：不強行填滿（清單收在下限）、「← 回首頁」最終完整可見（必要時可捲）",
                all(v["btn_visible"] and v["not_stretched"] for v in short_ok.values()),
                f"{short_ok}",
            )

            # review P1-1 回歸：矮螢幕不得破圖——rows 不可溢出清單卡、不可疊在「← 回首頁」上
            # （原本只驗「按鈕在畫面內」，漏掉「有東西畫在它上面」——按鈕可見不等於沒被蓋住）
            overlap = {}
            for h in (732, 700, 667, 560):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(320)
                overlap[h] = page.evaluate("""() => {
                  const card = document.querySelector('.body-card.body-list');
                  const rows = document.querySelector('.bm-rows');
                  const btn = [...document.querySelectorAll('.screen.body button')]
                    .find(b => b.textContent.includes('回首頁'));
                  const c = card.getBoundingClientRect();
                  const r = rows.getBoundingClientRect();
                  const b = btn.getBoundingClientRect();
                  return { rows_overflow: Math.round(Math.max(0, r.bottom - c.bottom)),
                           over_btn: Math.round(Math.max(0, r.bottom - b.top)) };
                }""")
            check(
                "review P1-1：矮螢幕不破圖（rows 不溢出清單卡、不疊在「← 回首頁」上）",
                all(v["rows_overflow"] <= 1 and v["over_btn"] <= 1 for v in overlap.values()),
                f"{overlap}",
            )

            # review P1-2 回歸：門檻死帶——701~732 之間不得「釘死高度但塞不進」
            band = {}
            for h in (733, 732, 720, 701):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(320)
                band[h] = page.evaluate("""() => {
                  const btn = [...document.querySelectorAll('.screen.body button')]
                    .find(b => b.textContent.includes('回首頁'));
                  const b = btn.getBoundingClientRect();
                  return { btn_in_view: b.bottom <= window.innerHeight + 1,
                           doc_scroll: document.documentElement.scrollHeight - window.innerHeight };
                }""")
            check(
                "review P1-2：門檻校準後 701–732 無死帶（按鈕在畫面內，或頁面確實可捲得到）",
                all(v["btn_in_view"] or v["doc_scroll"] > 0 for v in band.values()),
                f"{band}",
            )
            # F54 起表單移出畫面、清單變高，1000px 高時 10 筆資料不再溢出（捲不動＝測不到）。
            # 捲動相關檢查改在 700 高跑：門檻(556) 以上仍是填滿模式，且內容確實溢出。
            page.set_viewport_size({"width": 390, "height": 700})
            page.wait_for_timeout(320)

            # review P2-2 回歸：切過去再切回來，清單捲動位置要回到原處
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(300)
            rows_box = page.locator(".bm-rows").bounding_box()
            page.mouse.move(
                rows_box["x"] + rows_box["width"] / 2, rows_box["y"] + rows_box["height"] / 2
            )
            page.mouse.wheel(0, 80)
            page.wait_for_timeout(350)
            st_before = page.eval_on_selector(".bm-rows", "e => e.scrollTop")
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(300)
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(350)
            st_after = page.eval_on_selector(".bm-rows", "e => e.scrollTop")
            check(
                "review P2-2：切體脂再切回體重，清單捲動位置回到原處",
                st_before > 0 and abs(st_after - st_before) <= 2,
                f"before={st_before} after={st_after}",
            )

            # review P2-1 回歸：整頁重繪（點某列 ✎ 進編輯態）後捲動位置保留
            st2_before = page.eval_on_selector(".bm-rows", "e => e.scrollTop")
            page.locator(".bm-rows .bm-row .bm-edit").last.evaluate(
                "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
            )
            page.wait_for_timeout(450)
            st2_after = page.eval_on_selector(".bm-rows", "e => e.scrollTop")
            page.locator('.bm-row.editing button:has-text("取消")').evaluate(
                "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
            )
            page.wait_for_timeout(300)
            check(
                "review P2-1：整頁重繪（進編輯態）後清單捲動位置保留",
                st2_before > 0 and abs(st2_after - st2_before) <= 2,
                f"before={st2_before} after={st2_after}",
            )

            # review P3-1 回歸：切頁籤會退出行內編輯態
            page.locator(".bm-rows .bm-row .bm-edit").first.evaluate(
                "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
            )
            page.wait_for_timeout(300)
            was_editing = page.locator(".bm-row.editing").count() == 1
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(350)
            check(
                "review P3-1：切換頁籤時退出行內編輯態（不留看不見的編輯中狀態）",
                was_editing and page.locator(".bm-row.editing").count() == 0,
                f"was_editing={was_editing} still={page.locator('.bm-row.editing').count()}",
            )
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(300)

            # ⑧ 門檻：≤2 筆不加 scrollable（刪到剩 2 筆）
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)
            for _ in range(8):
                page.locator(".bm-rows .bm-row .bm-del").first.evaluate(
                    "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
                )
                page.wait_for_timeout(350)
            n_left = page.locator(".bm-rows .bm-row").count()
            check(
                "⑧ 門檻語意：清單 ≤2 筆時不加 scrollable",
                n_left == 2 and page.locator(".bm-rows.scrollable").count() == 0,
                f"rows={n_left} scrollable={page.locator('.bm-rows.scrollable').count()}",
            )

            # ⑨ 極矮／橫向回退成整頁可捲
            short = {}
            for w, h in ((844, 390), (320, 420)):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(300)
                page.locator(
                    '.screen.body .back-btn'
                ).scroll_into_view_if_needed()
                page.wait_for_timeout(200)
                short[f"{w}x{h}"] = fully_visible(page, '.screen.body .back-btn')
            check(
                "⑨ 極矮／橫向視窗回退成整頁可捲，「← 回首頁」捲動後完整可見",
                all(short.values()),
                f"{short}",
            )

            # ④ 完全沒體脂紀錄時，體脂頁籤顯示空狀態
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)
            for m in api(base, "GET", "/api/body-metrics"):
                if m.get("body_fat_pct") is not None:
                    api(
                        base,
                        "POST",
                        "/api/body-metrics",
                        {"date": m["date"], "weight_kg": m["weight_kg"]},
                    )  # 覆蓋成無體脂
            page.reload()
            wait_home(page)
            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(400)
            empty_txt = page.locator(".screen.body .body-empty").first.inner_text()
            check(
                "④ 完全沒有體脂紀錄時，體脂頁籤顯示「還沒有紀錄」",
                "還沒有紀錄" in empty_txt,
                f"text={empty_txt!r}",
            )

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        if tmpdb.exists():
            try:
                tmpdb.unlink()
            except Exception:
                pass

    print("\n==== F53 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
