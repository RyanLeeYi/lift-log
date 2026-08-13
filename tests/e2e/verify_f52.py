"""F52 加動作視窗高度穩定＋捲軸樣式與畫面清單去重 E2E。
用法：PYTHONUTF8=1 uv run python verify_f52_own.py
涵蓋 acceptance ①–⑤。
"""

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
    start_from_home,
    wait_home,
)

REPO = Path(__file__).resolve().parents[2]
TOKEN = "f52-own-token"


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


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f52_{port}.db"
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
        pool = [e for e in exs if not e.get("is_bodyweight")][:8]
        api(
            base,
            "POST",
            "/api/templates",
            {
                "name": "F52 課表",
                "exercises": [
                    {"exercise_id": ex["id"], "position": i + 1, "default_sets": 3}
                    for i, ex in enumerate(pool)
                ],
            },
        )

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 667})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            wait_home(page)

            # ⑤ 版本
            # F81 把版號搬進設定畫面；read_version() 自己會開設定再回首頁。
            ver = read_version(page)
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            check(
                "⑤ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v53）",
                ver.startswith("v") and int(ver[1:]) >= 53 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            # ③ marker class：四個畫面都掛 .fills，CSS 只認它
            fills = {}
            page.locator(".bottom-nav .nav-item", has_text="課表").click()
            page.wait_for_selector(".screen.templates", timeout=8000)
            fills["templates"] = page.locator(".screen.templates.fills").count() == 1
            page.locator(".tpl-row", has_text="F52 課表").locator("button", has_text="編輯").click()
            page.wait_for_selector(".screen.template-edit", timeout=8000)
            fills["templateEdit"] = page.locator(".screen.template-edit.fills").count() == 1
            edit_h = page.eval_on_selector(
                ".screen.template-edit", "e => getComputedStyle(e).height"
            )

            # ② 細捲軸樣式（與其他清單同一組共用規則）
            style = page.eval_on_selector(
                ".tpl-items.scrollable",
                """e => {
              const s = getComputedStyle(e);
              return { sw: s.scrollbarWidth, sc: s.scrollbarColor, oy: s.overflowY,
                       touch: s.webkitOverflowScrolling || "" };
            }""",
            )
            # 回傳值用不到，但選擇器不存在時 eval_on_selector 會拋——這行本身就是存在性斷言
            page.eval_on_selector(".tpl-items.scrollable", "e => 1")
            check(
                "② 編輯頁清單套到細捲軸共用樣式（thin ＋ scrollbar-color ＋ overflow-y: auto）",
                style["sw"] == "thin" and style["oy"] == "auto" and style["sc"] not in ("", "auto"),
                f"{style}",
            )

            # ① 加動作視窗：搜尋篩選前後 視窗 top/高度 與 搜尋框 y 不變
            page.locator('.screen.template-edit button:has-text("＋ 加動作")').click()
            page.wait_for_selector(".tpl-add-modal", timeout=5000)
            page.wait_for_timeout(300)
            m_before = page.locator(".tpl-add-modal").bounding_box()
            s_before = page.locator('.tpl-add-modal input[type="search"]').bounding_box()
            n_before = page.locator(".tpl-add-modal .exercise-list .exercise-item").count()
            page.locator('.tpl-add-modal input[type="search"]').type("bench", delay=40)
            page.wait_for_timeout(900)
            m_after = page.locator(".tpl-add-modal").bounding_box()
            s_after = page.locator('.tpl-add-modal input[type="search"]').bounding_box()
            n_after = page.locator(".tpl-add-modal .exercise-list .exercise-item").count()
            check(
                "① 加動作視窗：搜尋篩選結果變少時，視窗 top／高度與搜尋框位置皆不位移",
                n_after < n_before
                and abs(m_after["y"] - m_before["y"]) <= 1
                and abs(m_after["height"] - m_before["height"]) <= 1
                and abs(s_after["y"] - s_before["y"]) <= 1,
                f"items {n_before}→{n_after} modal_y {round(m_before['y'])}→{round(m_after['y'])} "
                f"modal_h {round(m_before['height'])}→{round(m_after['height'])} "
                f"search_y {round(s_before['y'])}→{round(s_after['y'])}",
            )

            # review P2-2 回歸：加動作視窗的搜尋框要吃到深色樣式與 ≥16px 字
            # （字 <16px 會讓 iOS Safari focus 時自動放大整頁）
            si = page.eval_on_selector(
                '.tpl-add-modal input[type="search"]',
                """e => {
              const s = getComputedStyle(e);
              return { bg: s.backgroundColor, fs: parseFloat(s.fontSize),
                       h: Math.round(e.getBoundingClientRect().height), br: s.borderRadius };
            }""",
            )
            check(
                "review P2-2：加動作視窗搜尋框有深色樣式、字 ≥16px、觸控高度足夠",
                si["bg"] != "rgb(255, 255, 255)" and si["fs"] >= 16 and si["h"] >= 40,
                f"{si}",
            )

            # review P2-1 回歸：極矮／橫向視窗不得出現雙層捲動，「確定加入」要完整在視窗內
            short = {}
            for w, h in ((320, 420), (844, 390)):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(350)
                geo = page.eval_on_selector(
                    ".tpl-add-modal",
                    """e => {
                  const r = e.getBoundingClientRect();
                  const btn = e.querySelector('.modal-actions .btn');
                  const br = btn.getBoundingClientRect();
                  // need/have/kids 是刻意留下的診斷欄位：F117 就是靠它一眼看出「差 10px、
                  // 而且是哪幾個子節點吃掉的」，否則只知道「有捲動」得再猜一輪
                  return { self_scrolls: e.scrollHeight > e.clientHeight + 2,
                           need: e.scrollHeight, have: e.clientHeight,
                           kids: [...e.children].map(c => c.className + ':' +
                                 Math.round(c.getBoundingClientRect().height)),
                           btn_inside: br.bottom <= r.bottom + 1 };
                }""",
                )
                short[f"{w}x{h}"] = geo
            check(
                "review P2-1：320×420／橫放 844×390 無雙層捲動，「確定加入」完整在視窗內",
                all((not g["self_scrolls"]) and g["btn_inside"] for g in short.values()),
                f"{short}",
            )
            page.set_viewport_size({"width": 390, "height": 667})
            page.wait_for_timeout(300)

            # ④ 既有行為：F21 單選＋確定 仍可加入；F22 部位 chips 仍在
            chips_n = page.locator(".tpl-add-modal .chips .chip").count()
            page.locator('.tpl-add-modal input[type="search"]').fill("")
            page.wait_for_timeout(700)
            items_before = page.locator(".tpl-item").count()
            page.locator(".tpl-add-modal .exercise-list .exercise-item").first.click()
            page.wait_for_timeout(200)
            confirm = page.locator('.tpl-add-modal button:has-text("確定加入")')
            confirm.click()
            page.wait_for_timeout(500)
            check(
                "④ 既有行為：部位 chips 在、單選＋確定加入仍正常（F21／F22）",
                chips_n >= 2
                and page.locator(".tpl-item").count() == items_before + 1
                and page.locator(".tpl-add-modal").count() == 0,
                f"chips={chips_n} items {items_before}→{page.locator('.tpl-item').count()}",
            )

            # ③ 續：矮螢幕 media query 仍生效（marker class 版）
            page.set_viewport_size({"width": 844, "height": 390})
            page.wait_for_timeout(300)
            short_h = page.eval_on_selector(
                ".screen.template-edit", "e => getComputedStyle(e).height"
            )
            page.set_viewport_size({"width": 390, "height": 667})
            page.wait_for_timeout(300)
            page.locator('button:has-text("← 課表列表")').click()
            page.wait_for_timeout(400)
            if page.locator(".modal-overlay").count() > 0:
                page.locator('.modal button:has-text("捨棄並離開")').first.click()
                page.wait_for_timeout(300)
            page.wait_for_selector(".screen.templates", timeout=8000)
            page.locator(".screen.templates button", has_text="← 回首頁").click()
            wait_home(page)
            start_from_home(page)
            page.wait_for_selector(".tpl-choice-list", timeout=8000)
            fills["templateSelect"] = page.locator(".screen.template-select.fills").count() == 1
            page.locator(".tpl-choice", has_text="F52 課表").click()
            page.wait_for_selector(".screen.picker", timeout=8000)
            fills["picker"] = page.locator(".screen.picker.fills").count() == 1
            # 判定方式：釘視窗高時 computed height 應等於 viewport − .app 上下 padding（28px）；
            # 矮螢幕回退成 auto 時是「內容高度」，不會等於那個值（實測 424 > 362＝內容比可視區高）
            pinned_667 = abs(float(edit_h.rstrip("px")) - (667 - 28)) <= 2
            fell_back_390 = abs(float(short_h.rstrip("px")) - (390 - 28)) > 2
            check(
                "③ 四個畫面皆掛 .fills marker；667 高時釘視窗高、390 高時回退成內容高度",
                all(fills.values()) and pinned_667 and fell_back_390,
                f"fills={fills} edit_h(667)={edit_h}（期望≈639）pinned={pinned_667} "
                f"edit_h(390 高)={short_h}（釘死會是 362）fell_back={fell_back_390}",
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

    print("\n==== F52 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
