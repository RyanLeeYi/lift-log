"""F58 資料不足時停用超出範圍的區間檔位 E2E。
用法：PYTHONUTF8=1 uv run python tests/e2e/verify_f58.py
涵蓋 acceptance ①–⑧。

測資設計：體重從 100 天前開始、體脂只從 20 天前開始 → 體重可用到 6M（100 天）、
體脂只可用到 1M，切 toggle 會觸發自動退檔（acceptance ④）。
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


def chip_state(page):
    return page.evaluate("""() => {
      const out = {};
      for (const b of document.querySelectorAll('.body-range button')) {
        out[b.textContent.trim()] = { off: b.classList.contains('off'), on: b.classList.contains('on') };
      }
      return out;
    }""")


def main():
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f58-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    try:
        today = datetime.date.today()

        # ⑥ 先在完全沒資料時驗「不限制」
        bounds_empty = api(base, "GET", "/api/body-metrics/range")

        # 體重 100 天前開始、體脂 20 天前才開始
        for i in [100, 90, 80, 60, 40, 30, 25, 20, 15, 10, 5, 1]:
            d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            payload = {"date": d, "weight_kg": 100.0 + i * 0.02}
            if i <= 20:
                payload["body_fat_pct"] = 24.0 + i * 0.01
            api(base, "POST", "/api/body-metrics", payload)
        bounds = api(base, "GET", "/api/body-metrics/range")
        w_first = (today - datetime.timedelta(days=100)).strftime("%Y-%m-%d")
        f_first = (today - datetime.timedelta(days=20)).strftime("%Y-%m-%d")
        check(
            "① 端點回體重／體脂各自的最早紀錄日與整體最後一天（空 DB 回 null）",
            bounds_empty == {"weight_first": None, "fat_first": None, "last": None}
            and bounds["weight_first"] == w_first
            and bounds["fat_first"] == f_first
            and bounds["last"] == (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
            f"empty={bounds_empty} bounds={bounds}",
        )

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 900})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            wait_home(page)

            ver = read_version(page)  # F81 把版號搬進設定畫面
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            check(
                "⑧ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v59）",
                ver.startswith("v") and int(ver[1:]) >= 59 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.wait_for_timeout(600)

            # ② 體重（最早 100 天前）→ 1M/3M/6M 可用；再上去的檔位灰掉。
            # ⚠ F87 ③ 把檔位改成五顆（1M／3M／6M／1Y／全部），9M 與 3Y 不存在了、
            # 自訂區間也被拿掉（見 F119）。**F58 的規則本身沒變**——
            # 「涵蓋得住資料的第一個檔位可用、再上去的灰掉」——只是檔位清單換了。
            st = chip_state(page)
            check(
                "② 體重頁籤：涵蓋範圍內＋第一個涵蓋得住全部資料的檔位可用（100 天 → 1M/3M/6M），再上去灰",
                not st["1M"]["off"]
                and not st["3M"]["off"]
                and not st["6M"]["off"]
                and st["1Y"]["off"],
                f"{ {k: ('off' if v['off'] else 'on-able') for k, v in st.items()} }",
            )

            # ③ 點停用的檔位 → 只顯示說明、不切區間、不打 API
            before_on = [k for k, v in st.items() if v["on"]]
            page.locator('.body-range button:has-text("1Y")').click()
            page.wait_for_timeout(500)
            note = page.locator(".range-note").count()
            note_txt = page.locator(".range-note").inner_text() if note else ""
            after_on = [k for k, v in chip_state(page).items() if v["on"]]
            check(
                "③ 點停用檔位：顯示說明（含最早紀錄日）、選取的區間不變",
                note == 1
                and w_first in note_txt
                and "體重" in note_txt
                and before_on == after_on == ["3M"],
                f"note={note_txt!r} on {before_on}→{after_on}",
            )

            # ④ 切體脂（最早 20 天前）→ 3M 不可用 → 自動退到最長可用檔位並說明。
            # F87 ③ 加了「全部」檔位，它永遠可用，所以 longestAvailable() 的答案從 1M 變成「全部」。
            # 2026-08-01 Ryan 裁決：**退到「全部」就是要的行為**（最完整、不漏資料），期望值跟著改。
            # 同時驗 F120 的文案 bug：months === null 不得被直接串成「最近 null 個月」。
            page.locator('.body-range button:has-text("6M")').click()
            page.wait_for_timeout(700)
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(900)
            st_fat = chip_state(page)
            fat_on = [k for k, v in st_fat.items() if v["on"]]
            fat_note = (
                page.locator(".range-note").inner_text()
                if page.locator(".range-note").count()
                else ""
            )
            check(
                "④ 切體脂後當前檔位不可用 → 自動退到最長可用檔位（「全部」）並顯示說明",
                fat_on == ["全部"] and st_fat["3M"]["off"] and f_first in fat_note,
                f"on={fat_on} 3M_off={st_fat['3M']['off']} note={fat_note!r}",
            )
            check(
                "④（F120）退檔說明不得出現 null——「全部」要講成「全部紀錄」",
                "null" not in fat_note and "全部紀錄" in fat_note,
                f"note={fat_note!r}",
            )

            # review P1-1 回歸（我的 E2E 原本漏掉的分支）：切 metric 後 chips 的灰／亮要**跟著重畫**，
            # 且說明文字不得留著上一個 metric 的內容。測「當前檔位對兩個 metric 都可用」的情形——
            # 那條路徑不走自動退檔，原本只呼叫 paint()（不碰 chips 與 note）
            page.locator(
                ".metric-toggle .metric-pill", has_text="體重"
            ).click()  # 前一段留在體脂，先還原
            page.wait_for_timeout(700)
            page.locator('.body-range button:has-text("1M")').click()  # 1M 對體重與體脂都可用
            page.wait_for_timeout(800)
            page.locator('.body-range button:has-text("1Y")').click()  # F87 ③ 後 3Y 不存在，1Y 在此情境同樣是停用的  # 點灰的 → 留下體重版說明
            page.wait_for_timeout(400)
            note_before = (
                page.locator(".range-note").inner_text()
                if page.locator(".range-note").count()
                else ""
            )
            st_w = chip_state(page)
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(800)
            st_f = chip_state(page)
            note_after = page.locator(".range-note").count()
            check(
                "review P1-1：切 metric 後 chips 重畫（3M/6M 由亮轉灰）、體重版說明不殘留",
                not st_w["3M"]["off"]
                and not st_w["6M"]["off"]
                and st_f["3M"]["off"]
                and st_f["6M"]["off"]
                and "體重" in note_before
                and note_after == 0,
                f"體重時 3M/6M={not st_w['3M']['off']}/{not st_w['6M']['off']} → "
                f"體脂時 off={st_f['3M']['off']}/{st_f['6M']['off']} note_殘留={note_after}",
            )
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(700)

            # review P2-2 回歸：記錄成功後說明要消失（不與 flash 打架）
            page.locator('.body-range button:has-text("1Y")').click()  # F87 ③ 後 3Y 不存在，1Y 在此情境同樣是停用的
            page.wait_for_timeout(400)
            had_note = page.locator(".range-note").count() == 1
            page.locator(".body-log-open").click()
            page.wait_for_selector(".body-log-modal", timeout=5000)
            page.locator('.body-log-modal input[placeholder^="體重"]').fill("101.1")
            page.locator('.body-log-modal button:has-text("✓ 記錄")').click()
            page.wait_for_timeout(1200)
            check(
                "review P2-2：記錄成功後 rangeNote 消失（不與 flash 並列打架）",
                had_note
                and page.locator(".range-note").count() == 0
                and page.locator(".body-saved").count() == 1,
                f"had_note={had_note} note_after={page.locator('.range-note').count()}",
            )
            # 還原到體脂頁籤——下一段 ⑤ 的前提是「選一段在體脂資料之前的區間會空」
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(800)

            # ⑤（自訂區間不受停用檔位限制）**已移除**：自訂區間隨 F87 ③ 消失，
            # 2026-08-01 Ryan 裁決（F119 選 B）確認不補回。這不是放寬斷言——被驗的 UI 不存在了。
            # ⑤ 想守住的「不該把使用者擋在資料之外」由 ③（點停用檔位只給說明、不擋畫面）與
            # 永遠可用的「全部」檔位共同承接，兩者都在本腳本裡驗著。

            # ⑦ 既有行為：切回體重 + 1M，圖表照畫、清單有資料
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(500)
            page.locator('.body-range button:has-text("3M")').click()
            page.wait_for_timeout(800)
            # F87 ⑤ 把折線圖換成 24 根長條圖，`svg polyline` 不存在了。
            # ⑦ 要的是「圖表照畫」這個行為，不是某種圖表型別——改驗長條有畫出來。
            bars = page.locator(".body-bars .body-bar").count()
            rows = page.locator(".bm-rows .bm-row").count()
            check(
                "⑦ 既有行為：切回體重 3M 仍正常出圖、清單有資料",
                bars > 0 and rows > 0,
                f"bars={bars} rows={rows}",
            )

            browser.close()

        # ⑥ 空 DB 的情況：另起一個乾淨 server 驗「不限制」
        port2 = safe_port()
        tmp2 = Path(tempfile.mkdtemp(prefix="liftlog-f58b-"))
        release2 = tmp2 / "release"
        release2.mkdir()
        proc2 = start_server(port2, tmp2 / "e2e.db", release2)
        base2 = f"http://127.0.0.1:{port2}"
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 390, "height": 900})
                page.goto(base2 + "/")
                page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
                page.reload()
                wait_home(page)
                page.locator(".bottom-nav .nav-item", has_text="體重").click()
                page.wait_for_selector(".screen.body", timeout=8000)
                page.wait_for_timeout(600)
                st0 = chip_state(page)
                check(
                    "⑥ 完全沒有紀錄時不啟用限制（沒有任何檔位被灰掉）",
                    all(not v["off"] for v in st0.values()),
                    f"{ {k: ('off' if v['off'] else 'ok') for k, v in st0.items()} }",
                )
                browser.close()
        finally:
            proc2.terminate()
            try:
                proc2.wait(timeout=10)
            except Exception:
                proc2.kill()
            shutil.rmtree(tmp2, ignore_errors=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n==== F58 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
