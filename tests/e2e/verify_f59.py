"""F59 動作表現頁：資料不足時停用超出範圍的區間檔位 E2E。
用法：PYTHONUTF8=1 uv run python tests/e2e/verify_f59.py
涵蓋 acceptance ①–⑦（F86 改版後翻新，見下方）。

**F86 改版帶來的取代**（F86 ⑩ 要求翻新這支；驗的目的不變，變的是手段）：
- 檔位從 1M/3M/6M/9M/1Y/2Y/3Y＋自訂 收成五顆（1M/3M/6M/1Y/全部）；
  **「自訂」由 F86 ③ 明文移除（D2 簽核）**，②「自訂不受限」一項隨之退役。
- DOM 換名：`.ex-range`→`.range-pills`、`.ex-chartcard`→`.bars-card`、`.ex-prs`→`.pr-cards`、
  `.ex-hist`→`.hist-list`；返回鍵→`.back-btn`。
- ⑤（切 metric 後說明就地消失）**退役**：F86 ⑤ 把折線圖換成「每次最佳組」長條圖，
  最重重量／總訓練量的 metric 切換整個不存在了。被驗的 UI 沒了，不是把斷言放寬。

**F59 ④ 的規則本身沒有被取代**（F86 ④ 明文要求保留），所以那條照驗——它現在會紅，
指出的是真的回歸，見 F121。

測資：動作 A 最早訓練 100 天前（→ 1M/3M/6M 可用、9M 以上灰）；動作 B 只有今天（→ 只有 1M 可用，
且初次進頁面就該直接載 1M，不能出現「被選中的那顆是灰的」）。
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
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_f67 import (  # noqa: E402
    read_version,
    wait_home,
)

REPO = Path(r"C:\Users\user\OneDrive\Desktop\SideProject\lift-log")
TOKEN = "f59-own-token"


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


def chip_state(page):
    return page.evaluate("""() => {
      const out = {};
      for (const b of document.querySelectorAll('.range-pills button')) {
        out[b.textContent.trim()] = { off: b.classList.contains('off'), on: b.classList.contains('on') };
      }
      return out;
    }""")


def log_set(base, ex_id, days_ago, weight):
    """在 days_ago 天前建一次訓練並記一組。"""
    d = (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")
    w = api(base, "POST", "/api/workouts", {"date": d})
    api(
        base,
        "POST",
        f"/api/workouts/{w['id']}/sets",
        {
            "client_uuid": f"f59-{uuid.uuid4().hex[:12]}",
            "exercise_id": ex_id,
            "set_number": 1,
            "weight_kg": weight,
            "reps": 5,
            "rpe": 7,
        },
    )


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f59_{port}.db"
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
        pool = [e for e in exs if not e.get("is_bodyweight")][:3]
        ex_a, ex_b, ex_c = pool[0], pool[1], pool[2]
        today = datetime.date.today()

        # 動作 A：100 天前起（100/60/30/10/2），動作 B：只有今天
        for i, wt in ((100, 60.0), (60, 62.5), (30, 65.0), (10, 67.5), (2, 70.0)):
            log_set(base, ex_a["id"], i, wt)
        log_set(base, ex_b["id"], 0, 40.0)
        # 動作 C：唯一一次訓練在 10 天前。與 B 的差別是**那一次不在今天**——
        # 自動退檔若把起始日算成「今天」，B 會僥倖通過而 C 會空掉（見下方 F121 那條）
        log_set(base, ex_c["id"], 10, 50.0)

        # ① first_session_date（全期，不受 from/to 影響）
        recent = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        hist_a = api(
            base, "GET", f"/api/exercises/{ex_a['id']}/history?from={recent}&to={today:%Y-%m-%d}"
        )
        hist_b = api(
            base, "GET", f"/api/exercises/{ex_b['id']}/history?from={recent}&to={today:%Y-%m-%d}"
        )
        empty_ex = [
            e for e in exs if e["id"] not in (ex_a["id"], ex_b["id"], ex_c["id"])
        ][0]
        hist_empty = api(
            base,
            "GET",
            f"/api/exercises/{empty_ex['id']}/history?from={recent}&to={today:%Y-%m-%d}",
        )
        want_a = (today - datetime.timedelta(days=100)).strftime("%Y-%m-%d")
        check(
            "① history 回 first_session_date（全期最早訓練日，查詢區間只框最近 7 天仍回 100 天前）",
            hist_a["first_session_date"] == want_a
            and hist_b["first_session_date"] == today.strftime("%Y-%m-%d")
            and hist_empty["first_session_date"] is None,
            f"A={hist_a['first_session_date']} B={hist_b['first_session_date']} "
            f"無紀錄={hist_empty['first_session_date']}",
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
                "⑦ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v60）",
                ver.startswith("v") and int(ver[1:]) >= 60 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            # 進動作表現（底部導覽「表現」→ 選部位 → 選動作；F76 換掉 emoji、F81 重建首頁）
            def open_detail(ex):
                # 動作表現頁與選動作頁都沒有底部導覽，且返回鍵在兩頁的形態不同
                # （F81／F86 各改過一次）。回首頁用 goto 最穩——這裡驗的是檔位規則，
                # 不是導覽路徑，沒必要把腳本綁在每次改版都會動的返回鍵上。
                if not page.locator(".bottom-nav").count():
                    page.goto(base + "/")
                    wait_home(page)
                page.locator(".bottom-nav").get_by_role("button", name="表現").click()
                page.wait_for_timeout(900)
                page.get_by_role("button", name=ex["muscle_group"]).first.click()
                page.wait_for_timeout(700)
                page.get_by_role("button", name=ex["name_zh"]).first.click()
                page.wait_for_selector(".screen.exercise-detail", timeout=8000)
                page.wait_for_timeout(700)

            open_detail(ex_a)

            # ② 動作 A（最早 100 天前）→ 1M/3M/6M 可用、9M 以上灰
            st = chip_state(page)
            # 檔位收成五顆（F86 ③）：9M/2Y/3Y/自訂 不存在了，規則本身不變——
            # 涵蓋得住資料的第一個檔位可用、再上去灰掉；「全部」永遠可用（它的定義就是資料全長）
            check(
                "② 動作 A（最早 100 天前）：1M/3M/6M 可用、1Y 灰、「全部」永遠可用",
                not st["1M"]["off"]
                and not st["3M"]["off"]
                and not st["6M"]["off"]
                and st["1Y"]["off"]
                and not st["全部"]["off"],
                f"{ {k: ('off' if v['off'] else 'ok') for k, v in st.items()} }",
            )

            # ③ 點停用的檔位 → 只顯示說明、不切區間
            on_before = [k for k, v in st.items() if v["on"]]
            page.locator('.range-pills button:has-text("1Y")').click()
            page.wait_for_timeout(500)
            note_txt = (
                page.locator(".range-note").inner_text()
                if page.locator(".range-note").count()
                else ""
            )
            on_after = [k for k, v in chip_state(page).items() if v["on"]]
            check(
                "③ 點停用檔位：顯示說明（含最早訓練日）、選取的區間不變",
                want_a in note_txt and on_before == on_after == ["3M"],
                f"note={note_txt!r} on {on_before}→{on_after}",
            )

            # ⑤（切 metric 後說明就地消失）**已退役**：F86 ⑤ 把折線圖換成「每次最佳組」長條圖，
            # 「最重重量／最重總訓練量」的切換整個不存在了。被驗的 UI 沒了，不是把斷言放寬。
            # ⑤ 想守的「說明不殘留」由下面 ⑥ 的切檔位路徑接手驗（切到可用檔位後說明要消失）。

            # ⑥ 既有行為：切可用檔位仍正常（圖表在、PR 卡在）
            page.locator('.range-pills button:has-text("6M")').click()
            page.wait_for_timeout(800)
            check(
                "⑥ 既有行為：切可用檔位正常（chip 選中、圖表與 PR 卡都在、說明不殘留）",
                page.locator(".range-pills button.on").inner_text().strip() == "6M"
                and page.locator(".bars-card").count() == 1
                and page.locator(".pr-cards").count() == 1
                and page.locator(".range-note").count() == 0,
                f"on={page.locator('.range-pills button.on').inner_text().strip()!r} "
                f"bars={page.locator('.bars-card').count()} prs={page.locator('.pr-cards').count()}",
            )

            # ④ 動作 B（只有今天）→ 進頁面就該是 1M（不能出現「被選中的那顆是灰的」）
            open_detail(ex_b)
            page.wait_for_timeout(300)
            st_b = chip_state(page)
            on_b = [k for k, v in st_b.items() if v["on"]]
            selected_is_off = any(v["on"] and v["off"] for v in st_b.values())
            # F86 ③ 加了「全部」檔位，它永遠可用 → longestAvailable() 的答案從 1M 變成「全部」。
            # 這與 2026-08-01 Ryan 對體重頁（F120 ②）的裁決一致：退檔就退到最完整的那一檔。
            # ④ 真正要守的不變式是**「不能出現被選中卻是灰的那顆」**，那條原封不動。
            check(
                "④ 動作 B（只有今天一次訓練）：初次進頁面自動退檔，且沒有「被選中的那顆是灰的」",
                on_b == ["全部"] and not selected_is_off and st_b["3M"]["off"],
                f"on={on_b} 被選中卻灰={selected_is_off} 3M_off={st_b['3M']['off']}",
            )

            # F121：退檔之後**資料要還在**。這是 ④ 的另一半——退檔的目的是「別給一張空圖」，
            # 退完卻把資料濾光就是把問題換了個樣子。動作 C 的唯一一次訓練在 10 天前，
            # 若起始日被算成「今天」，這裡會是 0 筆。
            open_detail(ex_c)
            page.wait_for_timeout(400)
            on_c = page.locator(".range-pills button.on").inner_text().strip()
            hist_c = page.locator(".hist-list .hist-card").count()
            bars_c = page.locator(".bars-card .bar-col").count()
            check(
                "④/F121 動作 C（唯一一次訓練在 10 天前）：退檔後那一次仍看得到（不是空清單）",
                hist_c == 1 and bars_c == 1,
                f"on={on_c!r} 歷來卡={hist_c} 長條={bars_c}",
            )

            # review P2-2 回歸：進「只有今天一次訓練」的動作時，**不該**多發一次 history 請求
            # （退檔改成純前端過濾）；且 1M 的資料仍正確顯示
            reqs = []
            page.on("request", lambda r: reqs.append(r.url) if "/history" in r.url else None)
            reqs.clear()
            open_detail(ex_b)
            page.wait_for_timeout(400)
            on_after = page.locator(".range-pills button.on").inner_text().strip()
            sessions_shown = page.locator(".hist-list .hist-card").count()
            check(
                "review P2-2：初次退檔改為純前端過濾（只發 1 次 history 請求），且退檔後內容正確",
                len(reqs) == 1 and on_after == "全部" and sessions_shown == 1,
                f"history 請求數={len(reqs)} on={on_after!r} 歷來列數={sessions_shown}",
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

    print("\n==== F59 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
