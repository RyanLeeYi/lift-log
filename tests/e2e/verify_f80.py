"""F80 驗證：課表排程（星期）與每週目標。

跑法：`uv run python tests/e2e/verify_f80.py`

後端的行為與邊界由 tests/test_schedule_and_settings.py 釘住（234 passed）。
這支負責它測不到的那半：**走真實 UI 點星期、存檔，再回頭打 API 確認寫進資料庫**——
畫面上亮著不代表送出去了，這正是「只驗畫面」會漏掉的地方。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, TOKEN, free_port, setup_and_home, start_server  # noqa: E402

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


def source_checks() -> None:
    """③⑦：邊界不破——API 層不直接寫 SQL，一律經 services。"""
    for name in ("schedule", "settings"):
        api_src = (REPO / f"app/api/{name}.py").read_text(encoding="utf-8")
        check("select(" not in api_src and "text(" not in api_src,
              f"⑦ app/api/{name}.py 沒有直接查詢（走 services）")
        check((REPO / f"app/services/{name}.py").is_file(), f"⑦ app/services/{name}.py 存在")

    migrations = (REPO / "app/migrations.py").read_text(encoding="utf-8")
    check("weekdays" in migrations, "① weekdays 走既有的冪等 ALTER 遷移機制")

    schedule_src = (REPO / "app/services/schedule.py").read_text(encoding="utf-8")
    check("deleted_at.is_(None)" in schedule_src, "⑤ 本週天數只算未刪除的組")


def make_template(page, name: str, weekdays: list[int]) -> None:
    """走真實 UI：新課表 → 選星期 → 加動作 → 存檔。"""
    # 可能是從首頁進來，也可能存完課表後還停在列表頁——兩種都要能用。
    # 用底部導覽定位而不是文字：F81 起首頁同時有「換一份課表」，name 比對會先命中它。
    if page.get_by_role("button", name="新課表").count() == 0:
        page.locator(".bottom-nav .nav-item", has_text="課表").click()
        page.wait_for_timeout(700)
    page.get_by_role("button", name="新課表").first.click()
    page.wait_for_timeout(600)
    page.locator("input[type=text]").fill(name)
    labels = ["一", "二", "三", "四", "五", "六", "日"]
    for day in weekdays:
        page.locator(".tpl-weekdays .chip", has_text=labels[day - 1]).first.click()
        page.wait_for_timeout(150)
    page.get_by_role("button", name="加動作").first.click()
    page.wait_for_timeout(700)
    page.locator(".tpl-add-modal .exercise-item").first.click()
    page.wait_for_timeout(200)
    page.get_by_role("button", name="確定加入").first.click()
    page.wait_for_timeout(600)
    page.get_by_role("button", name="儲存課表").click()
    page.wait_for_timeout(900)


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f80_{port}.db"
    release = REPO / f"liftlog_f80_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        source_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)

            # ⑥ 編輯畫面有星期多選
            page.locator(".bottom-nav .nav-item", has_text="課表").click()
            page.wait_for_timeout(700)
            page.get_by_role("button", name="新課表").first.click()
            page.wait_for_timeout(600)
            chips = page.locator(".tpl-weekdays .chip")
            check(chips.count() == 7, f"⑥ 編輯畫面有七顆星期（{chips.count()}）")
            small = [
                i for i in range(chips.count())
                if (box := chips.nth(i).bounding_box()) and box["height"] < 44
            ]
            check(not small, f"⑥ 星期鈕觸控高度 ≥44px（不足：{small}）")
            page.get_by_role("button", name="課表列表").first.click()
            page.wait_for_timeout(700)
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(600)

            # ①③⑥ UI 排星期 → 真的寫進 DB
            make_template(page, "推胸日", [1, 3])
            stored = api(base, "/api/templates")
            hit = [t for t in stored if t["name"] == "推胸日"]
            check(len(hit) == 1, f"① 課表建立成功（{[t['name'] for t in stored]}）")
            check(hit and hit[0]["weekdays"] == [1, 3],
                  f"③ 星期真的寫進資料庫（{hit[0]['weekdays'] if hit else None}）")

            # ⑥ 列表卡顯示排程
            page.wait_for_timeout(500)
            sched = page.locator(".tpl-sched")
            shown = sched.first.inner_text() if sched.count() else "無"
            check(sched.count() >= 1 and "一" in shown, f"⑥ 列表卡顯示排到的星期（{shown}）")

            # ④ 一天可排多份
            make_template(page, "晚上有氧", [1])
            today_body = api(base, "/api/schedule/today")
            monday_templates = [
                t["name"] for t in api(base, "/api/templates") if 1 in t["weekdays"]
            ]
            check(sorted(monday_templates) == ["推胸日", "晚上有氧"],
                  f"④ 同一天可排多份（週一：{monday_templates}）")

            # ③ schedule/today 的形狀
            check(set(today_body) >= {"date", "weekday", "templates", "weekly_target_days",
                                      "week_done_days", "week_days"},
                  f"③ schedule/today 欄位齊全（{sorted(today_body)}）")
            check(len(today_body["week_days"]) == 7, "③ week_days 是七天")

            # ② 週目標設定與值域
            check(api(base, "/api/settings/weekly_target_days")["value"] == "4",
                  "② 週目標預設 4")
            api(base, "/api/settings/weekly_target_days", "PUT", {"value": "5"})
            check(api(base, "/api/settings/weekly_target_days")["value"] == "5",
                  "② 週目標可修改")
            check(api(base, "/api/schedule/today")["weekly_target_days"] == 5,
                  "② schedule/today 反映新的週目標")
            try:
                api(base, "/api/settings/weekly_target_days", "PUT", {"value": "9"})
                bad_rejected = False
            except urllib.error.HTTPError as exc:
                bad_rejected = exc.code == 400
            check(bad_rejected, "② 超出值域的週目標被拒（400）")

            # ⑤ 本週天數由 sets 推導：開了訓練沒記組不算
            api(base, "/api/workouts", "POST", {})
            check(api(base, "/api/schedule/today")["week_done_days"] == 0,
                  "⑤ 開了訓練但沒記組，不算練過")
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
