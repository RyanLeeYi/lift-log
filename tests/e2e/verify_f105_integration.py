"""F105 整合切片 E2E：四個平行 worker 之間掉在縫裡、由主 session 補上的部分。

四個 worker 各自守著自己的檔案，所以下面這幾條沒有人擁有：
  ① 自訂動作建立視窗可選「時間型」（acceptance ⑥；在 custom-exercise.js，
     不在任何 worker 的 may-write）
  ② 日曆「補記這一天」對時間型動作送 duration_seconds（calendar.js worker 的單只涵蓋「編輯」）
  ③ 課表批次補記時間型動作（同上）
  ④ 首頁「上次訓練」卡同時講噸位與總秒數（acceptance ③；需要後端 LastWorkout 補欄位才做得到）

②③ 的價值在於它們原本會 **422**：兩條路徑都寫死只送 reps，而後端對時間型動作收到 reps 一律拒絕。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f105_integration.py`

量測一律問渲染結果與伺服器端實際資料，不問 class 名稱有沒有掛上
（本 repo 既有 E2E 規則，見 verify_f136.py 開頭）。
"""

from __future__ import annotations

import json
import sys
import urllib.error
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
    wait_home,
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
        raise AssertionError(f"{method} {path} -> {exc.code}: {body_text}") from None


def open_calendar(page) -> None:
    page.locator(".bottom-nav").get_by_role("button", name="日曆").click()
    page.wait_for_selector(".screen.calendar", timeout=10_000)
    page.wait_for_timeout(600)


def go_home(page, base: str) -> None:
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)


def main() -> int:  # noqa: PLR0915
    port = free_port()
    db = e2e_tmp() / f"liftlog_f105_int_{port}.db"
    release = e2e_tmp() / f"liftlog_f105_int_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    today = date.today()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)

            # ---------- ① 自訂動作建立視窗可選時間型 ----------
            wait_home(page)
            start_from_home(page)  # 首頁「開始訓練」→ picker
            page.wait_for_timeout(700)
            add_btn = page.locator(".add-custom-ex")
            check(add_btn.count() >= 1, "① picker 裡有「＋ 自訂動作」入口")
            add_btn.first.click()
            page.wait_for_selector(".custom-ex-modal", timeout=8_000)

            modal = page.locator(".custom-ex-modal")
            time_row = modal.locator(".checkbox-row", has_text="時間型動作")
            check(time_row.count() == 1, "① 建立視窗有「時間型動作」選項")

            modal.locator("input[type=text]").first.fill("整合棒式 F105")
            time_row.locator("input[type=checkbox]").check()
            modal.locator(".modal-confirm").click()
            page.wait_for_timeout(1200)

            created = [e for e in api(base, "/api/exercises") if e["name_zh"] == "整合棒式 F105"]
            check(len(created) == 1, "① 動作真的建立了")
            check(
                bool(created) and created[0]["mode"] == "time",
                f"① 勾選後建出來的 mode 是 time（實際 {created[0]['mode'] if created else '缺'}）",
            )
            time_ex = created[0]

            # ---------- ② 日曆「補記這一天」記時間型（原本會 422）----------
            go_home(page, base)
            open_calendar(page)
            page.locator(f'.cal-day[aria-label="{today.isoformat()}"]').click()
            page.wait_for_timeout(700)
            page.locator(".cal-add-toggle").click()
            page.wait_for_selector(".cal-add-modal", timeout=8_000)
            page.wait_for_timeout(500)
            page.locator(".cal-add-search").fill("整合棒式")
            page.wait_for_timeout(600)
            page.locator(".cal-add-list .exercise-item", has_text="整合棒式 F105").first.click()
            page.wait_for_timeout(600)

            stepper_names = page.locator(".cal-add-modal .steppers .name").all_inner_texts()
            check(
                any("秒" in n for n in stepper_names),
                f"② 補記視窗對時間型顯示秒數 stepper（實際 {stepper_names}）",
            )
            check(
                not any("REPS" in n for n in stepper_names),
                f"② 補記視窗沒有次數輸入（實際 {stepper_names}）",
            )
            page.locator(".cal-add-log").click()
            page.wait_for_timeout(1500)

            day_sets = [
                s
                for w in api(base, f"/api/workouts?from={today.isoformat()}&to={today.isoformat()}")
                for s in api(base, f"/api/workouts/{w['id']}")["sets"]
                if s["exercise_id"] == time_ex["id"]
            ]
            check(len(day_sets) == 1, f"② 補記真的寫進去了（{len(day_sets)} 組）")
            check(
                bool(day_sets) and day_sets[0]["duration_seconds"] is not None,
                "② 寫進去的是 duration_seconds（不是 reps）",
            )
            check(
                bool(day_sets) and day_sets[0]["reps"] is None,
                "② reps 保持 null（沒有被硬塞值繞過 422）",
            )

            # ---------- ③ 課表批次補記時間型 ----------
            tpl = api(
                base,
                "/api/templates",
                "POST",
                {
                    "name": "整合核心日 F105",
                    "exercises": [{"exercise_id": time_ex["id"], "default_sets": 2}],
                },
            )
            fetched = api(base, f"/api/templates/{tpl['id']}")
            check(
                fetched["exercises"][0].get("mode") == "time",
                "③ 課表項自帶 mode（TemplateExerciseOut 契約）",
            )

            go_home(page, base)
            open_calendar(page)
            page.locator(f'.cal-day[aria-label="{today.isoformat()}"]').click()
            page.wait_for_timeout(700)
            page.locator(".cal-add-toggle").click()
            page.wait_for_selector(".cal-add-modal", timeout=8_000)
            page.wait_for_timeout(500)
            page.locator(".cal-add-mode").get_by_text("用課表").click()
            page.wait_for_timeout(700)
            page.locator(".cal-tpl-item", has_text="整合核心日 F105").first.click()
            page.wait_for_timeout(1000)

            summary = page.locator(".batch-summary").first.inner_text()
            check("秒" in summary, f"③ 批次列摘要講秒數（實際「{summary}」）")

            before = len(day_sets)
            page.locator(".cal-batch-log").click()
            page.wait_for_timeout(2000)

            after_sets = [
                s
                for w in api(base, f"/api/workouts?from={today.isoformat()}&to={today.isoformat()}")
                for s in api(base, f"/api/workouts/{w['id']}")["sets"]
                if s["exercise_id"] == time_ex["id"]
            ]
            check(
                len(after_sets) == before + 2,
                f"③ 批次寫入 2 組成功（沒有 422；{before} → {len(after_sets)}）",
            )
            check(
                all(s["duration_seconds"] is not None and s["reps"] is None for s in after_sets),
                "③ 批次寫進去的全是時間型欄位",
            )

            # ---------- ④ 首頁「上次訓練」卡兩個數字 ----------
            reps_ex = api(base, "/api/exercises")[0]
            workouts = api(base, f"/api/workouts?from={today.isoformat()}&to={today.isoformat()}")
            api(
                base,
                f"/api/workouts/{workouts[0]['id']}/sets",
                "POST",
                {
                    "client_uuid": "f105-int-mix-0001",
                    "exercise_id": reps_ex["id"],
                    "weight_kg": 50.0,
                    "reps": 10,
                },
            )
            summary_api = api(base, "/api/schedule/today")["last_workout"]
            check(
                summary_api["volume_kg"] == 500.0,
                f"④ 後端噸位只算次數型（實際 {summary_api['volume_kg']}）",
            )
            check(
                summary_api["duration_seconds"] > 0,
                f"④ 後端另外回總秒數（實際 {summary_api['duration_seconds']}）",
            )

            go_home(page, base)
            card = page.locator(".last-card")
            check(card.count() == 1, "④ 首頁有「上次訓練」卡")
            units = card.locator(".last-volume .u").all_inner_texts()
            check(
                "kg" in units and "秒" in units,
                f"④ 兩個數字並列且各自標明單位（實際 {units}）",
            )
            values = card.locator(".last-volume .v").all_inner_texts()
            check(
                len(values) == 2 and values[0] != values[1],
                f"④ 兩個數字是各自的值、沒有相加成一個（實際 {values}）",
            )

            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=20)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    if passed != len(results):
        print("\nFAILED:")
        for ok, label in results:
            if not ok:
                print(f"  - {label}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
