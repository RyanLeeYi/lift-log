"""F59 動作表現頁：資料不足時停用超出範圍的區間檔位 E2E。
用法：PYTHONUTF8=1 uv run python verify_f59_own.py
涵蓋 acceptance ①–⑦。

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
      for (const b of document.querySelectorAll('.ex-range button')) {
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
        pool = [e for e in exs if not e.get("is_bodyweight")][:2]
        ex_a, ex_b = pool[0], pool[1]
        today = datetime.date.today()

        # 動作 A：100 天前起（100/60/30/10/2），動作 B：只有今天
        for i, wt in ((100, 60.0), (60, 62.5), (30, 65.0), (10, 67.5), (2, 70.0)):
            log_set(base, ex_a["id"], i, wt)
        log_set(base, ex_b["id"], 0, 40.0)

        # ① first_session_date（全期，不受 from/to 影響）
        recent = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        hist_a = api(
            base, "GET", f"/api/exercises/{ex_a['id']}/history?from={recent}&to={today:%Y-%m-%d}"
        )
        hist_b = api(
            base, "GET", f"/api/exercises/{ex_b['id']}/history?from={recent}&to={today:%Y-%m-%d}"
        )
        empty_ex = [e for e in exs if e["id"] not in (ex_a["id"], ex_b["id"])][0]
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

            # 進動作表現（首頁 → 📈 動作表現 → 選部位 → 選動作）
            page.locator('.btn:has-text("📈 動作表現")').click()
            page.wait_for_timeout(700)
            page.locator(".chips .chip", has_text=ex_a["muscle_group"]).first.click()
            page.wait_for_timeout(500)
            page.locator(".exercise-item", has_text=ex_a["name_zh"]).first.click()
            page.wait_for_selector(".screen.exercise-detail", timeout=8000)
            page.wait_for_timeout(700)

            # ② 動作 A（最早 100 天前）→ 1M/3M/6M 可用、9M 以上灰
            st = chip_state(page)
            check(
                "② 動作 A（最早 100 天前）：1M/3M/6M 可用、9M 以上灰、自訂不受限",
                not st["1M"]["off"]
                and not st["3M"]["off"]
                and not st["6M"]["off"]
                and st["9M"]["off"]
                and st["1Y"]["off"]
                and st["3Y"]["off"]
                and not st["自訂"]["off"],
                f"{ {k: ('off' if v['off'] else 'ok') for k, v in st.items()} }",
            )

            # ③ 點停用的檔位 → 只顯示說明、不切區間
            on_before = [k for k, v in st.items() if v["on"]]
            page.locator('.ex-range button:has-text("1Y")').click()
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

            # ⑤ 切 metric（最重重量／最重總訓練量）→ 說明就地消失
            page.locator(".ex-metric button").nth(1).click()
            page.wait_for_timeout(400)
            check(
                "⑤ 切 metric 後說明就地消失（F36 的就地更新不變）",
                page.locator(".range-note").count() == 0
                and page.locator(".ex-metric button.on").count() == 1,
                f"note={page.locator('.range-note').count()}",
            )

            # ⑥ 既有行為：切可用檔位仍正常（圖表在、PR 卡在）
            page.locator('.ex-range button:has-text("6M")').click()
            page.wait_for_timeout(800)
            check(
                "⑥ 既有行為：切可用檔位正常（chip 選中、圖表與 PR 卡都在）",
                page.locator(".ex-range button.on").inner_text().strip() == "6M"
                and page.locator(".ex-chartcard").count() == 1
                and page.locator(".ex-prs").count() == 1,
                f"on={page.locator('.ex-range button.on').inner_text().strip()!r}",
            )

            # ④ 動作 B（只有今天）→ 進頁面就該是 1M（不能出現「被選中的那顆是灰的」）
            page.locator('.screen.exercise-detail button:has-text("←")').first.click()
            page.wait_for_timeout(700)
            if page.locator(".chips .chip", has_text=ex_b["muscle_group"]).count():
                page.locator(".chips .chip", has_text=ex_b["muscle_group"]).first.click()
                page.wait_for_timeout(500)
            page.locator(".exercise-item", has_text=ex_b["name_zh"]).first.click()
            page.wait_for_selector(".screen.exercise-detail", timeout=8000)
            page.wait_for_timeout(900)
            st_b = chip_state(page)
            on_b = [k for k, v in st_b.items() if v["on"]]
            selected_is_off = any(v["on"] and v["off"] for v in st_b.values())
            check(
                "④ 動作 B（只有今天一次訓練）：初次進頁面就載 1M，且沒有「被選中的那顆是灰的」",
                on_b == ["1M"] and not selected_is_off and st_b["3M"]["off"],
                f"on={on_b} 被選中卻灰={selected_is_off} 3M_off={st_b['3M']['off']}",
            )

            # review P2-2 回歸：進「只有今天一次訓練」的動作時，**不該**多發一次 history 請求
            # （退檔改成純前端過濾）；且 1M 的資料仍正確顯示
            reqs = []
            page.on("request", lambda r: reqs.append(r.url) if "/history" in r.url else None)
            page.locator('.screen.exercise-detail button:has-text("←")').first.click()
            page.wait_for_timeout(700)
            if page.locator(".chips .chip", has_text=ex_b["muscle_group"]).count():
                page.locator(".chips .chip", has_text=ex_b["muscle_group"]).first.click()
                page.wait_for_timeout(500)
            reqs.clear()
            page.locator(".exercise-item", has_text=ex_b["name_zh"]).first.click()
            page.wait_for_selector(".screen.exercise-detail", timeout=8000)
            page.wait_for_timeout(1000)
            on_after = page.locator(".ex-range button.on").inner_text().strip()
            sessions_shown = page.locator(".ex-hist .hist-session, .ex-hist .hist-row").count()
            check(
                "review P2-2：初次退檔改為純前端過濾（只發 1 次 history 請求），且 1M 內容正確",
                len(reqs) == 1 and on_after == "1M",
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
