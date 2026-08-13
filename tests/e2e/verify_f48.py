"""F48 課表三處清單超過兩項改固定高度捲動 E2E（實作者版）。
用法：PYTHONUTF8=1 uv run python verify_f48_own.py
涵蓋 acceptance ①②③④⑥⑦。

④ 一律用真實滑鼠滾輪捲動：程式設 `scrollTop = scrollHeight` 會與「還原失敗、Playwright 為點擊
自動把容器捲到底」混淆，首版就因此假 PASS（獨立驗收者用滾輪才抓到）。
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
    end_workout,
    open_templates,
    read_version,
    start_from_home,
    wait_home,
)

# 硬編碼的絕對路徑換成相對推導——換一台機器就跑不動的東西不該留在測試裡
REPO = Path(__file__).resolve().parents[2]
TOKEN = "f48-own-token"

SCROLLS = "e => e.scrollHeight > e.clientHeight + 2"
OUTSIDE = "(e, sel) => e.closest(sel) === null"


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


def in_viewport(page, selector):
    box = page.locator(selector).first.bounding_box()
    h = page.viewport_size["height"]
    return box is not None and box["y"] >= 0 and box["y"] + box["height"] <= h + 1


def dispatch_click(locator):
    """不經滑鼠的點擊：Playwright 的真實點擊會先把「捲出可視範圍的元素」捲進畫面（auto-scroll），
    那會在重繪前改掉容器 scrollTop，測不到還原邏輯。真實使用者點的是看得見的東西，故此處直接
    派發 click 事件，保留捲動位置。"""
    locator.evaluate("e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))")


def wheel_scroll(page, selector, dy):
    box = page.locator(selector).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, dy)
    page.wait_for_timeout(400)
    return page.eval_on_selector(selector, "e => e.scrollTop")


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f48own_{port}.db"
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
        pool = [e for e in exs if not e.get("is_bodyweight")][:4]
        e1, e2, e3, e4 = pool

        def make_tpl(name, exercises):
            return api(
                base,
                "POST",
                "/api/templates",
                {
                    "name": name,
                    "exercises": [
                        {"exercise_id": ex["id"], "position": i + 1, "default_sets": 3}
                        for i, ex in enumerate(exercises)
                    ],
                },
            )

        make_tpl("F48 小課表", [e1, e2])
        make_tpl("F48 課表二", [e2, e3])

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            wait_home(page)

            # ⑦ 版本
            ver = read_version(page)
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            # 不釘死版號（之後每個 feature 都會 bump）——只驗兩處一致，這才是維護鐵則的內容
            check(
                "⑦ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v49）",
                ver.startswith("v") and int(ver[1:]) >= 49 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )
            # F50 起容器填滿螢幕高度 → 要測「真的在捲」得讓內容確實溢出，故加量到 10 份課表 / 10 動作課表


            # ① 門檻下
            open_templates(page)
            check(
                "① 課表 2 份時不加捲軸（版面與現狀相同）",
                page.locator(".tpl-row").count() == 2
                and page.locator(".tpl-rows.scrollable").count() == 0,
                f"rows={page.locator('.tpl-row').count()}",
            )

            # ① 門檻上
            for i in range(14):  # 合計 16 份，844 高度下三處清單都必定溢出
                make_tpl(f"F48 課表{i + 3}", [e3, e4])
            page.locator(".screen.templates button", has_text="← 回首頁").click()
            wait_home(page)
            open_templates(page)
            scrolls = page.locator(".tpl-rows.scrollable").count() == 1 and page.eval_on_selector(
                ".tpl-rows.scrollable", SCROLLS
            )
            new_out = page.eval_on_selector(
                'button.btn-primary:has-text("＋ 新課表")', OUTSIDE, ".tpl-rows"
            )
            home_out = page.eval_on_selector(
                '.screen.templates button:has-text("← 回首頁")', OUTSIDE, ".tpl-rows"
            )
            check(
                "① 課表 4 份 → 卡片清單固定高度內捲，「＋新課表」「←回首頁」在捲動區外且在畫面內",
                scrolls
                and new_out
                and home_out
                and in_viewport(page, 'button.btn-primary:has-text("＋ 新課表")')
                and in_viewport(page, '.screen.templates button:has-text("← 回首頁")'),
                f"scrolls={scrolls} new_out={new_out} home_out={home_out}",
            )

            # ④-A 滾輪捲到非最大值 → 開/關刪除確認（重繪）→ 位置保留
            before = wheel_scroll(page, ".tpl-rows.scrollable", 200)
            dispatch_click(page.locator(".tpl-row").first.locator("button", has_text="刪除"))
            page.wait_for_selector(".modal-overlay", timeout=5000)
            page.wait_for_timeout(500)
            after = page.eval_on_selector(".tpl-rows.scrollable", "e => e.scrollTop")
            dispatch_click(page.locator(".modal-actions button", has_text="取消"))
            page.wait_for_timeout(500)
            after2 = page.eval_on_selector(".tpl-rows.scrollable", "e => e.scrollTop")
            check(
                "④ 課表列表：滾輪捲動後開/關刪除確認的重繪，捲動位置保留",
                before > 0 and abs(after - before) <= 2 and abs(after2 - before) <= 2,
                f"before={before} open={after} close={after2}",
            )

            page.locator(".screen.templates button", has_text="← 回首頁").click()
            wait_home(page)

            # ② 開練挑課表
            start_from_home(page)
            page.wait_for_selector(".tpl-choice-list", timeout=8000)
            b_scrolls = page.locator(
                ".tpl-choice-list.scrollable"
            ).count() == 1 and page.eval_on_selector(".tpl-choice-list.scrollable", SCROLLS)
            free_out = page.eval_on_selector(".free-choice", OUTSIDE, ".tpl-choice-list")
            check(
                "② 開練挑課表 4 份 → 課表選項捲動，「自由訓練／不用課表」在捲動區外且在畫面內",
                b_scrolls
                and free_out
                and in_viewport(page, ".free-choice")
                and page.locator(".tpl-choice").count() >= 4,
                f"scrolls={b_scrolls} free_out={free_out}",
            )

            # ③ 今日菜單門檻下
            page.locator(".tpl-choice", has_text="F48 小課表").click()
            page.wait_for_selector(".screen.picker", timeout=8000)
            check(
                "③ 今日菜單 2 個動作時不加捲軸",
                page.locator(".menu-list").count() == 1
                and page.locator(".menu-list.scrollable").count() == 0,
            )
            end_workout(page)
            wait_home(page)

            # ③ 今日菜單門檻上
            make_tpl("F48 大課表", [e1, e2, e3, e4] * 3)  # 12 個動作項，必定溢出
            start_from_home(page)
            page.wait_for_selector(".tpl-choice-list", timeout=8000)
            page.locator(".tpl-choice", has_text="F48 大課表").click()
            page.wait_for_selector(".screen.picker", timeout=8000)
            c_scrolls = page.locator(
                ".menu-list.scrollable"
            ).count() == 1 and page.eval_on_selector(".menu-list.scrollable", SCROLLS)
            # F83／F85 起菜單標頭改用全站的 .screen-head（返回 ＋ 課表名 ＋「已練 N 分」），
            # 原本的 .menu-head 已不存在。F48 ③ 的本意＝**捲動不得把標頭推出畫面**，
            # 對象換了、要求不變。
            head_out = page.eval_on_selector(".screen-head", OUTSIDE, ".menu-list")
            # F49 起有課表時「臨時加動作」是一顆入口鈕（搜尋/清單收進懸浮視窗），此處驗那顆鈕；
            # F48 ③ 的本意＝菜單捲動不得把下方元素推出畫面，對象換了、要求不變。
            add_out = page.eval_on_selector(".add-exercise-open", OUTSIDE, ".menu-list")
            check(
                "③ 今日菜單 4 個動作 → 固定高度內捲；標頭與臨時加動作入口在捲動區外且在畫面內",
                c_scrolls and head_out and add_out and in_viewport(page, ".add-exercise-open"),
                f"scrolls={c_scrolls} head_out={head_out} add_out={add_out}",
            )

            # ④-B 滾輪捲菜單 → 記一組 → 回 picker（重繪）→ 位置保留
            # F83 起菜單項目是 .menu-card（名稱在 .menu-card-name），不再是 .exercise-item；
            # F76 起主按鈕的無障礙名稱不含圖示字元，所以用 .log-btn 而不是文字比對。
            menu_before = wheel_scroll(page, ".menu-list.scrollable", 40)
            last_name = (
                page.locator(".menu-list .menu-card").last
                .locator(".menu-card-name").first.inner_text()
            )
            dispatch_click(page.locator(".menu-list .menu-card").last)
            page.wait_for_selector(".screen.logger", timeout=8000)
            page.locator(".log-btn").first.click()
            page.wait_for_timeout(800)
            page.locator(".logger-back").click()
            page.wait_for_selector(".screen.picker", timeout=8000)
            page.wait_for_timeout(500)
            menu_after = page.eval_on_selector(".menu-list.scrollable", "e => e.scrollTop")
            check(
                "④ 今日菜單：滾輪捲動後記一組回 picker 的重繪，捲動位置保留",
                menu_before > 0 and abs(menu_after - menu_before) <= 2,
                f"before={menu_before} after={menu_after}",
            )

            # ⑥ F4 既有行為。F83 把「1/3」那行文字換成 setBars() 的分段指示條
            # （.menu-bar，每組一段、已做的加 .done），語意不變＝「這個動作做了幾組」。
            # 驗渲染出來的段數，不再比對文字。
            row = page.locator(".menu-list .menu-card", has_text=last_name).first
            done_bars = row.locator(".menu-bar.done").count()
            total_bars = row.locator(".menu-bar").count()
            check(
                "⑥ F4 既有行為不變：記錄後今日菜單顯示已做 1 段／共 3 段",
                done_bars == 1 and total_bars == 3,
                f"done={done_bars} total={total_bars}",
            )

            # ④（Codex P2）換一次訓練 → 新菜單從頂端
            end_workout(page)
            wait_home(page)
            make_tpl("F48 大課表二", [e2, e3, e4, e1] * 3)
            start_from_home(page)
            page.wait_for_selector(".tpl-choice-list", timeout=8000)
            page.locator(".tpl-choice", has_text="F48 大課表二").click()
            page.wait_for_selector(".screen.picker", timeout=8000)
            page.wait_for_timeout(400)
            fresh = page.eval_on_selector(".menu-list.scrollable", "e => e.scrollTop")
            check(
                "④ 換一次訓練 → 新課表菜單從頂端開始（不沿用上一次的捲動位置）",
                fresh == 0,
                f"scrollTop={fresh}",
            )

            # ④ 從別的畫面重新進課表頁 → 從頂端
            end_workout(page)
            wait_home(page)
            open_templates(page)
            page.wait_for_timeout(400)
            tpl_fresh = page.eval_on_selector(".tpl-rows.scrollable", "e => e.scrollTop")
            check(
                "④ 重新進課表頁 → 清單從頂端開始（不沿用上次瀏覽位置）",
                tpl_fresh == 0,
                f"scrollTop={tpl_fresh}",
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

    print("\n==== F48 E2E（實作者版）====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("===========================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
