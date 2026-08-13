"""F50 可捲清單高度改為填滿剩餘空間 E2E。
用法：PYTHONUTF8=1 uv run python verify_f50_own.py
涵蓋 acceptance ①–⑩。

核心手法：同一份 DOM 在三種 viewport 高度下量清單高度與「可見完整項目數」，並確認底部按鈕
仍在畫面內。固定 px 的舊行為在不同高度下數值會完全相同——這正是要區分的。
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
    read_version,
    start_from_home,
    wait_home,
)

REPO = Path(__file__).resolve().parents[2]
TOKEN = "f50-own-token"


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
    """元素是否完整落在 viewport 內（底部按鈕不得被推出畫面）。"""
    b = page.locator(selector).first.bounding_box()
    if b is None:
        return False
    return b["y"] >= 0 and b["y"] + b["height"] <= page.viewport_size["height"] + 1


def visible_items(page, container, item):
    """容器可視區內「完整看得到」的項目數。"""
    return page.evaluate(
        """([csel, isel]) => {
            const c = document.querySelector(csel);
            if (!c) return -1;
            const cr = c.getBoundingClientRect();
            return [...c.querySelectorAll(isel)].filter((el) => {
              const r = el.getBoundingClientRect();
              return r.top >= cr.top - 1 && r.bottom <= cr.bottom + 1;
            }).length;
        }""",
        [container, item],
    )


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f50_{port}.db"
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
        pool = [e for e in exs if not e.get("is_bodyweight")][:6]

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

        make_tpl("F50 課表A", pool[:2])  # 先只有 2 份 → 驗 ⑦ 門檻下（列表頁／挑課表）
        make_tpl("F50 課表B", pool[:2])
        LATER = [("F50 大課表", pool[:6]), ("F50 小課表", pool[:2])] + [
            (f"F50 課表{i + 1}", pool[i % 4 : (i % 4) + 2]) for i in range(12)
        ]

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            wait_home(page)

            # ⑩ 版本
            # F81 把版號搬進設定畫面；read_version() 自己會開設定再回首頁。
            ver = read_version(page)
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            # 不釘死版號（每個 feature 都會 bump）——只驗兩處一致，那才是維護鐵則的內容
            check(
                "⑩ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v51）",
                ver.startswith("v") and int(ver[1:]) >= 51 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            # ⑦（門檻下，兩處直接實測）：只有 2 份課表時不加 scrollable、也不被拉長成滿高
            page.locator(".bottom-nav .nav-item", has_text="課表").click()
            page.wait_for_selector(".screen.templates", timeout=8000)
            rows_h = box_h(page, ".tpl-rows")
            not_scrollable_rows = page.locator(".tpl-rows.scrollable").count() == 0
            page.locator(".screen.templates button", has_text="← 回首頁").click()
            wait_home(page)
            start_from_home(page)
            page.wait_for_selector(".tpl-choice-list", timeout=8000)
            choice_h = box_h(page, ".tpl-choice-list")
            not_scrollable_choice = page.locator(".tpl-choice-list.scrollable").count() == 0
            check(
                "⑦ 課表列表頁與開練挑課表：2 份時不加 scrollable，也不被拉長成滿高",
                # 門檳改成「不超過畫面一半」而不是寫死的 px：
                # F82 把挑課表改成卡片（多了動作 chips 與上次紀錄），卡本身就變高了。
                # ⑦ 要的是「**不被拉長成滿高**」，不是某個特定數字。
                not_scrollable_rows
                and not_scrollable_choice
                and rows_h < 844 * 0.55
                and choice_h < 844 * 0.5,
                f"rows_h={rows_h} choice_h={choice_h} scrollable=({not_scrollable_rows},{not_scrollable_choice})",
            )
            page.locator(".screen.template-select .back-btn").click()
            wait_home(page)
            for name, ex in LATER:  # 補齊資料量，後續各條才有溢出情境
                make_tpl(name, ex)

            def goto_templates():
                if page.locator("button:has-text('繼續訓練'), button:has-text('開始訓練'), "
                                "button:has-text('挑一份課表')").count() == 0:
                    page.goto(base + "/")
                    wait_home(page)
                page.locator(".bottom-nav .nav-item", has_text="課表").click()
                page.wait_for_selector(".screen.templates", timeout=8000)

            def goto_template_select():
                start_from_home(page)
                page.wait_for_selector(".tpl-choice-list", timeout=8000)

            def goto_picker(tpl_name):
                page.locator(".tpl-choice", has_text=tpl_name).click()
                page.wait_for_selector(".screen.picker", timeout=8000)

            # ---------- ② 課表列表頁：三種高度下高度不同、按鈕都看得見 ----------
            goto_templates()
            heights, vis, btns = {}, {}, {}
            for h in (844, 667, 560):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(250)
                heights[h] = box_h(page, ".tpl-rows.scrollable")
                vis[h] = visible_items(page, ".tpl-rows.scrollable", ".tpl-row")
                btns[h] = fully_visible(
                    page, 'button.btn-primary:has-text("＋ 新課表")'
                ) and fully_visible(page, '.screen.templates button:has-text("← 回首頁")')
            check(
                "② 課表列表頁：清單高度隨螢幕高度變化，「＋新課表」「←回首頁」在各高度都完整可見",
                heights[844] > heights[667] > heights[560] and all(btns.values()),
                f"heights={heights} visible_cards={vis} buttons_ok={btns}",
            )
            check(
                "⑤ 課表列表頁：螢幕越高看得到越多卡片；390×560 仍至少看得到 1 張",
                vis[844] > vis[560] and vis[560] >= 1,
                f"visible_cards={vis}",
            )

            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(200)
            page.locator(".screen.templates button", has_text="← 回首頁").click()
            wait_home(page)

            # ---------- ③ 開練挑課表 ----------
            goto_template_select()
            sel_h, sel_btn = {}, {}
            for h in (844, 667, 560):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(250)
                sel_h[h] = box_h(page, ".tpl-choice-list.scrollable")
                sel_btn[h] = fully_visible(page, ".free-choice") and fully_visible(
                    page, ".screen.template-select .back-btn"
                )
            check(
                "③ 開練挑課表：清單高度隨螢幕變化，「自由訓練」「←回首頁」各高度都完整可見",
                sel_h[844] > sel_h[667] > sel_h[560] and all(sel_btn.values()),
                f"heights={sel_h} buttons_ok={sel_btn}",
            )

            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(200)

            # ---------- ① 今日菜單（6 動作） ----------
            goto_picker("F50 大課表")
            menu_h, menu_vis, menu_btn = {}, {}, {}
            for h in (844, 667, 560):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(250)
                menu_h[h] = box_h(page, ".menu-list.scrollable")
                menu_vis[h] = visible_items(page, ".menu-list.scrollable", ".exercise-row")
                menu_btn[h] = fully_visible(page, ".add-exercise-open") and fully_visible(
                    page, '.end-workout, .picker-foot .btn-danger'
                )
            check(
                "① 今日菜單：高度隨螢幕變化，「＋臨時加動作」與底部兩鍵各高度都完整可見",
                menu_h[844] > menu_h[667] > menu_h[560] and all(menu_btn.values()),
                f"heights={menu_h} visible={menu_vis} buttons_ok={menu_btn}",
            )
            check(
                "⑤ 今日菜單：螢幕越高看得到越多動作；390×560 仍至少看得到 1 個",
                menu_vis[844] > menu_vis[560] and menu_vis[560] >= 1,
                f"visible={menu_vis}",
            )

            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)

            # ---------- ⑥ 錯誤橫幅出現時讓位 ----------
            before_h = box_h(page, ".menu-list.scrollable")
            page.evaluate("""() => {
              const s = document.querySelector('.screen.picker');
              const b = document.createElement('div');
              b.className = 'error-banner';
              b.textContent = '測試用錯誤橫幅';
              s.insertBefore(b, s.children[1]);
            }""")
            page.wait_for_timeout(250)
            after_h = box_h(page, ".menu-list.scrollable")
            still_ok = fully_visible(page, ".add-exercise-open") and fully_visible(
                page, '.end-workout, .picker-foot .btn-danger'
            )
            check(
                "⑥ 錯誤橫幅出現 → 清單自動縮短讓位，底部按鈕仍完整可見",
                after_h < before_h and still_ok,
                f"{before_h}→{after_h} buttons_ok={still_ok}",
            )
            page.evaluate("document.querySelector('.error-banner').remove()")
            page.wait_for_timeout(200)

            # ---------- ④ 臨時加動作視窗內清單 ----------
            modal_h, modal_btn = {}, {}
            for h in (844, 667):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(250)
                if page.locator(".pick-modal").count() == 0:
                    page.locator(".add-exercise-open").click()
                    page.wait_for_selector(".pick-modal", timeout=5000)
                modal_h[h] = box_h(page, ".pick-modal .pick-list")
                modal_btn[h] = fully_visible(page, ".pick-modal .add-custom-ex") and fully_visible(
                    page, '.pick-modal button:has-text("取消")'
                )
            check(
                "④ 臨時加動作視窗：清單隨視窗可用高度伸縮，「＋自訂動作」與「取消」不被推出畫面",
                modal_h[844] > modal_h[667] and all(modal_btn.values()),
                f"heights={modal_h} buttons_ok={modal_btn}",
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(200)
            page.locator('.pick-modal button:has-text("取消")').click()
            page.wait_for_timeout(250)

            # ---------- review P1 回歸：視窗高度與搜尋框位置不隨結果數變動 ----------
            page.locator(".add-exercise-open").click()
            page.wait_for_selector(".pick-modal", timeout=5000)
            modal_before = page.locator(".pick-modal").bounding_box()
            search_before = page.locator('.pick-modal input[type="search"]').bounding_box()
            n_before = page.locator(".pick-modal .pick-list .exercise-item").count()
            page.locator('.pick-modal input[type="search"]').type("bench", delay=40)
            page.wait_for_timeout(900)
            modal_after = page.locator(".pick-modal").bounding_box()
            search_after = page.locator('.pick-modal input[type="search"]').bounding_box()
            n_after = page.locator(".pick-modal .pick-list .exercise-item").count()
            check(
                "review P1：搜尋篩到少數結果時視窗高度與搜尋框位置不動（打字中不從指下溜走）",
                n_after < n_before
                and abs(modal_after["height"] - modal_before["height"]) <= 1
                and abs(modal_after["y"] - modal_before["y"]) <= 1
                and abs(search_after["y"] - search_before["y"]) <= 1,
                f"items {n_before}→{n_after} modal_y {round(modal_before['y'])}→{round(modal_after['y'])} "
                f"modal_h {round(modal_before['height'])}→{round(modal_after['height'])} "
                f"search_y {round(search_before['y'])}→{round(search_after['y'])}",
            )
            page.locator('.pick-modal button:has-text("取消")').click()
            page.wait_for_timeout(250)

            # ---------- review P2 回歸：極矮／橫向視窗回退成可捲，底部按鈕捲得到 ----------
            short_ok = {}
            for w, h in ((844, 390), (320, 420)):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(300)
                auto_h = page.eval_on_selector(".screen.picker", "e => getComputedStyle(e).height")
                page.locator(
                    '.end-workout, .picker-foot .btn-danger'
                ).scroll_into_view_if_needed()
                page.wait_for_timeout(200)
                short_ok[f"{w}x{h}"] = (
                    fully_visible(page, '.end-workout, .picker-foot .btn-danger'),
                    auto_h,
                )
            check(
                "review P2：極矮／橫向視窗改回退成可捲，底部按鈕捲動後完整可見",
                all(v[0] for v in short_ok.values()),
                f"{short_ok}",
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)

            # ---------- ⑦ 門檻下不加捲軸也不被拉長 ----------
            end_workout(page)  # F83 後有課表時在菜單的 .end-workout，共用 helper 兩種版面都試
            wait_home(page)
            goto_template_select()
            goto_picker("F50 小課表")
            small_h = box_h(page, ".menu-list")
            check(
                "⑦ 今日菜單 2 動作：不加 scrollable，也不被拉長成滿高（維持自然高度）",
                page.locator(".menu-list.scrollable").count() == 0
                and small_h is not None
                and small_h < 200,
                f"class_scrollable=0 height={small_h}",
            )

            # ---------- ④ 自由訓練攤開清單也填滿 ----------
            end_workout(page)  # F83 後有課表時在菜單的 .end-workout，共用 helper 兩種版面都試
            wait_home(page)
            goto_template_select()
            page.locator(".free-choice").click()
            page.wait_for_selector(".screen.picker", timeout=8000)
            free_h = {}
            for h in (844, 667):
                page.set_viewport_size({"width": 390, "height": h})
                page.wait_for_timeout(250)
                free_h[h] = box_h(page, ".screen.picker > .pick-list")
            free_btn = fully_visible(page, '.end-workout, .picker-foot .btn-danger')
            check(
                "④ 自由訓練攤開的動作清單同樣填滿剩餘空間，底部按鈕完整可見",
                free_h[844] > free_h[667] and free_btn,
                f"heights={free_h} buttons_ok={free_btn}",
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(200)

            # ---------- ⑨/⑧ 既有行為：F48 捲動位置保留仍成立（滾輪＋dispatchEvent） ----------
            end_workout(page)  # F83 後有課表時在菜單的 .end-workout，共用 helper 兩種版面都試
            wait_home(page)
            goto_templates()
            tbox = page.locator(".tpl-rows.scrollable").bounding_box()
            page.mouse.move(tbox["x"] + tbox["width"] / 2, tbox["y"] + tbox["height"] / 2)
            page.mouse.wheel(0, 120)
            page.wait_for_timeout(400)
            b4 = page.eval_on_selector(".tpl-rows.scrollable", "e => e.scrollTop")
            page.locator(".tpl-row").first.locator("button", has_text="刪除").evaluate(
                "e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))"
            )
            page.wait_for_selector(".modal-overlay", timeout=5000)
            page.wait_for_timeout(500)
            af = page.eval_on_selector(".tpl-rows.scrollable", "e => e.scrollTop")
            check(
                "⑧ F48 的捲動位置保留在新高度策略下仍成立",
                b4 > 0 and abs(af - b4) <= 2,
                f"before={b4} after={af}",
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

    print("\n==== F50 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
