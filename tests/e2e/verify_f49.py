"""F49 臨時加動作改按鈕＋懸浮視窗（有課表時）E2E。
用法：PYTHONUTF8=1 uv run python verify_f49_own.py
涵蓋 acceptance ①–⑨。

測試慣例（F48 教訓）：捲動用真實滾輪＋非邊界值；需要保留捲動位置時用 dispatchEvent 點擊，
避免 Playwright 真實 click 的 auto-scroll 在重繪前改掉 scrollTop。
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
    end_workout,
    read_version,
    start_from_home,
    wait_home,
)

REPO = Path(__file__).resolve().parents[2]
TOKEN = "f49-own-token"


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


def dispatch_click(locator):
    locator.evaluate("e => e.dispatchEvent(new MouseEvent('click', { bubbles: true }))")


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f49_{port}.db"
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
        api(
            base,
            "POST",
            "/api/templates",
            {
                "name": "F49 課表",
                "exercises": [
                    {"exercise_id": ex["id"], "position": i + 1, "default_sets": 3}
                    for i, ex in enumerate(pool)
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
            # F81 重建首頁之後 .home-start 不存在了（按鈕文字隨當天狀態變）。
            # 統一走 verify_f67 的 wait_home／start_from_home，下次改版才不會又全滅。
            wait_home(page)

            # ⑨ 版本
            # F81 把版號搬進設定畫面（首頁不再有 .version-tag）。
            # read_version() 自己會開設定再回首頁，這裡不要再包一層。
            ver = read_version(page)
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            check(
                "⑨ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v50）",
                ver.startswith("v") and int(ver[1:]) >= 50 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            def start_with_template():
                start_from_home(page)
                page.wait_for_selector(".tpl-choice-list", timeout=8000)
                # F82 起挑課表那一頁的項目是 .tpl-choice（卡片），不再是 .exercise-item
                page.locator(".tpl-choice", has_text="F49 課表").click()
                page.wait_for_selector(".screen.picker", timeout=8000)

            def start_free():
                start_from_home(page)
                page.wait_for_selector(".tpl-choice-list", timeout=8000)
                page.locator(".free-choice").click()
                page.wait_for_selector(".screen.picker", timeout=8000)

            # ① 有課表：清單三件套收起來，只留入口鈕；foot 兩顆照舊
            start_with_template()
            check(
                "① 有課表 → 搜尋框／chips／清單／自訂動作皆不在畫面上，只有「＋ 臨時加動作」入口鈕",
                page.locator(".add-exercise-open").count() == 1
                and page.locator('.screen.picker > input[type="search"]').count() == 0
                and page.locator(".screen.picker > .pick-list").count() == 0
                and page.locator(".screen.picker > .chips").count() == 0
                and page.locator(".screen.picker > .add-custom-ex").count() == 0
                # F83 起有課表時 .picker-foot 不存在了：結束訓練搬進菜單（.end-workout）、
                # 回首頁變成標頭的返回鍵（.back-btn）。① 的本意是「走得掉」，不是某個容器。
                and page.locator(".screen.picker .back-btn").count() == 1
                and page.locator(".end-workout").count() == 1,
                f"open_btn={page.locator('.add-exercise-open').count()} "
                f"inline_list={page.locator('.screen.picker > .pick-list').count()}",
            )

            # ③ 開窗：搜尋、chips、清單（可捲）、自訂動作、取消
            page.locator(".add-exercise-open").click()
            page.wait_for_selector(".pick-modal", timeout=5000)
            modal_ok = (
                page.locator('.pick-modal input[type="search"]').count() == 1
                and page.locator(".pick-modal .chips .chip").count() >= 2
                and page.locator(".pick-modal .pick-list").count() == 1
                and page.locator(".pick-modal .add-custom-ex").count() == 1
                and page.locator('.pick-modal button:has-text("取消")').count() == 1
            )
            scrolls = page.eval_on_selector(
                ".pick-modal .pick-list", "e => e.scrollHeight > e.clientHeight + 2"
            )
            check(
                "③ 視窗含搜尋／部位 chips／清單（固定高度可捲）／＋自訂動作／取消",
                modal_ok and scrolls,
                f"parts={modal_ok} list_scrolls={scrolls}",
            )

            # ③ 點遮罩空白處關閉
            page.locator(".modal-overlay").click(position={"x": 5, "y": 5})
            page.wait_for_timeout(300)
            check(
                "③ 點遮罩空白處關閉視窗",
                page.locator(".pick-modal").count() == 0,
                f"modal={page.locator('.pick-modal').count()}",
            )

            # ⑤ 搜尋就地更新：輸入後清單變少，且輸入框保有焦點與內容（沒有整頁重繪）
            page.locator(".add-exercise-open").click()
            page.wait_for_selector(".pick-modal", timeout=5000)
            before_n = page.locator(".pick-modal .pick-list .exercise-item").count()
            search = page.locator('.pick-modal input[type="search"]')
            search.click()
            search.type("bench", delay=30)
            page.wait_for_timeout(700)
            after_n = page.locator(".pick-modal .pick-list .exercise-item").count()
            focused = page.evaluate(
                "document.activeElement && document.activeElement.type === 'search'"
            )
            kept = search.input_value()
            check(
                "⑤ 視窗內搜尋就地更新清單：結果變少、輸入內容與焦點都還在（未整頁重繪）",
                after_n < before_n and after_n >= 1 and focused and kept == "bench",
                f"{before_n}→{after_n} focused={focused} value={kept!r}",
            )

            # ⑤ chips：點一顆篩選、再點同一顆取消
            search.fill("")
            page.wait_for_timeout(600)
            chip = page.locator(".pick-modal .chips .chip").first
            chip_label = chip.inner_text().strip()
            chip.click()
            page.wait_for_timeout(300)
            filtered = page.locator(".pick-modal .pick-list .exercise-item").count()
            on_after_first = page.locator(".pick-modal .chips .chip.on").count()
            chip.click()
            page.wait_for_timeout(300)
            unfiltered = page.locator(".pick-modal .pick-list .exercise-item").count()
            check(
                "⑤ 部位 chip 就地篩選、再點同一顆取消篩選",
                on_after_first == 1
                and filtered >= 1
                and unfiltered > filtered
                and page.locator(".pick-modal .chips .chip.on").count() == 0,
                f"chip={chip_label!r} all={unfiltered} filtered={filtered}",
            )

            # ⑥ 自訂動作：疊在上層、建立後回到清單且可選
            page.locator(".pick-modal .add-custom-ex").click()
            page.wait_for_timeout(400)
            stacked = page.locator(".custom-ex-modal").count() == 1
            custom_name = f"F49 自訂{port}"
            page.locator(".custom-ex-modal input").first.fill(custom_name)
            page.locator('.custom-ex-modal button:has-text("建立")').click()
            page.wait_for_timeout(1200)
            back_in_list = (
                page.locator(".custom-ex-modal").count() == 0
                and page.locator(".pick-modal").count() == 1
                and page.locator(
                    ".pick-modal .pick-list .exercise-item", has_text=custom_name
                ).count()
                == 1
            )
            check(
                "⑥ 自訂動作視窗疊在上層；建立後回到動作清單且新動作可選",
                stacked and back_in_list,
                f"stacked={stacked} back={back_in_list}",
            )

            # ⑦ 關窗再開：搜尋字與篩選清空
            page.locator('.pick-modal input[type="search"]').fill("bench")
            page.wait_for_timeout(600)
            page.locator('.pick-modal button:has-text("取消")').click()
            page.wait_for_timeout(300)
            page.locator(".add-exercise-open").click()
            page.wait_for_selector(".pick-modal", timeout=5000)
            check(
                "⑦ 每次開窗從乾淨狀態：搜尋字清空、無 chip 被選中",
                page.locator('.pick-modal input[type="search"]').input_value() == ""
                and page.locator(".pick-modal .chips .chip.on").count() == 0,
                f"q={page.locator('.pick-modal input[type=search]').input_value()!r}",
            )

            # ④ 點動作即進 logger 並可記一組；⑧ 菜單進度更新
            target = page.locator(".pick-modal .pick-list .exercise-item").first
            target_name = target.locator("span").first.inner_text()
            target.click()
            page.wait_for_selector(".screen.logger", timeout=8000)
            gone = page.locator(".pick-modal").count() == 0
            # F76：圖示改向量之後按鈕名稱不含「✓」，用 class 定位比對文字穩
            page.locator(".log-btn").first.click()
            page.wait_for_timeout(900)
            page.locator(".logger-back").click()
            page.wait_for_selector(".screen.picker", timeout=8000)
            page.wait_for_timeout(300)
            reopened = page.locator(".pick-modal").count()
            sets = api(
                base,
                "GET",
                f"/api/workouts?start={time.strftime('%Y-%m-%d')}&end={time.strftime('%Y-%m-%d')}",
            )
            wid = sets[0]["id"]
            saved = api(base, "GET", f"/api/workouts/{wid}")["sets"]
            check(
                "④ 視窗內點動作即進 logger（視窗關閉）、記錄成功；回 picker 後視窗不自己彈開",
                gone and len(saved) == 1 and reopened == 0,
                f"modal_gone={gone} sets={len(saved)} reopened={reopened} ex={target_name!r}",
            )

            # ⑧ 今日菜單與捲動照舊（F4／F48）
            menu_scrollable = page.locator(".menu-list.scrollable").count() == 1
            check(
                "⑧ 既有行為：今日菜單仍在且 4 動作時可捲（F4／F48 不受影響）",
                page.locator(".menu-list").count() == 1 and menu_scrollable,
                f"menu={page.locator('.menu-list').count()} scrollable={menu_scrollable}",
            )

            # 自審①更正：視窗開著時 foot 的「← 回首頁」被遮罩蓋住、實際點不到（那條洩漏路徑不可達，
            # 程式裡的歸零留作防禦）。真正可達的離開路徑是視窗內的 📈 動作表現——回來應接續開著。
            page.locator(".add-exercise-open").click()
            page.wait_for_selector(".pick-modal", timeout=5000)
            page.locator(".pick-modal .pick-list .detail-link").first.click()
            page.wait_for_selector(".screen.exercise-detail", timeout=8000)
            # F76 把 ← 換成向量圖示，按鈕上沒有那個字了；F81 起返回鍵一律是 .back-btn
            page.locator(".screen.exercise-detail .back-btn").first.click()
            page.wait_for_selector(".screen.picker", timeout=8000)
            page.wait_for_timeout(300)
            check(
                "自審①：從視窗內進『動作表現』再返回，視窗接續開著（瀏覽中途離開不該被關掉）",
                page.locator(".pick-modal").count() == 1,
                f"modal={page.locator('.pick-modal').count()}",
            )

            # 自審 findings 的回歸：② 離線時（動作庫刷新失敗）仍開得起來
            page.locator('.pick-modal button:has-text("取消")').click()  # 先關上上一段留著的視窗
            page.wait_for_timeout(250)
            page.route("**/api/exercises*", lambda route: route.abort())
            page.locator(".add-exercise-open").click()
            page.wait_for_timeout(800)
            opened_offline = page.locator(".pick-modal").count() == 1
            items_offline = page.locator(".pick-modal .pick-list .exercise-item").count()
            page.unroute("**/api/exercises*")
            check(
                "自審②：動作庫刷新失敗（離線）仍能開窗並沿用既有清單",
                opened_offline and items_offline >= 1,
                f"opened={opened_offline} items={items_offline}",
            )
            page.locator('.pick-modal button:has-text("取消")').click()
            page.wait_for_timeout(200)

            # review P2-2 回歸：視窗內搜尋失敗（5xx）時，錯誤訊息要出現在視窗裡（遮罩會蓋住畫面上那份）
            page.locator(".add-exercise-open").click()
            page.wait_for_selector(".pick-modal", timeout=5000)
            page.route("**/api/exercises*", lambda route: route.fulfill(status=500, body="boom"))
            page.locator('.pick-modal input[type="search"]').type("zzz", delay=30)
            page.wait_for_timeout(900)
            in_modal_err = page.locator(".pick-modal .error-banner").count()
            page.unroute("**/api/exercises*")
            check(
                "review P2-2：視窗內搜尋失敗時錯誤訊息顯示在視窗內（不被遮罩蓋住）",
                in_modal_err == 1,
                f"modal_error_banner={in_modal_err}",
            )

            # review P2-3 回歸：慢的舊回應不得覆蓋新結果（人工延遲短 query）
            page.locator('.pick-modal input[type="search"]').fill("")
            page.wait_for_timeout(500)

            def slow_short(route):
                q = route.request.url.split("q=")[-1]
                # 短 query（結果多）延遲 700ms，長 query 立即回 → 若無 seq 保護，短的會晚到蓋掉長的
                if len(q) <= 1:
                    page.wait_for_timeout(700)
                route.continue_()

            page.route("**/api/exercises?q=*", slow_short)
            search = page.locator('.pick-modal input[type="search"]')
            search.type("ben", delay=120)  # b → be → ben 三個請求並行
            page.wait_for_timeout(1800)
            final_n = page.locator(".pick-modal .pick-list .exercise-item").count()
            page.unroute("**/api/exercises?q=*")
            check(
                "review P2-3：快速連打時舊回應不覆蓋新結果（清單與搜尋字一致）",
                search.input_value() == "ben" and 1 <= final_n <= 6,
                f"q={search.input_value()!r} items={final_n}（無保護時會是 30+ 筆的 'b' 結果）",
            )
            page.locator('.pick-modal button:has-text("取消")').click()
            page.wait_for_timeout(250)

            # review P2-1 回歸：視窗開著時 token 失效 → 導回 setup → 重新登入後不得自己彈開視窗
            page.locator(".add-exercise-open").click()
            page.wait_for_selector(".pick-modal", timeout=5000)
            page.route("**/api/exercises*", lambda route: route.fulfill(status=401, body="{}"))
            page.locator('.pick-modal input[type="search"]').type("x", delay=30)
            page.wait_for_timeout(900)
            back_to_setup = page.locator(".screen.setup").count() == 1
            page.unroute("**/api/exercises*")
            page.locator(".screen.setup input").fill(TOKEN)
            page.locator('.screen.setup button:has-text("連線")').click()
            wait_home(page)
            start_from_home(page)  # 訓練仍在 → 回 picker
            page.wait_for_selector(".screen.picker", timeout=8000)
            page.wait_for_timeout(300)
            check(
                "review P2-1：視窗開著時 401 → 重新登入回訓練，視窗不自己彈開",
                back_to_setup
                and page.locator(".pick-modal").count() == 0
                and page.locator(".add-exercise-open").count() == 1,
                f"setup={back_to_setup} modal={page.locator('.pick-modal').count()}",
            )

            # ② 自由訓練：維持攤開，且沒有入口鈕
            # 這裡是「有課表」的狀態（上一段從 start_with_template 進來），
            # F83 後結束訓練在菜單的 .end-workout。用共用 helper，兩種版面都試。
            end_workout(page)
            wait_home(page)
            start_free()
            check(
                "② 自由訓練 → 搜尋框／chips／清單／＋自訂動作直接攤開，且無「＋ 臨時加動作」入口鈕",
                page.locator('.screen.picker > input[type="search"]').count() == 1
                and page.locator(".screen.picker > .chips").count() == 1
                and page.locator(".screen.picker > .pick-list").count() == 1
                and page.locator(".screen.picker > .add-custom-ex").count() == 1
                and page.locator(".add-exercise-open").count() == 0
                and page.locator(".menu-list").count() == 0,
                f"inline_search={page.locator('.screen.picker > input[type=search]').count()} "
                f"open_btn={page.locator('.add-exercise-open').count()}",
            )

            # ② 自由訓練點動作仍直接進 logger
            page.locator(".screen.picker > .pick-list .exercise-item").first.click()
            page.wait_for_selector(".screen.logger", timeout=8000)
            check("② 自由訓練點動作仍直接進 logger（流程不變）", True, "screen=logger")

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

    print("\n==== F49 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
