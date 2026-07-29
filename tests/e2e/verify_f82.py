"""F82 驗證：挑今日課表改版。

跑法：`uv run python tests/e2e/verify_f82.py`

這個畫面的重點是「哪一張被攤開」——它要跟 F80 的排程一致，而不是永遠第一張。
所以測試佈了兩種資料：今天有排程、今天沒排程，各驗一次。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    REPO,
    TOKEN,
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
        body = exc.read().decode()[:200]
        raise AssertionError(f"{method} {path} → {exc.code}: {body}") from None


def make_template(base: str, name: str, weekdays: list[int], exercise_ids: list[int]) -> int:
    created = api(base, "/api/templates", "POST", {
        "name": name,
        "weekdays": weekdays,
        "exercises": [{"exercise_id": i, "default_sets": 4} for i in exercise_ids],
    })
    return created["id"]


def log_workout(base: str, template_id: int, exercise_id: int, day: date, uuid: str) -> None:
    workout = api(base, "/api/workouts", "POST",
                  {"date": day.isoformat(), "template_id": template_id})
    api(base, f"/api/workouts/{workout['id']}/sets", "POST", {
        "client_uuid": uuid,
        "exercise_id": exercise_id,
        "set_number": 1,
        "weight_kg": 100,
        "reps": 10,
    })


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


def open_picker(page, base: str) -> None:
    """回首頁後進挑課表畫面（資料是從外部佈的，得重載）。

    今天有排程時，首頁主按鈕是「開始訓練」＝直接用那份開練，不經挑課表——
    要走到這個畫面得按「換一份課表」。沒排程時主按鈕本身就是「挑一份課表」。
    """
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_timeout(1300)
    swap = page.get_by_role("button", name="換一份課表")
    if swap.count():
        swap.first.click()
        page.wait_for_timeout(900)
    else:
        start_from_home(page)


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f82_{port}.db"
    release = REPO / f"liftlog_f82_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    today_iso = date.today().isoweekday()
    tomorrow_iso = today_iso % 7 + 1
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)

            exercises = [e["id"] for e in api(base, "/api/exercises")[:3]]
            # 第一張沒排今天、第二張排今天——用來證明「攤開的是排程那張」而不是第一張
            first = make_template(base, "拉背日", [tomorrow_iso], exercises[:2])
            second = make_template(base, "推胸日", [today_iso], exercises)
            make_template(base, "腿日", [], exercises[:1])
            log_workout(
                base, first, exercises[0], date.today() - timedelta(days=2), "f82-uuid-back-01"
            )

            open_picker(page, base)

            # ① 標題與副標
            head = page.locator(".screen-head")
            check(head.locator("h1").inner_text() == "挑今日課表",
                  f"① 標題為「挑今日課表」（{head.locator('h1').inner_text()}）")
            subtitle = head.locator(".st").inner_text()
            check(subtitle == "3 份課表", f"① 副標顯示份數（{subtitle}）")
            check(head.locator(".back-btn").count() == 1, "① 左上有返回鈕")

            cards = page.locator(".tpl-choice")
            check(cards.count() == 3, f"② 每份課表一張卡（{cards.count()}）")

            # ② 攤開的是「今天排到的」那張，不是第一張
            highlighted = page.locator(".tpl-choice.on")
            check(highlighted.count() == 1, f"② 只有一張被強調（{highlighted.count()}）")
            name = highlighted.locator(".tpl-choice-name").inner_text()
            check("推胸日" in name, f"② 強調的是今天排到的那份（{name}）")
            check(highlighted.locator(".tpl-choice-chips .chip").count() == 3,
                  "② 強調的那張列出動作 chips")
            bg = highlighted.evaluate("el => getComputedStyle(el).backgroundColor")
            check(bg == "rgb(59, 52, 44)", f"② 強調卡用 --card-hi（{bg}）")

            # ② 其餘顯示「上次 M/D · X,XXX kg」／沒練過
            back_card = page.locator(".tpl-choice", has_text="拉背日")
            back_last = back_card.locator(".tpl-choice-last").inner_text()
            check("上次" in back_last and "1,000 kg" in back_last,
                  f"② 未展開的卡顯示上次與總量（{back_last}）")
            leg_card = page.locator(".tpl-choice", has_text="腿日")
            leg_last = leg_card.locator(".tpl-choice-last").inner_text()
            check("還沒練過" in leg_last, f"② 沒練過的講「還沒練過」（{leg_last}）")

            # ④ 份量摘要
            check("3 動作 · 12 組" in highlighted.inner_text(),
                  f"④ 卡片右側顯示動作數與總組數（{highlighted.inner_text()}）")

            # ⑥ 自由訓練在最後
            free = page.locator(".free-choice")
            check(free.count() == 1 and free.inner_text().strip() == "自由訓練",
                  "⑥ 最後一顆是「自由訓練」")

            # ⑧ 觸控與捲動
            check(not undersized(page), f"⑧ 觸控目標 ≥44px（不足：{undersized(page)}）")
            no_hscroll = "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
            check(page.evaluate(no_hscroll), "⑧ 無水平捲動")
            check(page.locator(".tpl-choice-list.scrollable").count() == 1,
                  "⑧ 超過兩份時課表清單可捲（自由訓練留在捲動區外）")
            free_box = free.bounding_box()
            fits = free_box is not None and (
                free_box["y"] + free_box["height"] <= PHONE["height"] + 1
            )
            check(fits, f"⑧ 自由訓練固定在可視範圍（{free_box}）")

            # ⑤ 點卡片＝用那份課表開始
            highlighted.click()
            page.wait_for_timeout(1200)
            shown = page.locator("h1").first.inner_text().strip()
            check(shown == "今日菜單", f"⑤ 點卡片直接開練（{shown}）")
            # 取最新那場（清單裡還有前面佈資料用的舊訓練）
            latest = max(api(base, "/api/workouts"), key=lambda w: w["id"])
            check(latest["template_id"] == second,
                  f"⑤ 建立的訓練綁的是那份課表（{latest['template_id']} vs {second}）")

            # ③ 今天沒排程 → 攤開第一張（維持視覺節奏）。
            # 換一個 context 而不是刪訓練：進行中的訓練是前端狀態（localStorage），
            # 而後端沒有刪 workout 的端點——開新 context 是最乾淨的重置。
            api(base, f"/api/templates/{second}/weekdays", "PATCH", {"weekdays": []})
            ctx.close()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            open_picker(page, base)
            highlighted = page.locator(".tpl-choice.on")
            check(highlighted.count() == 1
                  and "拉背日" in highlighted.inner_text(),
                  f"③ 沒排程時攤開第一張（{highlighted.inner_text()[:20]}）")
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
