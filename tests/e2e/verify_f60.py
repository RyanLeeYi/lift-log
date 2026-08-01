"""F60 用課表批次新增：每列摺疊成摘要、點開才微調 E2E。
用法：PYTHONUTF8=1 uv run python verify_f60_own.py
涵蓋 acceptance ①–⑦。

注意：涉及捲動位置的斷言一律用 dispatchEvent 觸發點擊——真 click() 會 auto-scroll，
會把「捲動位置有沒有被保留」的證據抹掉（F51 的教訓）。
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

from verify_f67 import (  # noqa: E402
    read_version,
    wait_home,
)

REPO = Path(r"C:\Users\user\OneDrive\Desktop\SideProject\lift-log")
TOKEN = "f60-own-token"

ROWS = """() => [...document.querySelectorAll('.cal-batch-row')].map(r => ({
  name: r.querySelector('.ex-name').textContent.trim(),
  summary: r.querySelector('.batch-summary').textContent.trim(),
  // F76 把幾何字元（▸ / ▾）換成向量圖示，textContent 從此是空字串。
  // 條文要的是「指示符會反映展開狀態」，不是某個字元——改記 svg 的 path，
  // 收合態與展開態**不同**即可，不寫死任何座標。
  caret: r.querySelector('.batch-caret').textContent.trim(),
  caret_svg: r.querySelectorAll('.batch-caret svg').length,
  caret_d: (r.querySelector('.batch-caret path') || {}).getAttribute
    ? r.querySelector('.batch-caret path').getAttribute('d') : null,
  open: r.classList.contains('open'),
  off: r.classList.contains('off'),
  checked: r.querySelector('input[type=checkbox]').checked,
  steppers: r.querySelectorAll('.stepper').length,
  sets_ctl: r.querySelectorAll('.batch-sets').length,
  h: Math.round(r.getBoundingClientRect().height),
}))"""

GEO = """() => {
  const list = document.querySelector('.cal-batch-list');
  const modal = document.querySelector('.cal-add-modal.batch');
  const acts = document.querySelector('.cal-add-modal.batch .modal-actions');
  const lb = list.getBoundingClientRect(), mb = modal.getBoundingClientRect(),
        ab = acts.getBoundingClientRect();
  const rows = [...document.querySelectorAll('.cal-batch-row')];
  return {
    fully_visible: rows.filter(r => {
      const rb = r.getBoundingClientRect();
      return rb.top >= lb.top - 1 && rb.bottom <= lb.bottom + 1;
    }).length,
    rowCount: rows.length,
    scrollable: list.scrollHeight > list.clientHeight + 1,
    list_h: Math.round(lb.height),
    content_h: list.scrollHeight,
    // 溢出／重疊：清單不得超出 modal，也不得疊住底部按鈕列
    overflow_modal: Math.round(Math.max(0, lb.bottom - mb.bottom)),
    over_actions: Math.round(Math.max(0, lb.bottom - ab.top)),
    modal_overflow_vp: Math.round(Math.max(0, mb.bottom - window.innerHeight)),
  };
}"""


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


def tap(page, selector, nth=0):
    """dispatchEvent 點擊（不 auto-scroll）。"""
    page.evaluate(
        """([sel, i]) => {
             const e = document.querySelectorAll(sel)[i];
             e.dispatchEvent(new MouseEvent('click', { bubbles: true }));
           }""",
        [selector, nth],
    )


def open_batch(page, base, tpl_name):
    # F115 同型：原本用 today-3，月初跑就滑到上個月、那格根本沒被畫出來（日曆一次只畫一個月）。
    # 改用**本月 1 號**——它必定存在、必定不是未來日，且與今天是幾號無關。
    today_ = datetime.date.today()
    past = today_.replace(day=1).strftime("%Y-%m-%d")
    page.locator(".bottom-nav .nav-item", has_text="日曆").click()
    page.wait_for_selector(".calendar", timeout=8000)
    page.locator(f'.cal-day[aria-label="{past}"]').click()
    page.wait_for_timeout(400)
    page.locator(".cal-add-toggle").click()
    page.wait_for_selector(".modal-overlay", timeout=5000)
    page.locator(".cal-add-mode button", has_text="用課表").click()
    page.wait_for_timeout(400)
    page.locator(".cal-tpl-item", has_text=tpl_name).first.click()
    page.wait_for_selector(".cal-batch-row", timeout=8000)
    page.wait_for_timeout(500)


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f60_{port}.db"
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

        exs = api(base, "GET", "/api/exercises")
        bw = next(e for e in exs if e.get("is_bodyweight"))
        norm = [e for e in exs if not e.get("is_bodyweight")][:3]
        pool = [bw] + norm  # 第一列刻意是自體重動作（摘要要顯示「負重」）
        SETS = [3, 2, 1, 4]  # 每列不同 default_sets，才驗得出摘要對應各自的列
        api(
            base,
            "POST",
            "/api/templates",
            {
                "name": "排版檢查課表",
                "exercises": [
                    {"exercise_id": e["id"], "position": i + 1, "default_sets": SETS[i]}
                    for i, e in enumerate(pool)
                ],
            },
        )
        names = [e["name_zh"] for e in pool]

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
                "⑦ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v61）",
                ver.startswith("v") and int(ver[1:]) >= 61 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            open_batch(page, base, "排版檢查課表")

            # ①⑥ 摺疊態的一行摘要＋F47 預設值（無上次紀錄 → 20kg×8；自體重 0kg；組數＝default_sets）
            rows = page.evaluate(ROWS)
            want = [f"負重 0kg × 8 × {SETS[0]} 組"] + [
                f"20kg × 8 × {SETS[i]} 組" for i in (1, 2, 3)
            ]
            collapsed_caret = rows[0]["caret_d"]  # ② 要拿它比對展開態的指示符有沒有變
            check(
                "①⑥ 每列預設收合成一行摘要（自體重顯示「負重」）、摘要＝F47 預設值×各自 default_sets、無 stepper",
                [r["summary"] for r in rows] == want
                and all(r["steppers"] == 0 and r["sets_ctl"] == 0 for r in rows)
                and all(not r["open"] and r["caret_svg"] == 1 and r["caret_d"] for r in rows)
                and [r["name"] for r in rows] == names,
                f"summaries={[r['summary'] for r in rows]} 期望={want}",
            )

            # ⑤ 收合時 4 列全數完整可見、不需捲動、不溢出、不疊住按鈕（兩種手機高度）
            geo = {}
            for w, h in ((390, 844), (360, 640)):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(350)
                geo[f"{w}x{h}"] = page.evaluate(GEO)
                page.screenshot(path=str(Path(tempfile.gettempdir()) / f"f60_{w}x{h}.png"))
            check(
                "⑤ 4 列收合時在 390×844 與 360×640 全數完整可見、不需捲動、不溢出、不疊住底部按鈕",
                all(
                    g["fully_visible"] == 4
                    and g["rowCount"] == 4
                    and not g["scrollable"]
                    and g["overflow_modal"] <= 1
                    and g["over_actions"] <= 1
                    and g["modal_overflow_vp"] <= 1
                    for g in geo.values()
                ),
                json.dumps(geo, ensure_ascii=False),
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(300)

            # ② 點標頭展開／收合；可同時展開多列
            tap(page, ".cal-batch-row .batch-head", 1)
            page.wait_for_timeout(250)
            after_one = page.evaluate(ROWS)
            tap(page, ".cal-batch-row .batch-head", 3)
            page.wait_for_timeout(250)
            after_two = page.evaluate(ROWS)
            tap(page, ".cal-batch-row .batch-head", 1)
            page.wait_for_timeout(250)
            after_close = page.evaluate(ROWS)
            check(
                "② 點標頭展開出 KG／REPS steppers＋組數控制，再點收合；可同時展開多列（列 2 與列 4）",
                after_one[1]["open"]
                and after_one[1]["steppers"] == 2
                and after_one[1]["sets_ctl"] == 1
                and after_one[1]["caret_d"] != collapsed_caret  # 指示符跟著翻向（F76 起是向量圖示）
                and not after_one[3]["open"]
                and after_two[1]["open"]
                and after_two[3]["open"]
                and not after_close[1]["open"]
                and after_close[1]["steppers"] == 0
                and after_close[3]["open"],
                f"one={[r['open'] for r in after_one]} two={[r['open'] for r in after_two]} "
                f"close={[r['open'] for r in after_two and after_close]}",
            )

            # ③ 點勾選框只切勾選，不展開／收合（列 3 原為收合、列 4 原為展開）
            tap(page, ".cal-batch-row input[type=checkbox]", 2)
            page.wait_for_timeout(250)
            st3 = page.evaluate(ROWS)
            tap(page, ".cal-batch-row input[type=checkbox]", 3)
            page.wait_for_timeout(250)
            st4 = page.evaluate(ROWS)
            check(
                "③ 點勾選框只切勾選態（.off 生效），收合列不展開、展開列不收合",
                st3[2]["checked"] is False
                and st3[2]["off"]
                and not st3[2]["open"]
                and st4[3]["checked"] is False
                and st4[3]["off"]
                and st4[3]["open"],
                f"列3 checked={st3[2]['checked']} open={st3[2]['open']} / "
                f"列4 checked={st4[3]['checked']} open={st4[3]['open']}",
            )
            # 復原勾選
            tap(page, ".cal-batch-row input[type=checkbox]", 2)
            tap(page, ".cal-batch-row input[type=checkbox]", 3)
            page.wait_for_timeout(250)

            # ⑥ 全部取消勾選 → 「全部記錄」停用且反映在 DOM
            for i in range(4):
                tap(page, ".cal-batch-row input[type=checkbox]", i)
            page.wait_for_timeout(300)
            dis_all_off = page.evaluate(
                "() => document.querySelector('.cal-batch-log').hasAttribute('disabled')"
            )
            tap(page, ".cal-batch-row input[type=checkbox]", 0)
            page.wait_for_timeout(250)
            dis_one_on = page.evaluate(
                "() => document.querySelector('.cal-batch-log').hasAttribute('disabled')"
            )
            check(
                "⑥ 全部取消勾選 → 「全部記錄」disabled 反映在 DOM；勾回一列即解除",
                dis_all_off is True and dis_one_on is False,
                f"全不勾 disabled={dis_all_off} 勾一列 disabled={dis_one_on}",
            )
            for i in (1, 2, 3):
                tap(page, ".cal-batch-row input[type=checkbox]", i)
            page.wait_for_timeout(250)

            # ④ stepper 調整 → 摘要即時更新、該列不收合、其他列展開態與清單捲動位置都保留
            for i in range(4):  # 全展開造出可捲動內容
                st = page.evaluate(ROWS)
                if not st[i]["open"]:
                    tap(page, ".cal-batch-row .batch-head", i)
                    page.wait_for_timeout(180)
            page.evaluate(
                "() => { const l = document.querySelector('.cal-batch-list'); "
                "l.scrollTop = Math.round(l.scrollHeight * 0.45); }"
            )
            page.wait_for_timeout(250)
            before_scroll = page.evaluate(
                "() => document.querySelector('.cal-batch-list').scrollTop"
            )
            before_open = [r["open"] for r in page.evaluate(ROWS)]
            assert before_scroll > 0, f"前提不成立：清單沒捲動（scrollTop={before_scroll}）"
            # 列 2 的 KG +2.5 一次、REPS +1 一次、組數 +1 一次
            page.evaluate("""() => {
              const r = document.querySelectorAll('.cal-batch-row')[1];
              const st = r.querySelectorAll('.stepper');
              st[0].querySelectorAll('.pair .btn')[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
              st[1].querySelectorAll('.pair .btn')[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
              r.querySelectorAll('.batch-sets .btn')[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
            }""")
            page.wait_for_timeout(300)
            after = page.evaluate(ROWS)
            after_scroll = page.evaluate(
                "() => document.querySelector('.cal-batch-list').scrollTop"
            )
            check(
                "④ stepper／組數調整 → 摘要就地更新（22.5kg × 9 × 3 組）、該列不收合、"
                "其他列展開態與清單捲動位置都保留",
                after[1]["summary"] == f"22.5kg × 9 × {SETS[1] + 1} 組"
                and after[1]["open"]
                and [r["open"] for r in after] == before_open
                and abs(after_scroll - before_scroll) <= 1
                and after[0]["summary"] == want[0],  # 別列的摘要沒被連動改掉
                f"summary={after[1]['summary']!r} scroll {before_scroll}->{after_scroll} "
                f"open {before_open}->{[r['open'] for r in after]}",
            )

            # ⑥ 「取消」先退回課表清單（不直接關）
            page.locator(".cal-add-modal.batch .modal-cancel").click()
            page.wait_for_timeout(400)
            back_to_list = (
                page.locator(".cal-tpl-list").count() == 1
                and page.locator(".cal-batch-row").count() == 0
            )
            check(
                "⑥ 「取消」退回課表清單而非直接關閉（F44 退一步範式）",
                back_to_list,
                f"tpl_list={page.locator('.cal-tpl-list').count()}",
            )

            # ⑥ 全部記錄：取消勾選一列後送出，只寫勾選的列、每列組數各自正確
            page.locator(".cal-tpl-item", has_text="排版檢查課表").first.click()
            page.wait_for_selector(".cal-batch-row", timeout=8000)
            page.wait_for_timeout(500)
            fresh = page.evaluate(ROWS)
            tap(page, ".cal-batch-row input[type=checkbox]", 2)  # 取消第 3 列
            page.wait_for_timeout(250)
            page.locator(".cal-batch-log").click()
            page.wait_for_timeout(1800)
            past = (datetime.date.today() - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
            detail = api(base, "GET", f"/api/workouts?from={past}&to={past}")
            wid = detail[0]["id"]
            sets = api(base, "GET", f"/api/workouts/{wid}")["sets"]
            per = {}
            for s in sets:
                per[s["exercise_id"]] = per.get(s["exercise_id"], 0) + 1
            want_per = {pool[0]["id"]: SETS[0], pool[1]["id"]: SETS[1], pool[3]["id"]: SETS[3]}
            weights_ok = all(
                (s["weight_kg"] == 0 if s["exercise_id"] == pool[0]["id"] else s["weight_kg"] == 20)
                and s["reps"] == 8
                and s["rpe"] == 6
                for s in sets
            )
            check(
                "⑥ 重開批次為全收合預設；全部記錄只寫勾選的列、組數／重量／reps／rpe 皆依摘要值",
                all(not r["open"] for r in fresh)
                and per == want_per
                and weights_ok
                and page.locator(".cal-batch-row").count() == 0,
                f"每動作組數={per} 期望={want_per} weights_ok={weights_ok} "
                f"fresh_open={[r['open'] for r in fresh]}",
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

    print("\n==== F60 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
