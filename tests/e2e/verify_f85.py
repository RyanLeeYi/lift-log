"""F85 驗證：日曆改版（熱力卡 ＋ 當日明細卡 ＋ 組 chips）。

跑法：`uv run python tests/e2e/verify_f85.py`

這支測試的重點放在**量渲染結果**而不是查 class：F84 的教訓是
「class 掛上去了但 specificity 被蓋掉」這種缺陷只有 computed style 抓得到。
所以最佳組的琥珀底、選中日的白框、未來日的底色，一律比對實際 rgb 值。
"""

from __future__ import annotations

import json
import re
import sys
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
    e2e_tmp,
    free_port,
    setup_and_home,
    start_from_home,
    start_server,
)

results: list[tuple[bool, str]] = []

# design_handoff 的色票（F78 已抄進 :root）——這裡用 rgb 形式比對 computed style
CARD = "rgb(46, 40, 34)"
CARD_HI = "rgb(59, 52, 44)"
ACCENT = "rgb(217, 178, 95)"
ON_ACCENT = "rgb(36, 30, 20)"
TEXT = "rgb(240, 233, 223)"
HEAT_FUTURE = "rgb(41, 36, 31)"


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
        raise AssertionError(f"{method} {path} → {exc.code}: {exc.read().decode()[:200]}") from None


def css(page, selector: str, prop: str) -> str:
    return page.eval_on_selector(
        selector,
        "(e, p) => getComputedStyle(e).getPropertyValue(p)",
        prop,
    )


# icons.js 的 chevron path（要跟 app/static/js/icons.js 一致）。驗這個而不是驗 `.icon`
# class 數量——第三輪驗收指出：`<span class="icon">` 或貼錯的圖示都能通過數量斷言。
CHEVRON_DOWN = "m6 9 6 6 6-6"
CHEVRON_RIGHT = "m9 18 6-6-6-6"


def chevron_of(locator) -> tuple[str, str]:
    """回傳 (tagName, 第一條 path 的 d)。找不到 svg 時回 ("", "")。"""
    if not locator.count():
        return ("", "")
    return tuple(locator.first.evaluate(
        """e => {
            const svg = e.tagName.toLowerCase() === "svg" ? e : e.querySelector("svg");
            if (!svg) return ["", ""];
            const path = svg.querySelector("path");
            return [svg.tagName.toLowerCase(), path ? path.getAttribute("d") : ""];
        }""",
    ))


def open_calendar(page) -> None:
    page.locator(".bottom-nav").get_by_role("button", name="日曆").click()
    page.wait_for_selector(".screen.calendar", timeout=10_000)
    page.wait_for_timeout(600)


def seed(base: str, today: date) -> dict:
    """三個動作、一份課表、一場今天的訓練（第一個動作 3 組、其餘各 2 組）。"""
    exercises = api(base, "/api/exercises")[:3]
    ids = [e["id"] for e in exercises]
    tpl = api(base, "/api/templates", "POST", {
        "name": "腿日",
        "exercises": [{"exercise_id": i, "default_sets": 3} for i in ids],
    })
    w = api(base, "/api/workouts", "POST", {"date": today.isoformat(), "template_id": tpl["id"]})
    # 第一個動作三組，中間那組最重（最佳組不能剛好是第一或最後一顆，否則「挑對了嗎」測不出來）
    for n, (kg, reps) in enumerate([(80.0, 8), (85.0, 6), (70.0, 8)], start=1):
        api(base, f"/api/workouts/{w['id']}/sets", "POST", {
            "client_uuid": f"f85-aaaa-{n:04d}", "exercise_id": ids[0],
            "set_number": n, "weight_kg": kg, "reps": reps,
        })
    for idx, ex_id in enumerate(ids[1:], start=1):
        for n in range(1, 3):
            api(base, f"/api/workouts/{w['id']}/sets", "POST", {
                "client_uuid": f"f85-b{idx}-{n:04d}", "exercise_id": ex_id,
                "set_number": n, "weight_kg": 40.0 + n, "reps": 10,
            })
    api(base, "/api/daily-status", "POST", {
        "date": today.isoformat(), "energy": 3, "sleep_quality": 4, "note": "腰有點緊",
    })

    # F115：**這些日子全部放進上個月，不是「今天往前推幾天」。**
    # 原本用 today-7/-8/-9 與 today-3，月初跑就會滑到上個月——2026-08-01 那天
    # 「① 副標 5 天」「① 上個月 0 天」「① 下個月鈕切得回來」三條同時變紅，
    # 而產品完全沒有問題。測試自己造資料就該自己決定月份，不能假設今天離月初夠遠、
    # 也不能假設上個月是空的。
    #
    # 上個月是**整個都在過去**的一個月，且必定有 ≥28 天，所以 5/10/15/20/25 號永遠存在、
    # 永遠可點。熱力分級要「同一個月內比噸位」，四階因此要湊在同一個月裡——
    # 上個月放四天（含當月最大的那天），今天所在的月份只有今天一天（自己就是最大 → lv4）。
    last_day_prev = today.replace(day=1) - timedelta(days=1)
    prev_month = last_day_prev.replace(day=1)

    def prev_day(dom: int) -> date:
        return prev_month.replace(day=dom)

    # 上個月的最大噸位＝335×10＝3350（20 號）；其餘取約 20% / 45% / 70% 落在 lv1 / lv2 / lv3
    graded: dict[str, int] = {}
    for dom, (kg, reps, want) in {
        5: (67.0, 10, 1), 10: (150.0, 10, 2), 15: (235.0, 10, 3), 20: (335.0, 10, 4),
    }.items():
        day = prev_day(dom)
        wk = api(base, "/api/workouts", "POST", {"date": day.isoformat()})
        api(base, f"/api/workouts/{wk['id']}/sets", "POST", {
            "client_uuid": f"f85-lv{want}-0001", "exercise_id": ids[0],
            "set_number": 1, "weight_kg": kg, "reps": reps,
        })
        graded[day.isoformat()] = want

    # 「有訓練、但沒有課表」的一天：標題只該有日期，不該多出「· 課表名」
    plain_day = prev_day(25)
    plain = api(base, "/api/workouts", "POST", {"date": plain_day.isoformat()})
    # 兩組同重量不同次數 → 驗「平手取次數多者」為最佳組
    for n, (kg, reps) in enumerate([(90.0, 5), (90.0, 7)], start=1):
        api(base, f"/api/workouts/{plain['id']}/sets", "POST", {
            "client_uuid": f"f85-tie-{n:04d}", "exercise_id": ids[1],
            "set_number": n, "weight_kg": kg, "reps": reps,
        })
    return {
        "exercises": exercises, "workout": w, "graded": graded,
        "plain_day": plain_day, "plain": plain, "prev_month": prev_month,
    }


def main() -> int:  # noqa: C901, PLR0915
    port = free_port()
    db = e2e_tmp() / f"liftlog_f85_{port}.db"
    release = e2e_tmp() / f"liftlog_f85_release_{port}"
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
            exercises = data["exercises"]
            graded = data["graded"]
            plain_day = data["plain_day"]

            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            open_calendar(page)

            # ---------- ① 頁頭 ----------
            head = page.locator(".screen.calendar .screen-head")
            check(head.count() == 1, "① 日曆用全站 .screen-head")
            check(head.locator("h1").inner_text() == "訓練日曆",
                  f"① 標題「訓練日曆」（{head.locator('h1').inner_text()}）")
            sub = head.locator(".st").inner_text()
            # F115：本月只有今天一天有訓練（其餘測資刻意放在上個月，見 seed 的註解）
            expect_sub = f"{today.year}年{today.month}月 · 1 天"
            check(sub == expect_sub, f"① 副標「年月 · N 天」（{sub}）")
            check(head.locator(".back-btn").count() == 1, "① 左上返回鈕在標頭內")
            check(head.locator(".back-btn .icon").count() == 1, "① 返回鈕用 icons.js 圖示")

            # 切月：副標與格子要跟著換
            page.locator(".cal-prev").click()
            page.wait_for_timeout(700)
            prev_month = (today.replace(day=1) - timedelta(days=1))
            sub_prev = head.locator(".st").inner_text()
            check(sub_prev.startswith(f"{prev_month.year}年{prev_month.month}月"),
                  f"① 上個月鈕切得動（{sub_prev}）")
            # 上個月有 5 天（4 個熱力階 ＋ 1 天無課表的訓練），數字由 seed 決定而不是碰運氣
            expect_prev_days = len(graded) + 1
            check(f" · {expect_prev_days} 天" in sub_prev,
                  f"① 切月後訓練日數＝該月實際天數（期望 {expect_prev_days}，得到 {sub_prev}）")
            days_prev = page.locator(".cal-day").count()
            expected_prev = (today.replace(day=1) - timedelta(days=1)).day
            check(days_prev == expected_prev,
                  f"① 切月後格子數＝該月天數（{days_prev} vs {expected_prev}）")
            page.locator(".cal-next").click()
            page.wait_for_timeout(700)
            check(head.locator(".st").inner_text() == expect_sub, "① 下個月鈕切得回來")

            # ---------- ② 格子容器與星期表頭 ----------
            check(page.locator(".cal-card").count() == 1, "② 格子包在卡片容器內")
            check(css(page, ".cal-card", "background-color") == CARD,
                  f"② 卡片底色＝--card（{css(page, '.cal-card', 'background-color')}）")
            check(css(page, ".cal-card", "border-radius") == "22px",
                  f"② 卡片圓角＝--r-card 22px（{css(page, '.cal-card', 'border-radius')}）")
            wd = [page.locator(".cal-wd").nth(i).inner_text() for i in range(7)]
            check(wd == list("日一二三四五六"), f"② 星期表頭週日起始（{''.join(wd)}）")

            # 前置空白格數＝1 號的星期（週日 = 0）
            first_dow = date(today.year, today.month, 1).weekday()  # Mon=0
            expect_blank = (first_dow + 1) % 7  # 轉成週日起始
            grid_children = page.eval_on_selector(
                ".cal-grid", "e => [...e.children].map(c => c.className)")
            blanks = sum(1 for c in grid_children[7:] if c == "")
            leading = 0
            for c in grid_children[7:]:
                if c:
                    break
                leading += 1
            check(leading == expect_blank,
                  f"② 前置空白格＝1 號的星期（{leading} vs {expect_blank}；總空白 {blanks}）")

            # ---------- ③ 格子樣式 ----------
            check(css(page, ".cal-grid", "grid-template-columns").count(" ") == 6,
                  "③ 7 欄 grid")
            gap = css(page, ".cal-grid", "gap")
            check(gap == "6px", f"③ gap 6px（{gap}）")
            ratio = css(page, ".cal-day", "aspect-ratio")
            check(ratio.replace(" ", "") in ("1", "1/1"), f"③ aspect-ratio 1（{ratio}）")
            check(css(page, ".cal-day", "border-radius") == "10px",
                  f"③ 圓角 --r-cell 10px（{css(page, '.cal-day', 'border-radius')}）")
            check("IBM Plex Mono" in css(page, ".cal-day", "font-family"),
                  f"③ 格子走 mono（{css(page, '.cal-day', 'font-family')}）")
            today_cell = page.locator(f'.cal-day[aria-label="{today.isoformat()}"]')
            box_before = today_cell.bounding_box()
            check(css(page, f'.cal-day[aria-label="{today.isoformat()}"]', "border-top-width")
                  == "2px", "③ 未選中已預留 2px 邊寬")
            today_cell.click()
            page.wait_for_timeout(900)
            box_after = today_cell.bounding_box()
            sel_color = css(page, ".cal-day.sel", "border-top-color")
            check(sel_color == TEXT, f"③ 選中框＝--text（{sel_color}）")
            check(abs(box_before["width"] - box_after["width"]) < 0.5
                  and abs(box_before["height"] - box_after["height"]) < 0.5,
                  f"③ 選取前後尺寸不變（{box_before['width']:.1f} → {box_after['width']:.1f}）")

            # ---------- ④ 熱力階與未來日 ----------
            check(page.locator(f'.cal-day[aria-label="{today.isoformat()}"].lv4').count() == 1,
                  "④ 當月噸位最大的一天 → lv4")
            # F115：四個熱力階都在上個月（熱力是「同月內比噸位」，四階必須湊在同一個月）。
            # 切過去驗完再切回來——後面的未來日／明細檢查都以當月為前提。
            page.locator(".cal-prev").click()
            page.wait_for_timeout(700)
            for iso, want in graded.items():
                cls = page.locator(f'.cal-day[aria-label="{iso}"]').get_attribute("class")
                check(f"lv{want}" in cls, f"④ {iso} 依噸位落在 lv{want}（{cls}）")
            # 五階要真的看得出來：四個底色兩兩不同，否則「分 5 階」只是 class 名稱
            heats = [
                css(page, f'.cal-day[aria-label="{iso}"]', "background-color")
                for iso in graded
            ]
            check(len(set(heats)) == 4, f"④ lv1–lv4 底色互不相同（{heats}）")
            page.locator(".cal-next").click()
            page.wait_for_timeout(700)
            # 切月會清掉選取（明細卡跟著消失），⑤ 以「今天被選中」為前提 → 重新點一次
            page.locator(f'.cal-day[aria-label="{today.isoformat()}"]').click()
            page.wait_for_timeout(700)
            future = today + timedelta(days=1)
            if future.month != today.month:
                check(True, "④ 本月最後一天：未來日測試改在下個月（跳過本頁）")
            else:
                fut_sel = f'.cal-day[aria-label="{future.isoformat()}"]'
                check(page.locator(fut_sel + ".future").count() == 1, "④ 未來日掛 .future")
                fut_bg = css(page, fut_sel, "background-color")
                check(fut_bg == HEAT_FUTURE, f"④ 未來日底色＝--heat-future（{fut_bg}）")
                past_empty = None
                for d in range(1, today.day):
                    cand = date(today.year, today.month, d)
                    if page.locator(f'.cal-day[aria-label="{cand.isoformat()}"]').count():
                        past_empty = cand
                        break
                if past_empty:
                    past_bg = css(page, f'.cal-day[aria-label="{past_empty.isoformat()}"]',
                                  "background-color")
                    check(past_bg == CARD and past_bg != fut_bg,
                          f"④ 過去沒練＝--card，與未來日可區分（{past_bg} vs {fut_bg}）")
                else:
                    check(True, "④ 今天是 1 號：本月沒有「過去沒練」的格子可比（跳過）")

            # ---------- ⑤ 當日明細卡 ----------
            detail = page.locator(".cal-detail")
            check("card" in (detail.get_attribute("class") or ""), "⑤ 明細是一張卡")
            check(css(page, ".cal-detail", "background-color") == CARD,
                  f"⑤ 明細底色＝--card（{css(page, '.cal-detail', 'background-color')}）")
            title = detail.locator(".cal-detail-head .d").inner_text()
            check(title == f"{today.month}月{today.day}日 · 腿日",
                  f"⑤ 標題「M月D日 · 課表名」（{title}）")
            tonnage = detail.locator(".cal-detail-head .n").inner_text()
            # 80×8 + 85×6 + 70×8 + (41+42)×10 ×2 動作 = 3370 kg
            check(re.fullmatch(r"[\d,]+ kg", tonnage) and "3,370" in tonnage,
                  f"⑤ 右側總噸位（{tonnage}）")
            # F115：無課表那天也在上個月（見 seed）——切過去點它，驗完切回來
            page.locator(".cal-prev").click()
            page.wait_for_timeout(700)
            page.locator(f'.cal-day[aria-label="{plain_day.isoformat()}"]').click()
            page.wait_for_timeout(900)
            plain_title = page.locator(".cal-detail-head .d").inner_text()
            check(plain_title == f"{plain_day.month}月{plain_day.day}日",
                  f"⑤ 有訓練但無課表 → 標題只有日期（{plain_title}）")
            # ⑦ 同重量平手取次數多者（90×7 勝過 90×5）
            tie = page.locator(".cal-ex-block").first
            best_tie = tie.locator(".set-chip.best").inner_text()
            check(best_tie == "90×7 ★", f"⑦ 最重相同時取次數多者（{best_tie}）")
            page.locator(".cal-next").click()
            page.wait_for_timeout(700)
            page.locator(f'.cal-day[aria-label="{today.isoformat()}"]').click()
            page.wait_for_timeout(900)

            n_color = css(page, ".cal-detail-head .n", "color")
            check(n_color == ACCENT, f"⑤ 噸位用 --accent（{n_color}）")
            check("IBM Plex Mono" in css(page, ".cal-detail-head .n", "font-family"),
                  "⑤ 噸位走 mono")

            # ---------- ⑥ 狀態 chips ----------
            chips = page.locator(".cal-status .status-chip")
            texts = [chips.nth(i).inner_text() for i in range(chips.count())]
            check(texts == ["睡眠 4/5", "狀態 3/5", "腰有點緊"], f"⑥ 三顆狀態 chip（{texts}）")
            check(css(page, ".cal-status .status-chip", "background-color") == CARD_HI,
                  "⑥ chip 底＝--card-hi")
            check(css(page, ".cal-status .status-chip", "border-radius") == "99px",
                  "⑥ chip 圓角 r99")
            check(page.locator(".cal-status .status-edit").count() == 1
                  and page.locator(".cal-status .status-del").count() == 1,
                  "⑥ F18 的編輯與刪除入口都還在")
            # 「編輯入口打得開」證不了編輯能用——第三輪驗收指出：表單開得起來但儲存壞掉的話
            # 這條照樣全綠。所以改成真的改一個值、存檔、再回頭問伺服器。
            page.locator(".cal-status .status-edit").click()
            page.wait_for_timeout(400)
            check(page.locator(".cal-status.editing").count() == 1,
                  "⑥ 編輯入口打得開（F18 不回歸）")
            page.locator(".cal-status.editing .status-field").nth(0).locator(
                "button", has_text="5").click()  # 精力 3 → 5
            page.wait_for_timeout(300)
            page.locator(".cal-status.editing .edit-actions .btn-primary").click()
            page.wait_for_timeout(1400)
            edited = [
                page.locator(".cal-status .status-chip").nth(i).inner_text()
                for i in range(page.locator(".cal-status .status-chip").count())
            ]
            check("狀態 5/5" in edited, f"⑥ 存檔後 chip 顯示新值（{edited}）")
            saved = api(base, f"/api/daily-status?start={today}&end={today}")
            check(saved and saved[0]["energy"] == 5,
                  f"⑥ 伺服器端狀態確實更新（{saved}）")

            # ---------- ⑦⑧ 動作區塊與組 chips ----------
            blocks = page.locator(".cal-ex-block")
            check(blocks.count() == 3, f"⑦ 三個動作三個區塊（{blocks.count()}）")
            check(blocks.first.locator(".ex-name").inner_text() == exercises[0]["name_zh"],
                  "⑦ 區塊標題是動作名")
            check(blocks.first.locator(".ex-sum").inner_text() == "3 組",
                  f"⑦ 標題列顯示組數（{blocks.first.locator('.ex-sum').inner_text()}）")
            check(blocks.first.locator(".set-chip").count() == 3, "⑧ 第一個動作預設展開")
            check(blocks.nth(1).locator(".set-chip").count() == 0, "⑧ 第二個動作預設收合")
            check(blocks.nth(2).locator(".set-chip").count() == 0, "⑧ 第三個動作預設收合")
            collapsed_text = blocks.nth(1).inner_text().strip()
            check(collapsed_text == f"{exercises[1]['name_zh']}\n2 組",
                  f"⑧ 收合列只有動作名與組數（{collapsed_text!r}）")
            check(blocks.nth(1).locator(".ex-caret .icon").count() == 1,
                  "⑧ 收合列有指示符")
            labels = [blocks.first.locator(".set-chip").nth(i).inner_text() for i in range(3)]
            check(labels[0] == "80×8" and labels[2] == "70×8",
                  f"⑦ 組 chip 顯示「重量×次數」（{labels}）")
            check(labels[1] == "85×6 ★", f"⑦ 最佳組尾綴 ★（{labels[1]}）")
            best_bg = css(page, ".set-chip.best", "background-color")
            best_fg = css(page, ".set-chip.best", "color")
            check(best_bg == ACCENT, f"⑦ 最佳組填 --accent（{best_bg}）")
            check(best_fg == ON_ACCENT, f"⑦ 最佳組字＝--on-accent（{best_fg}）")
            check(css(page, ".cal-ex-block .set-chip:not(.best)", "background-color") == CARD_HI,
                  "⑦ 一般組 chip 底＝--card-hi")
            check(css(page, ".set-chip", "border-radius") == "99px", "⑦ 組 chip r99")
            check("IBM Plex Mono" in css(page, ".set-chip", "font-family"), "⑦ 組 chip 走 mono")

            # ⑧ 點標題切換展開／收合
            blocks.nth(1).locator(".cal-detail-ex").click()
            page.wait_for_timeout(500)
            check(page.locator(".cal-ex-block").nth(1).locator(".set-chip").count() == 2,
                  "⑧ 點標題可展開（F34 行為不變）")
            page.locator(".cal-ex-block").nth(1).locator(".cal-detail-ex").click()
            page.wait_for_timeout(500)
            check(page.locator(".cal-ex-block").nth(1).locator(".set-chip").count() == 0,
                  "⑧ 再點可收合")

            # ---------- ⑩ chevron 圖示 ----------
            # 要驗到「是 svg，而且是 chevron 那條 path」——展開與收合還要指向不同方向，
            # 否則兩顆都貼同一個圖示也會過
            tag, d = chevron_of(page.locator(".cal-ex-block").nth(0).locator(".ex-caret"))
            check(tag == "svg" and d == CHEVRON_DOWN,
                  f"⑩ 展開中的指示符是 chevron-down svg（{tag} / {d}）")
            tag2, d2 = chevron_of(page.locator(".cal-ex-block").nth(1).locator(".ex-caret"))
            check(tag2 == "svg" and d2 == CHEVRON_RIGHT,
                  f"⑩ 收合中的指示符是 chevron-right svg（{tag2} / {d2}）")
            js_dir = REPO / "app" / "static" / "js"
            offenders = [
                f.name for f in js_dir.glob("*.js")
                if "▾" in f.read_text(encoding="utf-8") or "▸" in f.read_text(encoding="utf-8")
            ]
            check(not offenders, f"⑩ app/static/js 內不再有 ▾／▸ 字元（{offenders}）")

            # ⑩ 批次確認列（補記 → 用課表）也要是 icons.js 的 chevron
            page.locator(".cal-add-toggle").click()
            page.wait_for_timeout(600)
            page.locator(".cal-add-mode .chip", has_text="用課表").click()
            page.wait_for_timeout(900)
            page.locator(".cal-tpl-item").first.click()
            page.wait_for_timeout(900)
            tag3, d3 = chevron_of(page.locator(".cal-batch-row .batch-caret"))
            check(tag3 == "svg" and d3 in (CHEVRON_DOWN, CHEVRON_RIGHT),
                  f"⑩ 批次確認列的指示符是 chevron svg（{tag3} / {d3}）")
            page.locator(".cal-add-modal .modal-cancel").click()
            page.wait_for_timeout(400)
            page.locator(".cal-add-modal .modal-cancel").click()
            page.wait_for_timeout(500)

            # ---------- ⑨ 點 chip 開編輯 modal、改值生效、刪除在 modal 內 ----------
            page.locator(".cal-ex-block").first.locator(".set-chip").first.click()
            page.wait_for_timeout(600)
            check(page.locator(".cal-edit-modal").count() == 1, "⑨ 點組 chip 開 F45 編輯 modal")
            page.locator(".cal-edit-modal .stepper").first.get_by_role(
                "button", name="+").click()
            page.wait_for_timeout(200)
            page.locator(".cal-edit-save").click()
            page.wait_for_timeout(1200)
            check(page.locator(".cal-edit-modal").count() == 0, "⑨ 儲存後 modal 自動關")
            new_label = page.locator(".cal-ex-block").first.locator(".set-chip").first.inner_text()
            check(new_label == "82.5×8", f"⑨ 改值即時生效（{new_label}）")
            sets_now = api(base, f"/api/workouts/{data['workout']['id']}")["sets"]
            check(any(s["weight_kg"] == 82.5 for s in sets_now), "⑨ 伺服器端確實更新")

            page.locator(".cal-ex-block").first.locator(".set-chip").first.click()
            page.wait_for_timeout(600)
            check(page.locator(".cal-edit-del").count() == 1, "⑨ 編輯 modal 內有刪除")
            page.locator(".cal-edit-del").click()
            page.wait_for_timeout(1400)
            check(page.locator(".cal-ex-block").first.locator(".set-chip").count() == 2,
                  "⑨ 單擊即刪（無兩段式確認），畫面即時移除")
            left = [s for s in api(base, f"/api/workouts/{data['workout']['id']}")["sets"]]
            check(len(left) == 6, f"⑨ 伺服器端軟刪生效（剩 {len(left)} 組）")

            # ⑨ F19 選取批次刪除仍可用
            page.locator(".cal-select-toggle").click()
            page.wait_for_timeout(500)
            selectable = page.locator(".set-chip.selectable")
            check(selectable.count() == 6, f"⑨ 選取模式全部展開可勾（{selectable.count()}）")
            selectable.nth(0).click()
            selectable.nth(1).click()
            page.wait_for_timeout(300)
            check(page.locator(".set-chip.selected").count() == 2, "⑨ 可勾選兩顆")
            page.locator(".cal-batch-del").click()
            page.wait_for_timeout(1600)
            left2 = api(base, f"/api/workouts/{data['workout']['id']}")["sets"]
            check(len(left2) == 4, f"⑨ 批次刪除生效（剩 {len(left2)} 組）")

            # ---------- ⑪ 補記入口 ----------
            add = page.locator(".cal-add-toggle")
            check(add.inner_text().strip() == "補記這一天", f"⑪ 文案（{add.inner_text().strip()}）")
            check(css(page, ".cal-add-toggle", "background-color") == "rgba(0, 0, 0, 0)",
                  f"⑪ 透明底（{css(page, '.cal-add-toggle', 'background-color')}）")
            check(css(page, ".cal-add-toggle", "border-top-width") == "1px"
                  and css(page, ".cal-add-toggle", "border-top-color") == "rgb(84, 74, 61)",
                  "⑪ 1px solid var(--line) 外框")
            check(css(page, ".cal-add-toggle", "border-radius") == "99px", "⑪ r99")
            check(css(page, ".cal-add-toggle", "color") == ACCENT, "⑪ 字色 --accent")
            add.click()
            page.wait_for_timeout(600)
            check(page.locator(".cal-add-modal").count() == 1, "⑪ 補記 modal 打得開（F41 不回歸）")
            page.locator(".cal-add-modal .modal-cancel").click()
            page.wait_for_timeout(400)

            # 未來日不給補記入口
            if future.month == today.month:
                page.locator(f'.cal-day[aria-label="{future.isoformat()}"]').click()
                page.wait_for_timeout(900)
                check(page.locator(".cal-add-toggle").count() == 0, "⑪ 未來日不顯示補記入口")
                page.locator(f'.cal-day[aria-label="{today.isoformat()}"]').click()
                page.wait_for_timeout(900)

            # ⑥ 刪除狀態：不是「按鈕在不在」，是按下去之後 chips 與 API 都要沒了
            page.locator(".cal-status .status-del").click()
            page.wait_for_timeout(1400)
            check(page.locator(".cal-status").count() == 0, "⑥ 刪除後狀態列從畫面消失")
            remain = api(base, f"/api/daily-status?start={today}&end={today}")
            check(remain == [], f"⑥ 伺服器端狀態也刪掉了（{remain}）")

            # ⑩ 動作表現頁的月份收合指示符
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(900)
            page.locator(".bottom-nav").get_by_role("button", name="表現").click()
            page.wait_for_timeout(1000)
            # 部位 chip 要逐顆試——第一顆未必是有紀錄的那個部位。第一版只點第一顆，
            # 點到空清單就靜靜往下跑，錯誤看起來像「圖示沒渲染」，其實是根本沒進到那一頁。
            for i in range(page.locator(".trends .chip").count()):
                page.locator(".trends .chip").nth(i).click()
                page.wait_for_timeout(700)
                if page.locator(".trends .exercise-item").count():
                    page.locator(".trends .exercise-item").first.click()
                    page.wait_for_timeout(1600)
                    break
            check(page.locator(".exercise-detail").count() == 1, "⑩ 進得去動作表現頁")
            # F86 取代：動作表現頁的月份摺疊已經拿掉（改成一次訓練一張卡），
            # 所以這裡不再有月份指示符可驗。⑩ 的目的是「展開指示符不用幾何字元」，
            # 剩下的兩處（日曆、體重）仍在上面驗過——不是放寬，是這一處不存在了。
            check(page.locator(".ex-mhead").count() == 0,
                  "⑩ 動作表現頁已無月份摺疊（F86 改成一次訓練一張卡）")
            check(not any(ch in page.locator(".exercise-detail").inner_text() for ch in "▸▾▴◂"),
                  "⑩ 動作表現頁沒有幾何字元指示符殘留")

            # ⑨ logger 側的 🗑 不受這次改版影響（規格明說「logger 側的 🗑 不動」）
            page.locator(".exercise-detail .back-btn").click()
            page.wait_for_timeout(800)
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(900)
            start_from_home(page)
            page.wait_for_timeout(900)
            # 今天沒排程時 start_from_home 會停在「挑今日課表」——課表卡在那裡才是下一步
            if page.locator(".tpl-choice-list").count():
                page.locator(".tpl-choice-card, .free-choice").first.click()
                page.wait_for_timeout(1200)
            page.locator(".menu-card, .pick-list .exercise-item").first.click()
            page.wait_for_timeout(1200)
            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(1200)
            check(page.locator(".done-list .del-set").count() == 1,
                  "⑨ logger done-list 的刪除鈕仍在（未受日曆改版波及）")

            # 收工回日曆量觸控與版面（logger 那一段把畫面帶走了，重新從首頁進來最乾淨）
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1300)
            open_calendar(page)
            page.locator(f'.cal-day[aria-label="{today.isoformat()}"]').click()
            page.wait_for_timeout(1000)

            # ---------- ⑫ 觸控與水平捲動 ----------
            small = []
            for i in range(page.locator("button").count()):
                b = page.locator("button").nth(i)
                if not b.is_visible():
                    continue
                cls = b.get_attribute("class") or ""
                if "cal-day" in cls:
                    continue  # 日曆格是 7 欄等分，尺寸由版面決定（acceptance ⑫ 已排除）
                box = b.bounding_box()
                if box and (box["height"] < 44 or box["width"] < 44):
                    label = (b.inner_text() or b.get_attribute("aria-label") or "?").strip()[:14]
                    small.append(f"{label}({int(box['width'])}x{int(box['height'])})")
            check(not small, f"⑫ 觸控目標 ≥44px（{small}）")
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - window.innerWidth")
            check(overflow <= 1, f"⑫ 無水平捲動（溢出 {overflow}px）")

            # ⑫ :root token 全部有人引用（含新增的 --heat-future）
            app_css = (REPO / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
            root = app_css.split(":root {", 1)[1].split("\n}", 1)[0]
            tokens = re.findall(r"^\s*(--[a-z0-9-]+):", root, re.M)
            dead = [t for t in tokens if f"var({t})" not in app_css]
            check(not dead, f"⑫ :root 沒有死 token（{dead}）")
            check("--heat-future" in tokens and "var(--heat-future)" in app_css,
                  "⑫ --heat-future 已加入且被引用")

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
