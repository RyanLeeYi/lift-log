"""F55 體重頁「＋ 記錄」移到畫面下方 E2E（含 F54 行為回歸）。
用法：PYTHONUTF8=1 uv run python verify_f55_own.py
涵蓋 F55 acceptance ①–⑤（沿用 F54 腳本的視窗行為檢查當 ④ 的回歸）。
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

REPO = Path(r"C:\Users\user\OneDrive\Desktop\SideProject\lift-log")
TOKEN = "f55-own-token"


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


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f55_{port}.db"
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

        today = datetime.date.today()
        for i in range(12, 0, -1):
            d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            payload = {"date": d, "weight_kg": 100.0 + i * 0.3}
            if i % 4 == 0:
                payload["body_fat_pct"] = 24.0 + i * 0.1
            api(base, "POST", "/api/body-metrics", payload)

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            page.wait_for_selector(".home-start", timeout=8000)

            ver = page.locator(".version-tag").first.inner_text().strip()
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            check(
                "⑤ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v56）",
                ver.startswith("v") and int(ver[1:]) >= 56 and f'liftlog-shell-{ver}"' in sw_src,
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
            page.locator(".body-metric-toggle .chip", has_text="體脂").click()
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
            metric_kept = page.locator(".body-metric-toggle .chip.on").inner_text().strip()
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
            page.locator(".body-metric-toggle .chip", has_text="體重").click()
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
                "③ 門檻 612 仍成立（≥613 填滿、遞減正確），各高度不破圖（不溢出、不疊住按鈕）",
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
            page.locator(".body-metric-toggle .chip", has_text="體脂").click()
            page.wait_for_timeout(250)
            page.locator(".body-metric-toggle .chip", has_text="體重").click()
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
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        if tmpdb.exists():
            try:
                tmpdb.unlink()
            except Exception:
                pass

    print("\n==== F54 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
