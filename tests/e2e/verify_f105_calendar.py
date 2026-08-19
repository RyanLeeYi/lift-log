"""F105 前端切片 E2E：日曆熱力圖改吃組數＋日曆明細依動作 mode 分流顯示。

驗的是凍結 acceptance ③④⑥：
  ① 只有時間型組的一天在熱力圖上有顏色（不是空白），明細顯示「N 秒」不是「N 次」
  ② 同一天次數型＋時間型並存時，噸位與總秒數兩個數字都出現且各自標明，不相加
  ③ 純次數型的一天行為不變（回歸）
  ④ 分級：組數多的日子級別 >= 組數少的日子
外加一條凍結契約的直接驗證：編輯時間型組要送 duration_seconds、不送 reps（不誤觸 422）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f105_calendar.py`

量測一律問渲染結果（實際文字、getAttribute），不問 class 名稱有沒有掛上
（本 repo 既有 E2E 規則，見 verify_f136.py 開頭）。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ①②③④⑤ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError
# exit 1——腳本自己釘 UTF-8（同 verify_f67／verify_f136 的既有防呆）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    TOKEN,
    e2e_tmp,
    free_port,
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
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()[:200]
        raise AssertionError(f"{method} {path} -> {exc.code}: {body}") from None


def css(page, selector: str, prop: str) -> str:
    return page.eval_on_selector(
        selector, "(e, p) => getComputedStyle(e).getPropertyValue(p)", prop,
    )


def open_calendar(page) -> None:
    page.locator(".bottom-nav").get_by_role("button", name="日曆").click()
    page.wait_for_selector(".screen.calendar", timeout=10_000)
    page.wait_for_timeout(600)


def level_of(page, iso: str) -> int:
    cls = page.locator(f'.cal-day[aria-label="{iso}"]').get_attribute("class") or ""
    m = re.search(r"\blv(\d)\b", cls)
    return int(m.group(1)) if m else -1


def log_set(base, workout_id, exercise_id, n, weight_kg, tag, *, reps=None, duration_seconds=None):
    payload = {
        "client_uuid": f"f105-{tag}-{n:04d}",
        "exercise_id": exercise_id,
        "set_number": n,
        "weight_kg": weight_kg,
    }
    if reps is not None:
        payload["reps"] = reps
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds
    api(base, f"/api/workouts/{workout_id}/sets", "POST", payload)


def seed(base: str, today: date) -> dict:
    """五天測資，全放在**上個月**（F85 的老技巧）：保證存在（上個月一定 ≥28 天）、
    不必擔心今天離月初太近讓 5/10/15/20 號落到下個月或未來。分級門檻本身是固定值、
    不再是「當月最大值」相對值，所以不必湊在同一個月才能比——這裡沿用同一招純粹是
    為了讓多天測資一次到位，不是分級演算法要求的。
    """
    reps_ex = api(base, "/api/exercises")[0]
    time_ex = api(base, "/api/exercises", "POST", {
        "name_zh": "測試棒式 F105", "name_en": "Test Plank F105",
        "muscle_group": "核心", "is_bodyweight": True, "mode": "time",
    })

    last_day_prev = today.replace(day=1) - timedelta(days=1)
    prev_month = last_day_prev.replace(day=1)

    def pd(dom: int) -> date:
        return prev_month.replace(day=dom)

    days: dict[str, dict] = {}

    # day 5：只有時間型（40s + 55s）——① 有顏色、明細講「秒」不是「次」
    d5 = pd(5)
    w5 = api(base, "/api/workouts", "POST", {"date": d5.isoformat()})
    log_set(base, w5["id"], time_ex["id"], 1, 0, "d5", duration_seconds=40)
    log_set(base, w5["id"], time_ex["id"], 2, 0, "d5", duration_seconds=55)
    days["time_only"] = {"date": d5, "workout_id": w5["id"]}

    # day 6：完全沒練——跟 day5 對照「有顏色 vs 空白」
    days["empty"] = {"date": pd(6)}

    # day 10：混合（3 組次數型 + 2 組時間型）——② 兩個數字並列不相加
    d10 = pd(10)
    w10 = api(base, "/api/workouts", "POST", {"date": d10.isoformat()})
    for n, (kg, reps) in enumerate([(50.0, 8), (55.0, 8), (45.0, 8)], start=1):
        log_set(base, w10["id"], reps_ex["id"], n, kg, "d10", reps=reps)
    for n, dur in enumerate([20, 30], start=4):
        log_set(base, w10["id"], time_ex["id"], n, 0, "d10", duration_seconds=dur)
    days["mixed"] = {"date": d10}

    # day 15：純次數型——③ 回歸（F105 前的行為不能變）
    d15 = pd(15)
    w15 = api(base, "/api/workouts", "POST", {"date": d15.isoformat()})
    for n, (kg, reps) in enumerate([(60.0, 8), (65.0, 6), (55.0, 8)], start=1):
        log_set(base, w15["id"], reps_ex["id"], n, kg, "d15", reps=reps)
    days["reps_only"] = {"date": d15}

    # day 20：10 組次數型——④ 組數多要落在較高分級
    d20 = pd(20)
    w20 = api(base, "/api/workouts", "POST", {"date": d20.isoformat()})
    for n in range(1, 11):
        log_set(base, w20["id"], reps_ex["id"], n, 40.0, "d20", reps=8)
    days["many_sets"] = {"date": d20}

    return {"reps_ex": reps_ex, "time_ex": time_ex, "days": days}


def main() -> int:  # noqa: PLR0915
    port = free_port()
    db = e2e_tmp() / f"liftlog_f105_cal_{port}.db"
    release = e2e_tmp() / f"liftlog_f105_cal_release_{port}"
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

            data = seed(base, today)
            days = data["days"]

            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            open_calendar(page)
            page.locator(".cal-prev").click()
            page.wait_for_timeout(700)

            iso_time_only = days["time_only"]["date"].isoformat()
            iso_empty = days["empty"]["date"].isoformat()
            iso_mixed = days["mixed"]["date"].isoformat()
            iso_reps_only = days["reps_only"]["date"].isoformat()
            iso_many = days["many_sets"]["date"].isoformat()

            # ---------- ① 只有時間型的一天：有顏色，明細講「N 秒」不是「N 次」 ----------
            cls_time_only = (
                page.locator(f'.cal-day[aria-label="{iso_time_only}"]').get_attribute("class") or ""
            )
            check("lv0" not in cls_time_only, f"① 純時間型日不落在 lv0（{cls_time_only}）")
            bg_time_only = css(page, f'.cal-day[aria-label="{iso_time_only}"]', "background-color")
            bg_empty = css(page, f'.cal-day[aria-label="{iso_empty}"]', "background-color")
            check(bg_time_only != bg_empty,
                  f"① 純時間型日底色與空白日不同（{bg_time_only} vs {bg_empty}）")

            page.locator(f'.cal-day[aria-label="{iso_time_only}"]').click()
            page.wait_for_timeout(900)
            chips = page.locator(".cal-ex-block").first.locator(".set-chip")
            check(chips.count() == 2, f"① 明細顯示 2 組（{chips.count()}）")
            labels = [chips.nth(i).inner_text() for i in range(2)]
            check(all("秒" in t and "次" not in t for t in labels),
                  f"① chip 顯示「N 秒」不是「N 次」（{labels}）")
            check(any(t == "55秒 ★" for t in labels), f"① 較長那組加 ★（{labels}）")
            dur_span = page.locator(".cal-detail-head .n-duration")
            dur_txt = dur_span.inner_text() if dur_span.count() else "(無)"
            check(dur_span.count() == 1 and dur_txt == "95 秒",
                  f"① 純時間型日仍顯示總秒數（{dur_txt}）")

            # ---------- ② 混合日：噸位與總秒數並列不相加 ----------
            page.locator(f'.cal-day[aria-label="{iso_mixed}"]').click()
            page.wait_for_timeout(900)
            tonnage_txt = page.locator(".cal-detail-head .n:not(.n-duration)").inner_text()
            duration_txt = page.locator(".cal-detail-head .n-duration").inner_text()
            check(tonnage_txt == "1,200 kg", f"② 噸位只算次數型（{tonnage_txt}）")
            check(duration_txt == "50 秒", f"② 總秒數另外顯示（{duration_txt}）")
            check("1200" not in duration_txt and "50" not in tonnage_txt,
                  f"② 兩個數字沒有被加在一起（{tonnage_txt} / {duration_txt}）")

            # ---------- ③ 純次數型日行為不變（回歸） ----------
            page.locator(f'.cal-day[aria-label="{iso_reps_only}"]').click()
            page.wait_for_timeout(900)
            reps_only_n = page.locator(".cal-detail-head .n:not(.n-duration)").inner_text()
            check(reps_only_n == "1,310 kg", f"③ 純次數型日噸位不變（{reps_only_n}）")
            check(page.locator(".cal-detail-head .n-duration").count() == 0,
                  "③ 純次數型日不多顯示秒數欄位")
            chip0 = page.locator(".cal-ex-block").first.locator(".set-chip").first.inner_text()
            check(bool(re.fullmatch(r"[\d.]+×\d+( ★)?", chip0)), f"③ 組 chip 格式不變（{chip0}）")
            page.locator(".cal-ex-block").first.locator(".set-chip").first.click()
            page.wait_for_timeout(500)
            check(page.locator(".cal-edit-modal .stepper .name", has_text="REPS").count() == 1,
                  "③ 次數型組編輯 modal 仍顯示 REPS stepper（不受時間型影響）")
            page.locator(".cal-edit-modal .modal-cancel").click()
            page.wait_for_timeout(400)

            # ---------- ④ 分級：組數多的日子級別 >= 組數少的日子 ----------
            lv_many = level_of(page, iso_many)
            lv_few = level_of(page, iso_time_only)
            check(lv_many >= lv_few > 0, f"④ 10 組的分級 >= 2 組的分級（{lv_many} vs {lv_few}）")

            # ---------- ⑤ 凍結契約：編輯時間型組送 duration_seconds、不誤觸 422 ----------
            page.locator(f'.cal-day[aria-label="{iso_time_only}"]').click()
            page.wait_for_timeout(900)
            # 40 秒那組（非最佳，避免跟 ★ 邏輯混在一起驗）
            page.locator(".cal-ex-block").first.locator(".set-chip").first.click()
            page.wait_for_timeout(600)
            check(page.locator(".cal-edit-modal .stepper .name", has_text="秒").count() == 1,
                  "⑤ 編輯時間型組顯示「秒」stepper 而非 REPS")
            page.locator(".cal-edit-modal .stepper", has_text="秒").get_by_role(
                "button", name="+5").click()
            page.wait_for_timeout(200)
            page.locator(".cal-edit-save").click()
            page.wait_for_timeout(1200)
            check(page.locator(".cal-edit-modal").count() == 0,
                  "⑤ 儲存成功、modal 正常關閉（沒有誤觸 422）")
            check(page.locator(".error-banner").count() == 0, "⑤ 沒有殘留錯誤訊息")
            new_labels = [
                page.locator(".cal-ex-block").first.locator(".set-chip").nth(i).inner_text()
                for i in range(2)
            ]
            check("45秒" in new_labels, f"⑤ 畫面即時反映新秒數（{new_labels}）")
            server_sets = api(base, f"/api/workouts/{days['time_only']['workout_id']}")["sets"]
            edited = next((s for s in server_sets if s["duration_seconds"] == 45), None)
            check(edited is not None and edited["reps"] is None,
                  f"⑤ 伺服器端 duration_seconds 更新、reps 仍是 null（{edited}）")

            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        for path in (db, db.with_suffix(".db-wal"), db.with_suffix(".db-shm")):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass  # Windows：伺服器行程剛結束時檔案可能還被握著，留著不影響下次（檔名帶 port）
        for f in release.glob("*"):
            f.unlink()
        release.rmdir()

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    for label in failed:
        print(f"  FAIL: {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
