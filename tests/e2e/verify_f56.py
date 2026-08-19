"""F56 體重頁圖表可自選時間長度 E2E（含 F54／F55 行為回歸）。

用法：PYTHONUTF8=1 uv run python tests/e2e/verify_f56.py

⚠ **2026-08-01 Ryan 裁決（F119 選 B）：F56 的「自訂區間」已被 F87 ③ 取代，不補回。**
因此本腳本中專驗自訂面板的條目（原 (2) 的起訖驗證、原 (6) 的自訂空窗、review P2-2 的面板
展開版面）已改寫或移除，並在各處註明。**其餘條文一條都沒放寬**——chips 切換要同步篩圖表與
清單、與 metric toggle 正交、無資料不炸圖、切換失敗的原子性，全部照原樣驗，只是改用還存在的
UI（五顆預設藥丸）達成。
"""

import datetime
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from verify_f67 import (  # noqa: E402
    TOKEN,
    read_version,
    safe_port,
    start_server,
    wait_home,
)


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


def box_h(page, sel):
    b = page.locator(sel).first.bounding_box()
    return round(b["height"]) if b else None


GEO = """() => {
  const card = document.querySelector('.body-card.body-list');
  const rows = document.querySelector('.bm-rows');
  const btn = [...document.querySelectorAll('.screen.body button')]
    .find(b => b.textContent.includes('回首頁'));
  const c = card.getBoundingClientRect(), r = rows.getBoundingClientRect(),
        b = btn.getBoundingClientRect();
  return { overflow: Math.round(Math.max(0, r.bottom - c.bottom)),
           over_btn: Math.round(Math.max(0, r.bottom - b.top)) };
}"""


# /body 的「填滿門檻」由 app.css 決定（固定區塊每次改都會變）——這裡從服役中的 CSS 直接讀出來，
# 腳本就不會每次 feature 改門檻都變紅（F56 加了 chips 一列，門檻 612→656）
def body_threshold(base):
    import re as _re

    css = urllib.request.urlopen(base + "/css/app.css", timeout=5).read().decode()
    mm = _re.search(r"@media \(max-height: (\d+)px\) \{\s*\.screen\.body", css)
    return int(mm.group(1))


def chips_row_budget(base):
    """門檻算式裡替時間窗藥丸列編的高度預算（app.css 那段註解是唯一來源）。

    原本這裡寫死 34px（chips 還是 30px 高的年代）。F87 把藥丸改成 44px、算式跟著重算，
    寫死的數字就變成假紅——但**不能因此拿掉這條檢查**：它驗的是「實際量到的高度沒有偷偷
    超過算式編列的預算」，超過就代表門檻失準、矮螢幕會出現死帶（F53／F54 各踩過一次）。
    所以改成從算式本身讀，量到的必須與預算一致。
    """
    import re as _re

    css = urllib.request.urlopen(base + "/css/app.css", timeout=5).read().decode()
    mm = _re.search(r"時間窗藥丸 (\d+)", css)
    return int(mm.group(1))


CHIP_ROWS = """() => {
  const tops = [...document.querySelectorAll('.body-range button')]
    .map(b => Math.round(b.getBoundingClientRect().top));
  return { rows: new Set(tops).size,
           h: Math.round(document.querySelector('.body-range').getBoundingClientRect().height) };
}"""

def main():
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f56-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    try:
        today = datetime.date.today()
        # 跨三年的資料點：讓 1M < 3M < 1Y 有明顯差異；890-885 天前刻意留空窗（驗 6）
        DAYS_AGO = [900, 700, 500, 400, 200, 120, 80, 60, 45, 40, 30, 25, 20, 16] + list(
            range(12, 0, -1)
        )
        for i in DAYS_AGO:
            d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            payload = {"date": d, "weight_kg": 100.0 + i * 0.02}
            if i % 4 == 0:
                payload["body_fat_pct"] = 24.0 + i * 0.005
            api(base, "POST", "/api/body-metrics", payload)

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            wait_home(page)

            ver = read_version(page)  # F81 把版號搬進設定畫面
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            check(
                "⑨ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v57）",
                ver.startswith("v") and int(ver[1:]) >= 57 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)

            # ①② 入口鈕在畫面下方、在「← 回首頁」之上；版面順序正確
            order = page.evaluate("""() => {
              const s = document.querySelector('.screen.body');
              const kids = [...s.children].filter(c => !c.classList.contains('modal-overlay'));
              const cls = kids.map(c => c.className.split(' ').filter(x => x).slice(0, 2).join('.'));
              const openBtn = document.querySelector('.body-log-open');
              const home = kids.find(c => c.textContent.trim().includes('回首頁'));
              const list = document.querySelector('.body-card.body-list');
              return { cls,
                       open_idx: kids.indexOf(openBtn), home_idx: kids.indexOf(home),
                       list_idx: kids.indexOf(list),
                       open_above_home: openBtn.getBoundingClientRect().top < home.getBoundingClientRect().top,
                       open_below_list: openBtn.getBoundingClientRect().top > list.getBoundingClientRect().top };
            }""")
            check(
                "①② 「＋ 記錄」在畫面下方（清單之下、「← 回首頁」之上），版面順序正確",
                order["open_idx"] == order["home_idx"] - 1
                and order["list_idx"] < order["open_idx"]
                and order["open_above_home"]
                and order["open_below_list"]
                and page.locator(".screen.body > .body-form").count() == 0,
                f"order={order['cls']} open_idx={order['open_idx']} home_idx={order['home_idx']}",
            )

            # (1)(8) chips 存在、預設 3M
            chips = page.locator(".body-range button")
            labels = [chips.nth(i).inner_text().strip() for i in range(chips.count())]
            on = page.locator(".body-range button.on").inner_text().strip()
            rows_3m = page.locator(".bm-rows .bm-row").count()
            check(
                "(1)(8) 區間 chips（F87 ③ 的五顆：1M/3M/6M/1Y/全部）存在、預設 3M",
                labels == ["1M", "3M", "6M", "1Y", "全部"] and on == "3M",
                f"labels={labels} on={on!r} rows={rows_3m}",
            )

            # (3) 切區間：1M < 3M <= 1Y
            page.locator('.body-range button:has-text("1M")').click()
            page.wait_for_timeout(700)
            rows_1m = page.locator(".bm-rows .bm-row").count()
            on_1m = page.locator(".body-range button.on").inner_text().strip()
            page.locator('.body-range button:has-text("1Y")').click()
            page.wait_for_timeout(700)
            rows_1y = page.locator(".bm-rows .bm-row").count()
            check(
                "(3) 切區間帶 start/end 查後端，圖表與清單同步（1M < 3M <= 1Y）",
                on_1m == "1M" and rows_1m < rows_3m <= rows_1y,
                f"1M={rows_1m} 3M={rows_3m} 1Y={rows_1y}",
            )

            # (2) 原文驗的是「自訂區間套用後清單只含區間內日期」。自訂面板已被 F87 ③ 取代
            # （2026-08-01 Ryan 裁決 F119 選 B），但**條文的目的沒有被取代**：選了一個區間，
            # 清單就只能有那個區間內的日期。改用還存在的 1M 藥丸驗同一件事。
            page.locator('.body-range button:has-text("1M")').click()
            page.wait_for_timeout(800)
            on_1m2 = page.locator(".body-range button.on").inner_text().strip()
            dates_in = page.eval_on_selector_all(
                ".bm-rows .bm-row .bm-date", "els => els.map(e => e.textContent.trim())"
            )
            # 1M 是**日曆月**（monthsAgo 會 clamp 月底），實際天數落在 28–31 之間，故用 32 天當寬鬆下界；
            # 資料集裡有 900/700/500 天前的點，能真的驗到「被篩掉了」而不是「本來就沒有舊資料」。
            floor_iso = (today - datetime.timedelta(days=32)).strftime("%Y-%m-%d")
            all_metrics = api(base, "GET", "/api/body-metrics")
            has_older = any(m["date"] < floor_iso for m in all_metrics)
            check(
                "(2) 選定區間後清單只含區間內日期（原文的自訂面板已由 F87 ③ 取代，改用 1M 藥丸驗同一目的）",
                on_1m2 == "1M"
                and len(dates_in) > 0
                and has_older
                and all(d >= floor_iso for d in dates_in),
                f"on={on_1m2!r} rows={len(dates_in)} oldest={min(dates_in) if dates_in else None} "
                f"floor={floor_iso} has_older={has_older}",
            )

            # (4) 切換失敗（5xx）→ 區間與資料都不動
            page.locator('.body-range button:has-text("3M")').click()
            page.wait_for_timeout(700)
            before_on = page.locator(".body-range button.on").inner_text().strip()
            before_rows = page.locator(".bm-rows .bm-row").count()
            page.route("**/api/body-metrics*", lambda r: r.fulfill(status=500, body="boom"))
            page.locator('.body-range button:has-text("6M")').click()
            page.wait_for_timeout(900)
            after_on = page.locator(".body-range button.on").inner_text().strip()
            after_rows = page.locator(".bm-rows .bm-row").count()
            err = page.locator(".screen.body .error-banner").count()
            page.unroute("**/api/body-metrics*")
            check(
                "(4) 切換失敗（5xx）原子性：區間與資料都不動、錯誤有顯示（無半套狀態）",
                before_on == after_on == "3M" and before_rows == after_rows and err == 1,
                f"on {before_on}->{after_on} rows {before_rows}->{after_rows} err={err}",
            )

            # (5) 與 toggle 正交
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(400)
            range_after_metric = page.locator(".body-range button.on").inner_text().strip()
            page.locator('.body-range button:has-text("6M")').click()
            page.wait_for_timeout(800)
            metric_after_range = page.locator(".metric-toggle .metric-pill.on").inner_text().strip()
            check(
                "(5) 與體重／體脂 toggle 正交（切 metric 不改區間、切區間不改 metric）",
                range_after_metric == "3M" and metric_after_range == "體脂",
                f"range_after_metric={range_after_metric!r} metric_after_range={metric_after_range!r}",
            )
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(300)

            # (6) 原文用「自訂到一段空窗」驗無資料不炸圖。自訂面板已無，改用等價手段：
            # 把最近 40 天的紀錄全部刪掉，再選 1M——區間存在但區間內沒有資料，正是原文要驗的狀況。
            # 刪完之後**要把資料補回去**，否則後面的檢查全部失去前提。
            wiped = [
                m["date"] for m in api(base, "GET", "/api/body-metrics")
                if m["date"] >= (today - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
            ]
            wiped_rows = [m for m in api(base, "GET", "/api/body-metrics") if m["date"] in wiped]
            for d in wiped:
                api(base, "DELETE", f"/api/body-metrics/{d}")
            page.reload()
            page.wait_for_timeout(400)
            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.locator('.body-range button:has-text("1M")').click()
            page.wait_for_timeout(800)
            empties = page.locator(".screen.body .body-empty").count()
            empty_rows = page.locator(".bm-rows .bm-row").count()
            check(
                "(6) 區間內無資料 → 顯示「還沒有紀錄」不炸圖",
                empties >= 1 and empty_rows == 0,
                f"empty_blocks={empties} rows={empty_rows} wiped={len(wiped)}",
            )
            for m in wiped_rows:  # 補回去：後面的檢查都靠這批資料
                payload = {"date": m["date"], "weight_kg": m["weight_kg"]}
                if m.get("body_fat_pct") is not None:
                    payload["body_fat_pct"] = m["body_fat_pct"]
                api(base, "POST", "/api/body-metrics", payload)
            page.reload()
            page.wait_for_timeout(400)
            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.locator('.body-range button:has-text("3M")').click()
            page.wait_for_timeout(700)

            # review P2-3 回歸：chips 在窄螢幕也要一行（門檻算式的 30px 前提）。
            # 顆數已由 8 降為 5（F87 ③），一行的要求不變——反而更容易成立
            chip_rows = {}
            for w in (320, 360, 375, 390):
                page.set_viewport_size({"width": w, "height": 900})
                page.wait_for_timeout(300)
                chip_rows[w] = page.evaluate(CHIP_ROWS)
            budget = chips_row_budget(base)
            check(
                "review P2-3：區間 chips（5 顆）在 320/360 窄螢幕仍是一行，且不超過門檻算式編的預算",
                all(v["rows"] == 1 and v["h"] <= budget for v in chip_rows.values()),
                f"budget={budget} {chip_rows}",
            )

            # review P2-2（自訂面板展開時的版面）**已移除**：那條驗的是自訂起訖面板展開後
            # 不溢出、不重疊，而面板本身已隨 F87 ③ 消失（2026-08-01 Ryan 裁決 F119 選 B）。
            # 這不是放寬斷言——被驗的 UI 不存在了。chips 列本身的版面由 P2-3 那條顧著。
            page.set_viewport_size({"width": 390, "height": 900})
            page.wait_for_timeout(250)

            # ② 視窗內容齊全＋點遮罩關閉
            page.locator(".body-log-open").click()
            page.wait_for_selector(".body-log-modal", timeout=5000)
            parts = (
                page.locator(".body-log-modal .bm-date-picker").count() == 1
                and page.locator('.body-log-modal input[placeholder^="體重"]').count() == 1
                and page.locator('.body-log-modal input[placeholder^="體脂"]').count() == 1
                and page.locator('.body-log-modal button:has-text("✓ 記錄")').count() == 1
                and page.locator('.body-log-modal button:has-text("取消")').count() == 1
            )
            page.locator(".modal-overlay").click(position={"x": 5, "y": 5})
            page.wait_for_timeout(300)
            check(
                "② 視窗含日期／體重／體脂／✓ 記錄／取消；點遮罩空白處關閉",
                parts and page.locator(".body-log-modal").count() == 0,
                f"parts={parts}",
            )

            # ⑥ 開窗乾淨狀態
            today_iso = today.strftime("%Y-%m-%d")
            page.locator(".body-log-open").click()
            page.wait_for_selector(".body-log-modal", timeout=5000)
            d0 = page.locator(".body-log-modal .bm-date-picker").input_value()
            w0 = page.locator('.body-log-modal input[placeholder^="體重"]').input_value()
            check(
                "⑥ 開窗預設：日期＝今天、體重帶最新值當起點",
                d0 == today_iso and w0 not in ("", None),
                f"date={d0!r} weight={w0!r}",
            )

            # ④ 失敗 → 視窗不關、輸入保留、錯誤在視窗內
            page.locator('.body-log-modal input[placeholder^="體重"]').fill("999")
            page.locator('.body-log-modal button:has-text("✓ 記錄")').click()
            page.wait_for_timeout(600)
            err_in_modal = page.locator(".body-log-modal .error-banner").count()
            still_open = page.locator(".body-log-modal").count()
            kept = page.locator('.body-log-modal input[placeholder^="體重"]').input_value()
            check(
                "④ 送出失敗：視窗不關、輸入保留、錯誤訊息在視窗內（不被遮罩蓋住）",
                err_in_modal == 1 and still_open == 1 and kept == "999",
                f"err={err_in_modal} open={still_open} kept={kept!r}",
            )

            # ③④ 成功（F11 補記過去日期）→ 關窗、資料落在該日、toggle 狀態保留
            page.locator('.body-log-modal button:has-text("取消")').click()
            page.wait_for_timeout(250)
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(250)
            page.locator(".body-log-open").click()
            page.wait_for_selector(".body-log-modal", timeout=5000)
            past = (today - datetime.timedelta(days=20)).strftime("%Y-%m-%d")
            page.locator(".body-log-modal .bm-date-picker").fill(past)
            page.locator(".body-log-modal .bm-date-picker").dispatch_event("change")
            page.wait_for_timeout(300)
            page.locator('.body-log-modal input[placeholder^="體重"]').fill("95.5")
            page.locator('.body-log-modal input[placeholder^="體脂"]').fill("22.2")
            page.locator('.body-log-modal button:has-text("✓ 記錄")').click()
            page.wait_for_timeout(1000)
            closed = page.locator(".body-log-modal").count() == 0
            saved = [m for m in api(base, "GET", "/api/body-metrics") if m["date"] == past]
            metric_kept = page.locator(".metric-toggle .metric-pill.on").inner_text().strip()
            flash = page.locator(".body-saved").count()
            check(
                "③④ 成功記錄（含 F11 補記過去日期）→ 自動關窗、資料落該日、toggle 狀態保留、flash 出現",
                closed
                and len(saved) == 1
                and saved[0]["weight_kg"] == 95.5
                and metric_kept == "體脂"
                and flash == 1,
                f"closed={closed} saved={saved} metric={metric_kept!r} flash={flash}",
            )

            # ③ 換日期帶入該日既有紀錄
            page.locator(".body-log-open").click()
            page.wait_for_selector(".body-log-modal", timeout=5000)
            page.locator(".body-log-modal .bm-date-picker").fill(past)
            page.locator(".body-log-modal .bm-date-picker").dispatch_event("change")
            page.wait_for_timeout(350)
            w_back = page.locator('.body-log-modal input[placeholder^="體重"]').input_value()
            f_back = page.locator('.body-log-modal input[placeholder^="體脂"]').input_value()
            check(
                "③ 換日期帶入該日既有紀錄（同日覆蓋看得見）",
                w_back == "95.5" and f_back == "22.2",
                f"weight={w_back!r} fat={f_back!r}",
            )
            page.locator('.body-log-modal button:has-text("取消")').click()
            page.wait_for_timeout(300)

            # ⑤ 667 高也能填滿；門檻上下皆不破圖
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(250)
            fill_h, geo = {}, {}
            T = body_threshold(base)  # 門檻的唯一來源在 app.css
            for h in (T + 244, T + 144, T + 44, T + 1, T, T - 56, T - 112):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(330)
                fill_h[h] = box_h(page, ".bm-rows")
                geo[h] = page.evaluate(GEO)
            # 填滿模式只在 ≥613（門檻 612，見 app.css 算式）；600 以下是退回模式，rows 取 40dvh 故數值會回升，
            # 不納入遞減比較——但各高度都必須不破圖
            check(
                "⑦ 門檻（由 app.css 讀出）成立：≥T+1 填滿且遞減、各高度不破圖",
                fill_h[T + 244] > fill_h[T + 144] > fill_h[T + 44] > fill_h[T + 1]
                and all(g["overflow"] <= 1 and g["over_btn"] <= 1 for g in geo.values()),
                f"heights={fill_h} geo={geo}",
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)

            # review P2-1 回歸：有 flash／殘留錯誤時也不得溢出（門檻改用最壞情況 612）
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)
            page.locator(".body-log-open").click()
            page.wait_for_selector(".body-log-modal", timeout=5000)
            page.locator('.body-log-modal input[placeholder^="體重"]').fill("101.1")
            page.locator('.body-log-modal button:has-text("✓ 記錄")').click()
            page.wait_for_timeout(900)
            flash_on = page.locator(".body-saved").count() == 1
            band = {}
            for h in (T + 1, T, T - 36, T - 86, T - 156):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(330)
                band[h] = page.evaluate("""() => {
                  const btn = [...document.querySelectorAll('.screen.body button')]
                    .find(b => b.textContent.includes('回首頁'));
                  const b = btn.getBoundingClientRect();
                  const g = (() => {
                    const card = document.querySelector('.body-card.body-list');
                    const rows = document.querySelector('.bm-rows');
                    if (!card || !rows) return 0;
                    return Math.round(Math.max(0,
                      rows.getBoundingClientRect().bottom - card.getBoundingClientRect().bottom));
                  })();
                  return { btn_in_view: b.bottom <= window.innerHeight + 1,
                           doc_scroll: document.documentElement.scrollHeight - window.innerHeight,
                           overflow: g };
                }""")
            check(
                "review P2-1：flash 出現時 557–612 不再有死帶（按鈕在畫面內或頁面確實可捲、清單不溢出）",
                flash_on
                and all(
                    (v["btn_in_view"] or v["doc_scroll"] > 0) and v["overflow"] <= 1
                    for v in band.values()
                ),
                f"flash={flash_on} {band}",
            )

            # review P2-2 回歸：用遮罩關窗要清掉錯誤，不留過期紅字在畫面上
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)
            page.locator(".body-log-open").click()
            page.wait_for_selector(".body-log-modal", timeout=5000)
            page.locator('.body-log-modal input[placeholder^="體重"]').fill("9")
            page.locator('.body-log-modal button:has-text("✓ 記錄")').click()
            page.wait_for_timeout(600)
            err_while_open = page.locator(".error-banner").count()
            page.locator(".modal-overlay").click(position={"x": 5, "y": 5})
            page.wait_for_timeout(400)
            err_after_close = page.locator(".error-banner").count()
            check(
                "review P2-2：點遮罩關窗會清掉錯誤（不留過期紅字撐高版面）",
                err_while_open >= 1
                and err_after_close == 0
                and page.locator(".body-log-modal").count() == 0,
                f"while_open={err_while_open} after_close={err_after_close}",
            )

            # ⑦ 既有行為：清單編輯整筆、分頁籤捲動記憶
            page.locator(".bm-rows .bm-row .bm-edit").first.evaluate(
                "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
            )
            page.wait_for_timeout(350)
            edit_ok = (
                page.locator(".bm-row.editing .bm-edit-weight").count() == 1
                and page.locator(".bm-row.editing .bm-edit-fat").count() == 1
            )
            page.locator('.bm-row.editing button:has-text("取消")').evaluate(
                "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
            )
            page.wait_for_timeout(300)
            rows_box = page.locator(".bm-rows").bounding_box()
            page.mouse.move(
                rows_box["x"] + rows_box["width"] / 2, rows_box["y"] + rows_box["height"] / 2
            )
            page.mouse.wheel(0, 60)
            page.wait_for_timeout(350)
            st_b = page.eval_on_selector(".bm-rows", "e => e.scrollTop")
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(250)
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(350)
            st_a = page.eval_on_selector(".bm-rows", "e => e.scrollTop")
            check(
                "⑦ 既有行為：清單編輯仍整筆（F53 ③）、分頁籤捲動記憶仍在（F53 P2-2）",
                edit_ok and st_b > 0 and abs(st_a - st_b) <= 2,
                f"edit_ok={edit_ok} scroll {st_b}→{st_a}",
            )

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n==== F56 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
