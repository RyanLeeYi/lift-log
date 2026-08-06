"""F132 E2E：日曆補記改由 server 指派組號（client 自算組號的最後一條路）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f132.py`

涵蓋 acceptance ②③：撞號重現與修復、批次補記組號連續。

② 的重現手法：造一場某動作有 #1–#5、軟刪 #3（該動作可見組數＝4），
用日曆單一補記加一組——修法之前 `calendar.js` 送 `existing + 1 = 5`，
直接撞既有的 #5；修法之後不送 set_number，server 用「含軟刪的最大值 +1」算出 6。

③ 的重現手法：另一動作有 #1–#2、軟刪 #1（可見組數＝1），用同一課表批次補 3 組——
修法之前送 `existing + i + 1` = 2,3,4，第一個就撞既有的 #2；修法之後三組連續接在
真正最大值（2）後面＝3,4,5，與既有的 #2 一起、未軟刪組號無重複。
"""

from __future__ import annotations

import datetime
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    TOKEN,  # start_server／setup_and_home 都吃這顆，raw API 呼叫也要用同一顆才過得了 auth
    safe_port,
    setup_and_home,
    start_server,
    wait_home,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  |  ' + detail if detail else ''}")


def api(base: str, method: str, path: str, body: dict | None = None):
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


def log_set(base: str, workout_id: int, exercise_id: int, tag: str):
    return api(
        base,
        "POST",
        f"/api/workouts/{workout_id}/sets",
        {
            "client_uuid": f"f132-seed-{tag}",
            "exercise_id": exercise_id,
            "weight_kg": 20,
            "reps": 8,
        },
    )


def find_exercise(exercises: list[dict], name_zh: str) -> dict:
    return next(e for e in exercises if e["name_zh"] == name_zh)


def active_numbers(base: str, workout_id: int, exercise_id: int) -> list[int]:
    sets = api(base, "GET", f"/api/workouts/{workout_id}")["sets"]
    return sorted(s["set_number"] for s in sets if s["exercise_id"] == exercise_id)


def seed(base: str) -> dict:
    exercises = api(base, "GET", "/api/exercises")
    squat = find_exercise(exercises, "深蹲")  # ② 用
    deadlift = find_exercise(exercises, "硬舉")  # ③ 用

    day = datetime.date.today().replace(day=1).isoformat()
    workout = api(base, "POST", "/api/workouts", {"date": day})
    workout_id = workout["id"]

    # ② 深蹲：#1–#5，軟刪 #3（可見組數 4，最大值仍是 5）
    squat_sets = [log_set(base, workout_id, squat["id"], f"sq-{i}") for i in range(5)]
    got = [s["set_number"] for s in squat_sets]
    if got != [1, 2, 3, 4, 5]:
        raise AssertionError(f"種子資料組號非預期（深蹲）：{got}")
    api(base, "DELETE", f"/api/sets/{squat_sets[2]['id']}")  # 軟刪 #3

    # ③ 硬舉：#1–#2，軟刪 #1（可見組數 1，最大值仍是 2）
    deadlift_sets = [log_set(base, workout_id, deadlift["id"], f"dl-{i}") for i in range(2)]
    got = [s["set_number"] for s in deadlift_sets]
    if got != [1, 2]:
        raise AssertionError(f"種子資料組號非預期（硬舉）：{got}")
    api(base, "DELETE", f"/api/sets/{deadlift_sets[0]['id']}")  # 軟刪 #1

    api(
        base,
        "POST",
        "/api/templates",
        {
            "name": "F132 檢查課表",
            "exercises": [{"exercise_id": deadlift["id"], "position": 1, "default_sets": 3}],
        },
    )

    return {
        "day": day,
        "workout_id": workout_id,
        "squat": squat,
        "deadlift": deadlift,
    }


def run_checks(base: str) -> None:
    ctx = seed(base)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        wait_home(page)

        page.get_by_role("button", name="日曆").first.click()
        page.wait_for_selector(".calendar", timeout=8000)
        page.locator(f'.cal-day[aria-label="{ctx["day"]}"]').click()
        page.wait_for_timeout(600)

        # ② 單一補記：撞號重現與修復
        page.locator(".cal-add-toggle").click()
        page.wait_for_selector(".modal-overlay", timeout=5000)
        page.locator(".cal-add-search").fill(ctx["squat"]["name_zh"])
        page.wait_for_timeout(300)
        page.locator(".cal-add-list .exercise-item", has_text=ctx["squat"]["name_zh"]).first.click()
        page.wait_for_selector(".cal-add-modal.recording", timeout=5000)
        page.locator(".cal-add-log").click()
        page.wait_for_timeout(1200)

        squat_numbers = active_numbers(base, ctx["workout_id"], ctx["squat"]["id"])
        check(
            squat_numbers == [1, 2, 4, 5, 6],
            "② 日曆單一補記在軟刪 #3 之後加一組 → 新組號為 6，未軟刪組號無重複",
            f"got={squat_numbers}",
        )

        # ③ 批次補記：組號連續
        page.locator(".cal-add-toggle").click()
        page.wait_for_selector(".modal-overlay", timeout=5000)
        page.locator(".cal-add-mode button", has_text="用課表").click()
        page.wait_for_timeout(400)
        page.locator(".cal-tpl-item", has_text="F132 檢查課表").first.click()
        page.wait_for_selector(".cal-batch-row", timeout=8000)
        page.wait_for_timeout(400)
        page.locator(".cal-batch-log").click()
        page.wait_for_timeout(1500)

        deadlift_numbers = active_numbers(base, ctx["workout_id"], ctx["deadlift"]["id"])
        new_three = [n for n in deadlift_numbers if n != 2]
        check(
            deadlift_numbers == [2, 3, 4, 5] and new_three == [3, 4, 5],
            "③ 批次補記 3 組 → 接在既有最大值後面連續三個號碼，與既有 #2 無重複",
            f"got={deadlift_numbers}",
        )

        browser.close()


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f132-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        run_checks(base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    if passed != len(results):
        print("\nFAILED:")
        for ok, label in results:
            if not ok:
                print(f"  - {label}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
