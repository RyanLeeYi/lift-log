"""F51 編輯課表頁動作清單改填滿剩餘空間 E2E。
用法：PYTHONUTF8=1 uv run python verify_f51_own.py
涵蓋 acceptance ①–⑤，外加一條「診斷」：F21 的 itemsScrollTop 是否真的有效（只回報、不修）。
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

from verify_f67 import (  # noqa: E402
    read_version,
    wait_home,
)

REPO = Path(r"C:\Users\user\OneDrive\Desktop\SideProject\lift-log")
TOKEN = "f51-own-token"


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


def box_h(page, selector):
    b = page.locator(selector).first.bounding_box()
    return round(b["height"]) if b else None


def fully_visible(page, selector):
    b = page.locator(selector).first.bounding_box()
    if b is None:
        return False
    return b["y"] >= 0 and b["y"] + b["height"] <= page.viewport_size["height"] + 1


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f51_{port}.db"
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
    notes = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    try:
        if not wait_up(base + "/"):
            print("SERVER FAILED")
            return 1

        exs = api(base, "GET", "/api/exercises")
        pool = [e for e in exs if not e.get("is_bodyweight")][:8]
        # 大課表（8 動作 → 必定溢出）與小課表（2 動作 → 門檻下）
        api(
            base,
            "POST",
            "/api/templates",
            {
                "name": "F51 大課表",
                "exercises": [
                    {"exercise_id": ex["id"], "position": i + 1, "default_sets": 3}
                    for i, ex in enumerate(pool)
                ],
            },
        )
        api(
            base,
            "POST",
            "/api/templates",
            {
                "name": "F51 三動作課表",
                "exercises": [
                    {"exercise_id": ex["id"], "position": i + 1, "default_sets": 3}
                    for i, ex in enumerate(pool[:3])
                ],
            },
        )
        api(
            base,
            "POST",
            "/api/templates",
            {
                "name": "F51 小課表",
                "exercises": [
                    {"exercise_id": ex["id"], "position": i + 1, "default_sets": 3}
                    for i, ex in enumerate(pool[:2])
                ],
            },
        )

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            wait_home(page)

            # ⑤ 版本
            # F81 把版號搬進設定畫面；read_version() 自己會開設定再回首頁。
            ver = read_version(page)
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            check(
                "⑤ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v52）",
                ver.startswith("v") and int(ver[1:]) >= 52 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            def open_editor(name):
                if page.locator(".screen.templates").count() == 0:
                    page.locator(".bottom-nav .nav-item", has_text="課表").click()
                    page.wait_for_selector(".screen.templates", timeout=8000)
                page.locator(".tpl-row", has_text=name).locator("button", has_text="編輯").click()
                page.wait_for_selector(".screen.template-edit", timeout=8000)

            def back_to_list():
                page.locator('.screen.template-edit button:has-text("← 課表列表")').click()
                page.wait_for_selector(".screen.templates", timeout=8000)

            # ① / ③ 大課表：三種高度下清單高度不同、三顆鈕都完整可見
            open_editor("F51 大課表")
            heights, btns = {}, {}
            for h in (844, 667, 560):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(300)
                heights[h] = box_h(page, ".tpl-items.scrollable")
                btns[h] = (
                    fully_visible(page, '.screen.template-edit button:has-text("＋ 加動作")')
                    and fully_visible(page, 'button:has-text("儲存課表")')
                    and fully_visible(page, 'button:has-text("← 課表列表")')
                )
            check(
                "① / ③ 編輯課表頁：動作清單高度隨螢幕高度變化，「＋加動作」「儲存課表」「←課表列表」皆完整可見",
                heights[844] > heights[667] > heights[560] and all(btns.values()),
                f"heights={heights} buttons_ok={btns}",
            )
            check(
                "③ 清單在 390×560 仍有下限（不塌成 0）", heights[560] >= 100, f"h560={heights[560]}"
            )

            # 診斷（不在 acceptance）：F21 的 itemsScrollTop 是否真的有效
            page.set_viewport_size({"width": 390, "height": 560})
            page.wait_for_timeout(300)
            ibox = page.locator(".tpl-items.scrollable").bounding_box()
            page.mouse.move(ibox["x"] + ibox["width"] / 2, ibox["y"] + ibox["height"] / 2)
            page.mouse.wheel(0, 120)
            page.wait_for_timeout(400)
            scroll_before = page.eval_on_selector(".tpl-items.scrollable", "e => e.scrollTop")
            # 觸發整頁重繪：改某列的組數（stepper ＋）——會 rerender
            page.locator('.tpl-item-sets button:has-text("＋")').first.evaluate(
                "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
            )
            page.wait_for_timeout(500)
            scroll_after = page.eval_on_selector(".tpl-items.scrollable", "e => e.scrollTop")
            notes.append(
                f"[診斷] F21 itemsScrollFix：重繪前 scrollTop={scroll_before}、重繪後={scroll_after} → "
                + (
                    "有效（位置保留）"
                    if scroll_before > 0 and abs(scroll_after - scroll_before) <= 2
                    else "**失效**（與 F48 首版同一個 onscroll 污染問題）"
                )
            )

            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)

            # ④ 既有行為抽驗：組數改動後可儲存（F21）、加動作視窗可開（F25）
            page.locator('.screen.template-edit button:has-text("＋ 加動作")').click()
            page.wait_for_timeout(500)
            panel_ok = page.locator(".modal-overlay").count() >= 1
            page.locator('.modal button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator('button:has-text("儲存課表")').click()
            page.wait_for_selector(".screen.templates", timeout=8000)
            saved_ok = page.locator(".tpl-row", has_text="F51 大課表").count() == 1
            check(
                "④ 既有行為抽驗：加動作視窗可開關（F25）、改組數後可儲存並回到列表（F21）",
                panel_ok and saved_ok,
                f"panel={panel_ok} saved={saved_ok}",
            )

            # P2-1 回歸（Ryan 拍板貼底）：動作 3→2 跨門檻時「儲存課表」位置不得位移
            open_editor("F51 三動作課表")
            page.wait_for_timeout(300)

            def save_bottom():
                b = page.locator('button:has-text("儲存課表")').bounding_box()
                return round(b["y"] + b["height"])

            pos = [save_bottom()]
            for _ in range(2):  # 刪到剩 2 個動作，跨過門檻
                # F76 把✕ 改成向量圖示（按鈕上沒有那個字）；
                # F98 把刪除鈕搬到卡片標題列，類別是 .tpl-item-del。
                page.locator(".tpl-item").last.locator(".tpl-item-del").evaluate(
                    "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
                )
                page.wait_for_timeout(400)
                pos.append(save_bottom())
            check(
                "P2-1：動作 3→2 跨門檻塌陷時「儲存課表」位置不位移（貼底，避免誤觸儲存）",
                len(set(pos)) == 1 and page.locator(".tpl-item").count() == 1,
                f"save_bottom 序列={pos} 剩餘動作={page.locator('.tpl-item').count()}",
            )
            page.locator('button:has-text("← 課表列表")').click()
            page.wait_for_timeout(400)
            if page.locator(".modal-overlay").count() > 0:  # F27 未儲存離開確認
                page.locator('.modal button:has-text("離開")').first.click()
                page.wait_for_timeout(300)
            page.wait_for_selector(".screen.templates", timeout=8000)

            # ② 門檻下：2 個動作不加 scrollable，也不被拉長
            open_editor("F51 小課表")
            small_h = box_h(page, ".tpl-items")
            check(
                "② 編輯課表頁 2 個動作：不加 scrollable，也不被拉長成滿高",
                page.locator(".tpl-items.scrollable").count() == 0
                and small_h is not None
                and small_h < 400,
                f"scrollable=0 height={small_h}",
            )

            # ③ 極矮／橫向回退成可捲
            open_short = {}
            for w, h in ((844, 390), (320, 420)):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(300)
                page.locator('button:has-text("← 課表列表")').scroll_into_view_if_needed()
                page.wait_for_timeout(200)
                open_short[f"{w}x{h}"] = fully_visible(page, 'button:has-text("← 課表列表")')
            check(
                "③ 極矮／橫向視窗：回退成整頁可捲，底部按鈕捲動後完整可見",
                all(open_short.values()),
                f"{open_short}",
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

    print("\n==== F51 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    for n in notes:
        print(n)
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
