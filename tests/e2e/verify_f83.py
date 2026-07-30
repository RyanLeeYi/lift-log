"""F83 驗證：今日菜單改版（環形進度、動作卡、接著做）。

跑法：`uv run python tests/e2e/verify_f83.py`

「接著做」是這次新增的流程優化，它的價值全在**帶對動作與組號**——
所以測試不只看按鈕長怎樣，而是按下去之後回頭查記進資料庫的 set_number。
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
    setup_and_home,
    start_from_home,
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
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode()[:200]
        raise AssertionError(f"{method} {path} → {exc.code}: {body_text}") from None


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


def log_set(page, bump: int = 0) -> None:
    """在 logger 記一組。

    bump：先按幾次「+2.5」再記——若照預設值記，記到的就是「上次」那組的數值，
    測不出「本次做過就顯示本次的值」（第一版測法就是這樣自我矛盾的）。
    """
    for _ in range(bump):
        page.locator(".stepper").first.get_by_role("button", name="+").click()
        page.wait_for_timeout(150)
    page.get_by_role("button", name="完成這組").click()
    page.wait_for_timeout(900)


def main() -> int:
    port = free_port()
    db = e2e_tmp() / f"liftlog_f83_{port}.db"
    release = e2e_tmp() / f"liftlog_f83_release_{port}"
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

            exercises = api(base, "/api/exercises")[:3]
            ids = [e["id"] for e in exercises]
            api(base, "/api/templates", "POST", {
                "name": "推胸日",
                "weekdays": [today_iso],
                "exercises": [{"exercise_id": i, "default_sets": 3} for i in ids],
            })
            # 給第一個動作一段歷史，卡片第二行才有「上次」可顯示
            old = api(base, "/api/workouts", "POST", {"date": "2026-07-20"})
            api(base, f"/api/workouts/{old['id']}/sets", "POST", {
                "client_uuid": "f83-history-0001",
                "exercise_id": ids[0],
                "set_number": 1,
                "weight_kg": 62.5,
                "reps": 9,
            })

            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1300)
            start_from_home(page)  # 今天有排程 → 直接開這份課表

            # ① 標題列
            head = page.locator(".screen-head")
            check(head.locator("h1").inner_text() == "推胸日",
                  f"① 標題是課表名（{head.locator('h1').inner_text()}）")
            sub = head.locator(".st").inner_text()
            check("已練" in sub and "0/9 組" in sub, f"① 副標含已練時間與組數進度（{sub}）")
            check(head.locator(".back-btn").count() == 1, "① 左上有返回鈕")

            # ① 環形進度
            ring = page.locator(".progress-ring")
            check(ring.count() == 1, "① 標題列右側有環形進度")
            check(ring.locator(".ring-pct").inner_text() == "0%",
                  f"① 起始 0%（{ring.locator('.ring-pct').inner_text()}）")

            # ② 動作卡
            cards = page.locator(".menu-card")
            check(cards.count() == 3, f"② 每個動作一張卡（{cards.count()}）")
            check(page.locator(".menu-card.on").count() == 0, "② 還沒開始時沒有「進行中」")

            # ③ 組數指示：每組一段
            check(cards.first.locator(".menu-bar").count() == 3,
                  f"③ 每組一段（{cards.first.locator('.menu-bar').count()}）")
            check(cards.first.locator(".menu-bar.done").count() == 0, "③ 尚未完成時沒有亮起的段")

            # ④ 第二行顯示上次數值
            first_values = cards.first.locator(".menu-card-values").inner_text()
            check("62.5 kg × 9" in first_values, f"④ 有歷史的動作顯示上次數值（{first_values}）")
            # 「不顯示這行」＝整個元素不建出來。第一版斷言寫成「存在但空字串」，
            # 等於把多出來的 10px gap 寫死成期望值（review LOW-5 點出來的）。
            check(cards.nth(1).locator(".menu-card-values").count() == 0,
                  "④ 沒歷史又非進行中的動作不建那一行")

            # ⑤ 接著做
            check(page.locator(".next-up-label").inner_text() == "接著做", "⑤ 有「接著做」小標")
            next_up = page.locator(".next-up")
            name = next_up.locator(".next-up-name").inner_text()
            check("第 1 組" in name and exercises[0]["name_zh"] in name,
                  f"⑤ 指向第一個動作的第 1 組（{name}）")
            check("62.5 kg × 9" in next_up.locator(".next-up-values").inner_text(),
                  "⑤ 帶出參考數值")

            # F38 回歸防護：菜單每一列仍要有「動作表現」入口。
            # 改版第一版把整張卡換成裸按鈕，這個入口就消失了（review HIGH-1），
            # 而既有 E2E 沒有任何一支涵蓋它——所以釘在這裡。
            links = page.locator(".menu-list .detail-link").count()
            check(links == 3, f"F38 每張動作卡都有動作表現入口（{links}）")
            page.locator(".menu-list .detail-link").first.click()
            page.wait_for_timeout(1200)
            check(page.locator(".exercise-detail").count() == 1,
                  "F38 入口真的進得去動作表現頁")
            page.locator(".ex-back").click()
            page.wait_for_timeout(1000)

            # 有課表時也要有中／EN 切換（改版第一版只留在自由訓練那支，review MEDIUM-2）
            check(page.locator(".screen-head .lang-toggle").count() == 1,
                  "有課表時仍可切換中／EN")

            # ⑩ 觸控與捲動
            check(not undersized(page), f"⑩ 觸控目標 ≥44px（不足：{undersized(page)}）")
            no_hscroll = "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
            check(page.evaluate(no_hscroll), "⑩ 無水平捲動")
            check(page.locator(".menu-list.scrollable").count() == 1,
                  "⑩ 動作 >2 個時清單可捲（接著做留在捲動區外）")

            # ⑤ 按下去真的帶對動作與組號
            next_up.click()
            page.wait_for_timeout(1200)
            check(exercises[0]["name_zh"] in page.locator("h2").first.inner_text(),
                  f"⑤ 進 logger 且帶對動作（{page.locator('h2').first.inner_text()}）")
            log_set(page, bump=1)  # 62.5 → 65，才分得出顯示的是本次還是上次
            page.get_by_role("button", name="繼續下一組").click()
            page.wait_for_timeout(800)
            page.locator(".logger-back").click()
            page.wait_for_timeout(1200)

            # ② 記完一組後：那張卡轉「進行中」、環形進度前進
            in_progress = page.locator(".menu-card.on")
            check(in_progress.count() == 1, f"② 記過的動作轉為進行中（{in_progress.count()}）")
            check(in_progress.locator(".menu-card-state").inner_text() == "進行中",
                  "② 進行中的卡標示「進行中」")
            check(in_progress.locator(".menu-bar.done").count() == 1,
                  "③ 已完成的組亮起一段")
            check(page.locator(".progress-ring .ring-pct").inner_text() == "11%",
                  f"① 環形進度反映 1/9（{page.locator('.progress-ring .ring-pct').inner_text()}）")

            # ⑤ 接著做接續組號
            name = page.locator(".next-up .next-up-name").inner_text()
            check("第 2 組" in name, f"⑤ 組號接續（{name}）")

            # ④ 本次做過就顯示本次的值（而不是上次）
            values = in_progress.locator(".menu-card-values").inner_text()
            check("65 kg" in values and "62.5" not in values,
                  f"④ 本次做過後顯示本次的值而非上次（{values}）")

            # ⑤ 帶進資料庫的 set_number 真的是 2
            page.locator(".next-up").click()
            page.wait_for_timeout(1200)
            log_set(page)
            workout = max(api(base, "/api/workouts"), key=lambda w: w["id"])
            numbers = [
                s["set_number"] for s in api(base, f"/api/workouts/{workout['id']}")["sets"]
                if s["exercise_id"] == ids[0]
            ]
            check(sorted(numbers) == [1, 2], f"⑤ 寫進資料庫的組號是續接的（{numbers}）")

            # ⑥ 全部做滿 → 改講都做完了。
            # 用另一份「一個動作一組」的小課表走完整 UI 流程：已完成組數是前端狀態
            # （setCounts），拿 API 從外面灌組畫面是不知道的。
            ctx.close()
            api(base, "/api/templates", "POST", {
                "name": "一組就收",
                "weekdays": [],
                "exercises": [{"exercise_id": ids[0], "default_sets": 1}],
            })
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            swap = page.get_by_role("button", name="換一份課表")
            if swap.count():
                swap.first.click()
            else:
                start_from_home(page)
            page.wait_for_timeout(900)
            page.locator(".tpl-choice", has_text="一組就收").click()
            page.wait_for_timeout(1200)
            page.locator(".next-up").click()
            page.wait_for_timeout(1200)
            log_set(page)
            page.locator(".logger-back").click()
            page.wait_for_timeout(1200)
            check(page.locator(".next-up").count() == 0, "⑥ 全部做滿後不再推「接著做」")
            done_text = page.locator(".next-up-done").inner_text()
            check("都做完了" in done_text, f"⑥ 改講都做完了（{done_text}）")
            check(page.locator(".progress-ring .ring-pct").inner_text() == "100%",
                  "① 全部做完時環形進度 100%")

            # ⑦ 結束訓練
            check(page.get_by_role("button", name="結束訓練").count() == 1, "⑦ 有結束訓練")
            ctx.close()

            # ⑧ 自由訓練維持原本的選動作畫面
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            swap = page.get_by_role("button", name="換一份課表")
            if swap.count():
                swap.first.click()
                page.wait_for_timeout(900)
            page.get_by_role("button", name="自由訓練").click()
            page.wait_for_timeout(1200)
            shown = page.locator("h1").first.inner_text().strip()
            check(shown == "選動作", f"⑧ 自由訓練仍是「選動作」畫面（{shown}）")
            check(page.locator(".menu-card").count() == 0, "⑧ 自由訓練不套用菜單卡片版型")
            check(page.locator(".progress-ring").count() == 0, "⑧ 自由訓練沒有環形進度")
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
