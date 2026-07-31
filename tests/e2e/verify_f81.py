"""F81 驗證：首頁改版 ＋ 設定畫面。

跑法：`uv run python tests/e2e/verify_f81.py`

首頁有三種「今天的安排」狀態（沒排程／一份／多份），過去只驗其中一種就是漏。
這裡三種都實際佈置資料走一次；週目標改完之後回首頁確認分母真的跟著變——
那是唯一能證明設定畫面與首頁接上的證據。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    TOKEN,
    e2e_tmp,
    free_port,
    native,
    setup_and_home,
    start_server,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req))


def reload_home(page, base: str) -> None:
    """重新載入並回到首頁（資料是從外部用 API 佈置的，畫面要重抓）。"""
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)


def undersized(page) -> list[str]:
    out = []
    for i in range(page.locator("button").count()):
        b = page.locator("button").nth(i)
        if not b.is_visible():
            continue
        box = b.bounding_box()
        if box and (box["height"] < 44 or box["width"] < 44):
            label = (b.inner_text() or b.get_attribute("aria-label") or "?").strip()[:12]
            out.append(f"{label}({int(box['width'])}x{int(box['height'])})")
    return out


def make_template(base: str, name: str, weekdays: list[int], exercise_id: int) -> int:
    created = api(base, "/api/templates", "POST", {
        "name": name,
        "weekdays": weekdays,
        "exercises": [{"exercise_id": exercise_id, "default_sets": 4}],
    })
    return created["id"]


def main() -> int:
    port = free_port()
    db = e2e_tmp() / f"liftlog_f81_{port}.db"
    release = e2e_tmp() / f"liftlog_f81_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    today_iso = date.today().isoweekday()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)

            # ① 問候列
            head = page.locator(".home-head")
            check(head.count() == 1, "① 首頁有問候列")
            greeting = head.locator("h1").inner_text()
            check(greeting.endswith("Ryan") and greeting[:2] in ("早安", "午安", "晚安"),
                  f"① 問候語依時段（{greeting}）")
            check("月" in head.locator(".date").inner_text(),
                  f"① 日期含月日與星期（{head.locator('.date').inner_text()}）")

            # ② 本週進度卡
            check(page.locator(".week-card").count() == 1, "② 本週進度卡存在")
            bars = page.locator(".week-bar").count()
            check(bars == 7, f"② 七段進度條（{bars}）")
            check("/ 4 天" in page.locator(".week-count").inner_text(),
                  f"② 分母是週目標（{page.locator('.week-count').inner_text()}）")
            today_bar = page.locator(".week-bar").nth(today_iso - 1)
            check("today" in (today_bar.get_attribute("class") or ""),
                  "② 今天那一段有標記（尚未練）")

            # ③-a 沒排程
            check("今天沒安排" in page.locator(".plan-card").inner_text(),
                  "③ 沒排程時說「今天沒安排」")
            check(page.get_by_role("button", name="挑一份課表").count() == 1,
                  "③ 沒排程時提供「挑一份課表」")

            # ④ 沒有歷史時不畫「上次訓練」卡
            check(page.locator(".last-card").count() == 0, "④ 沒有歷史時不畫上次訓練卡")

            # ⑤ 底部四格導覽
            nav = page.locator(".bottom-nav .nav-item")
            check(nav.count() == 4, f"⑤ 底部四格導覽（{nav.count()}）")
            labels = [nav.nth(i).inner_text().strip() for i in range(nav.count())]
            check(labels == ["課表", "日曆", "表現", "體重"], f"⑤ 導覽項目正確（{labels}）")
            check(not undersized(page), f"⑧ 首頁觸控目標 ≥44px（不足：{undersized(page)}）")
            no_hscroll = "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
            check(page.evaluate(no_hscroll), "⑧ 首頁無水平捲動")

            # 導覽真的會到那些畫面
            # F85 起日曆的標題是「訓練日曆」（改版把標題列換成全站 .screen-head 樣式）
            # F87 起體重頁的標題是「體重 · 體脂」（改版把兩個 metric 都寫進標題）
            for label, marker in (("課表", "課表"), ("日曆", "訓練日曆"), ("體重", "體重 · 體脂")):
                page.locator(".bottom-nav .nav-item", has_text=label).click()
                page.wait_for_timeout(900)
                shown = page.locator("h1").first.inner_text().strip()
                check(shown == marker, f"⑤ 導覽「{label}」進得去（{shown}）")
                page.get_by_role("button", name="回首頁").first.click()
                page.wait_for_timeout(900)

            # ③-b 一份排程
            exercise_id = api(base, "/api/exercises")[0]["id"]
            make_template(base, "推胸日", [today_iso], exercise_id)
            reload_home(page, base)
            plan = page.locator(".plan-card")
            check("推胸日" in plan.inner_text(),
                  f"③ 一份排程時顯示課表名（{plan.inner_text()[:30]}）")
            check(page.get_by_role("button", name="開始訓練").count() == 1,
                  "③ 一份時主按鈕是「開始訓練」")
            check(page.get_by_role("button", name="換一份課表").count() == 1,
                  "③ 一份時可換課表")
            check(page.locator(".plan-row").count() == 0, "③ 一份時不使用多份版型")

            # ③-c 多份排程
            make_template(base, "晚上有氧", [today_iso], exercise_id)
            reload_home(page, base)
            rows = page.locator(".plan-row")
            check(rows.count() == 2, f"③ 多份時每份一列（{rows.count()}）")
            names = [
                rows.nth(i).locator(".plan-row-name").inner_text() for i in range(rows.count())
            ]
            check(names == ["推胸日", "晚上有氧"], f"③ 多份依課表順序（{names}）")
            check(page.get_by_role("button", name="開始訓練").count() == 2,
                  "③ 每份各有「開始訓練」")
            check(not undersized(page), f"⑧ 多份版型觸控目標 ≥44px（不足：{undersized(page)}）")

            # ③-d 訓練進行中：主按鈕改口
            page.get_by_role("button", name="開始訓練").first.click()
            page.wait_for_timeout(1200)
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(1000)
            check(page.get_by_role("button", name="繼續訓練").count() >= 1,
                  "③ 訓練進行中主按鈕變「繼續訓練」")

            # ④ 記一組之後：上次訓練卡出現、本週進度 +1
            workouts = api(base, "/api/workouts")
            api(base, f"/api/workouts/{workouts[0]['id']}/sets", "POST", {
                "client_uuid": "f81-verify-0001",
                "exercise_id": exercise_id,
                "set_number": 1,
                "weight_kg": 60,
                "reps": 8,
            })
            reload_home(page, base)
            last = page.locator(".last-card")
            check(last.count() == 1, "④ 有歷史後出現上次訓練卡")
            check("推胸日" in last.inner_text(), f"④ 上次訓練帶課表名（{last.inner_text()[:40]}）")
            check("480" in last.locator(".last-volume").inner_text(),
                  f"④ 總量正確（{last.locator('.last-volume').inner_text()}）")
            check(page.locator(".week-count .n").inner_text() == "1", "② 記完組後本週天數 +1")
            done_bar = page.locator(".week-bar").nth(today_iso - 1)
            check("done" in (done_bar.get_attribute("class") or ""), "② 今天那一段轉為已練")

            # ⑥⑦ 設定畫面
            page.locator(".home-settings").click()
            page.wait_for_timeout(900)
            check(page.locator("h1").first.inner_text().strip() == "設定", "⑥ 齒輪進得去設定畫面")
            check(
                page.locator(".switch-row [role=switch]").count() >= 1,
                "⑥ 休息提醒開關搬進設定畫面",
            )
            check(page.locator(".version-tag").count() == 1, "⑦ 版號入口在設定畫面")
            check(page.locator(".set-row-val").inner_text() == "4", "⑥ 週目標顯示目前值")
            page.locator(".set-row-ctl button").last.click()
            page.wait_for_timeout(900)
            check(page.locator(".set-row-val").inner_text() == "5", "⑥ 週目標可調")
            check(api(base, "/api/settings/weekly_target_days")["value"] == "5",
                  "⑥ 週目標真的寫進後端")
            check(not undersized(page), f"⑧ 設定畫面觸控目標 ≥44px（不足：{undersized(page)}）")
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(1000)
            check("/ 5 天" in page.locator(".week-count").inner_text(),
                  f"⑥ 首頁分母跟著週目標變（{page.locator('.week-count').inner_text()}）")

            # ⑥ 首頁不再有那兩顆開關
            check(page.locator(".switch-row").count() == 0, "⑥ 首頁不再放提醒/浮動計時開關")
            # ⑥ 週目標寫入失敗要回復畫面——留著未儲存的數字，下一次加減會從錯的值起算
            #（Codex 2026-07-29 P2）
            page.locator(".home-settings").click()
            page.wait_for_timeout(800)
            before = page.locator(".set-row-val").inner_text()
            page.route("**/api/settings/**", lambda route: route.abort()
                       if route.request.method == "PUT" else route.continue_())
            page.locator(".set-row-ctl button").last.click()
            page.wait_for_timeout(900)
            after = page.locator(".set-row-val").inner_text()
            check(after == before, f"⑥ 寫入失敗時週目標退回原值（{before} → {after}）")
            page.unroute("**/api/settings/**")
            ctx.close()

            # ⑥ token 失效時要導回重新登入，而不是停在「看起來只是今天沒安排」的首頁
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            page.evaluate("() => localStorage.setItem('liftlog.token', 'bogus-token')")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            check(page.locator("input[type=password]").count() == 1,
                  "⑥ token 失效 → 回到 setup 重新輸入（401 不被當成可忽略的載入失敗）")
            ctx.close()

            # ⑧ app 版的設定畫面：版號是可點按鈕（web 版是純文字 div，量不到——
            #    這個 39px 的缺口就是這樣躲過前兩輪量測的，Codex 2026-07-29 驗收抓到）
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=85)
            setup_and_home(page)
            page.locator(".home-settings").click()
            page.wait_for_timeout(900)
            check(page.locator(".version-tag-btn").count() == 1, "⑦ app 版設定畫面的版號可點")
            small = undersized(page)
            check(not small, f"⑧ app 版設定畫面觸控目標 ≥44px（不足：{small}）")
            ctx.close()

            # ⑧ 矮螢幕不破版
            ctx = browser.new_context(viewport={"width": 360, "height": 640})
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)  # 新 context＝新的 localStorage，要重新設定 token
            page.wait_for_timeout(800)
            check(page.evaluate(no_hscroll), "⑧ 360×640 無水平捲動")
            # 矮螢幕塞不下時整頁可捲、導覽捲得到——沿用 F50 訂下的原則
            #（「按鈕捲得到比硬留在畫面內重要」），不是把內容壓扁或讓它被裁掉。
            page.locator(".bottom-nav").scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            nav_box = page.locator(".bottom-nav").bounding_box()
            fits = nav_box is not None and nav_box["y"] >= 0 and (
                nav_box["y"] + nav_box["height"] <= 641
            )
            check(fits, f"⑧ 矮螢幕上底部導覽捲得到且完整（{nav_box}）")
            check(not undersized(page), f"⑧ 360 寬觸控目標 ≥44px（不足：{undersized(page)}）")
            ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for _ in range(20):
            try:
                db.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.25)
        for f in release.iterdir():
            f.unlink()
        release.rmdir()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
