"""F86 E2E：動作表現改版（PR 卡 ＋ 每次最佳組長條圖），①–⑧。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f86.py`

⚠ 量測一律問**渲染結果**（getComputedStyle／bounding_box／實際文字），不問 class 名稱。
handoff 記過四次假綠，型態都是「問了 class，class 在，但東西是壞的」——
F84 的停止鈕警示色從 F73 起就沒生效，測試卻一直綠，就是這樣來的。

⚠ 圖表的斷言要能分辨「有畫」與「畫對」：長條高度比例、PR 那幾根的顏色，
都拿實際樣式來比，不看有沒有 .pr 這個 class。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    TOKEN,
    safe_port,
    setup_and_home,
    start_server,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as exc:  # 種子失敗時要看得到伺服器說什麼，不然只有一句 400
        raise AssertionError(f"{method} {path} → {exc.code}: {exc.read().decode()[:300]}") from None
    return json.loads(raw) if raw.strip() else None


def seed(base: str) -> None:
    """五次訓練，重量一路上升——這樣「累進 PR」才有東西可標（不是每根都是 PR）。

    刻意讓第 3 次比第 2 次輕：那一根不該掛獎盃，否則「全部都標」也會通過。
    """
    exercises = api(base, "GET", "/api/exercises")
    squat = next(e for e in exercises if e["name_en"].lower() == "squat")
    plan = [
        (30, [(60, 8), (60, 7)]),
        (24, [(65, 8), (62.5, 8)]),
        (18, [(62.5, 8), (60, 9)]),   # 比上次輕：不是 PR
        (12, [(70, 6), (67.5, 6)]),
        (5, [(75, 5), (72.5, 5)]),
    ]
    for days_ago, sets in plan:
        day = (date.today() - timedelta(days=days_ago)).isoformat()
        workout = api(base, "POST", "/api/workouts", {"date": day})
        for i, (weight, reps) in enumerate(sets, start=1):
            api(base, "POST", f"/api/workouts/{workout['id']}/sets", {
                "client_uuid": f"f86-seed-{days_ago:03d}-{i}",
                "exercise_id": squat["id"],
                "set_number": i,
                "weight_kg": weight,
                "reps": reps,
                "rpe": 7,
            })


def open_detail(page) -> None:
    """底部導覽「表現」→ 選部位 → 選動作。"""
    page.locator(".bottom-nav").get_by_role("button", name="表現").click()
    page.wait_for_timeout(900)
    page.get_by_role("button", name="腿").first.click()
    page.wait_for_timeout(700)
    page.get_by_role("button", name="深蹲").first.click()
    page.wait_for_selector(".exercise-detail", timeout=8000)
    page.wait_for_timeout(600)


def css(page, selector: str, prop: str) -> str:
    return page.eval_on_selector(selector, "(e, p) => getComputedStyle(e)[p]", prop)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f86-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        seed(base)
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


def run_checks(base: str) -> None:  # noqa: C901
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        open_detail(page)

        accent = css(page, ".range-pill.on", "backgroundColor")

        # ① 頁頭
        check(page.locator(".exercise-detail .screen-head .back-btn svg").count() == 1,
              "① 頁頭返回鍵是向量圖示（icons.js），不是字元")
        sub = page.locator(".exercise-detail .screen-head .st").inner_text()
        check("Squat" in sub and "次紀錄" in sub,
              f"① 副標＝英文別名 · N 次紀錄（實際：{sub}）")

        # ② 三張 PR 卡
        cards = page.locator(".pr-card")
        check(cards.count() == 3, f"② PR 卡三張橫排（實際 {cards.count()} 張）")
        boxes = [cards.nth(i).bounding_box() for i in range(cards.count())]
        widths = [round(b["width"]) for b in boxes]
        check(max(widths) - min(widths) <= 2, f"② 三張等寬（flex:1）：{widths}")
        check(len({round(b["y"]) for b in boxes}) == 1, "② 三張在同一列")
        first_bg = css(page, ".pr-card:nth-child(1)", "backgroundColor")
        rest_bg = css(page, ".pr-card:nth-child(2)", "backgroundColor")
        check(first_bg != rest_bg, f"② 第一張用 --card-hi 站出來（{first_bg} vs {rest_bg}）")
        check(css(page, ".pr-card:nth-child(1) .pr-v", "color") == accent,
              "② 第一張的數值是 --accent")
        check(css(page, ".pr-card .pr-v", "fontSize") == "26px",
              f"② 數值 26px（實際 {css(page, '.pr-card .pr-v', 'fontSize')}）")
        check(css(page, ".pr-card .pr-k", "fontSize") == "10px", "② 標籤 10px")

        labels = [
            page.locator(".pr-card .pr-k").nth(i).inner_text().strip()
            for i in range(3)
        ]
        check(labels == ["推估 1RM", "最重", "單次量"],
              f"② 三張分別是推估 1RM／最重／單次量（{labels}）")
        # 數值要對得上種子資料：最重 75；推估 1RM = 75×(1+5/30)=87.5 → 88
        values = [page.locator(".pr-card .pr-v").nth(i).inner_text().strip() for i in range(3)]
        check(values[1].startswith("75"), f"② 「最重」＝種子資料的 75kg（實際 {values[1]}）")
        check(values[0].startswith("88"),
              f"② 「推估 1RM」＝Epley 87.5 四捨五入 88（實際 {values[0]}）")

        # ③ 五顆等寬藥丸、無自訂
        pills = page.locator(".range-pill")
        texts = [pills.nth(i).inner_text().strip() for i in range(pills.count())]
        check(texts == ["1M", "3M", "6M", "1Y", "全部"], f"③ 五顆檔位（實際 {texts}）")
        check(not page.locator(".ex-custom, button:has-text('自訂')").count(),
              "③ 「自訂」檔位已移除")
        pboxes = [pills.nth(i).bounding_box() for i in range(pills.count())]
        check(all(b["width"] >= 44 and b["height"] >= 44 for b in pboxes),
              "③ 五顆的觸控目標寬高皆 ≥44px："
              f"{[(round(b['width']), round(b['height'])) for b in pboxes]}")
        check(max(round(b["width"]) for b in pboxes) - min(round(b["width"]) for b in pboxes) <= 2,
              "③ 五顆等寬")

        # ④ 資料不足的檔位灰掉但仍可點
        one_month = pills.nth(0)
        one_year = pills.nth(3)
        check(float(css(page, ".range-pill:nth-child(4)", "opacity")) < 0.5,
              "④ 超出資料範圍的檔位（1Y）灰掉")
        one_year.click()
        page.wait_for_timeout(700)
        note = page.locator(".range-note")
        check(note.count() == 1 and "最早" in note.inner_text(),
              f"④ 點灰掉的檔位會說明最早紀錄日（{note.inner_text() if note.count() else '(無)'}）")
        one_month.click()
        page.wait_for_timeout(900)
        check(page.locator(".range-pill.on").inner_text().strip() == "1M",
              "④ 可用的檔位點了會切換")

        # 切回「全部」看完整資料
        pills.nth(4).click()
        page.wait_for_timeout(900)

        # ⑤ 每次最佳組折線圖（F134 取代長條圖；F86 ⑤ 條文標 superseded_by: F134，
        # 這段 E2E 改驗折線圖，但 .bars-max／.bars-foot 的斷言必須留著——F134 明文
        # 要求那兩處資訊不得消失。詳細的點選互動由 verify_f134.py 驗，這裡只驗
        # 「圖表本身畫對了」這件事，避免兩支測試重複覆蓋同一批斷言。）
        check(page.locator(".bars-card").count() == 1, "⑤ 圖表卡存在")
        check(page.locator(".bars-card .bar, .bars-card .bar-col").count() == 0,
              "⑤ 舊的長條圖 DOM（.bar／.bar-col）已移除")
        pts = page.locator(".line-pt")
        check(pts.count() == 5, f"⑤ 五次訓練＝五個資料點（實際 {pts.count()}）")
        check(page.locator(".line-path").count() == 1, "⑤ 五個點以一條折線相連")
        ys = [pts.nth(i).bounding_box()["y"] for i in range(5)]
        check(ys[4] < ys[0], "⑤ 最重那次（最後一次 75kg）的點比第一次（60kg）高（y 座標較小）")
        chart_top = page.locator(".line-chart").bounding_box()["y"]
        check(min(ys) >= chart_top - 0.5,
              f"⑤ 最高點沒有被容器上緣裁切（點頂 {min(ys):.1f}, 容器頂 {chart_top:.1f}）")
        # PR 那幾點才有獎盃節點；第三次（比上次輕）不該有
        check(page.locator(".line-flag").count() == 4,
              f"⑤ 四次突破各一個獎盃圖示（實際 {page.locator('.line-flag').count()}）")
        head_max = page.locator(".bars-max").inner_text().strip()
        check(head_max.startswith("75"), f"⑤ 標題列右側是區間最大值（實際 {head_max}）")
        foot = page.locator(".bars-foot").inner_text()
        check("月" in foot and "個人紀錄" in foot, f"⑤ 底部三段標示（實際 {foot!r}）")

        # ⑥ 歷來紀錄卡
        cardsh = page.locator(".hist-card")
        check(cardsh.count() == 5, f"⑥ 五張歷來紀錄卡（實際 {cardsh.count()}）")
        head = cardsh.first.locator(".hist-head").inner_text()
        check("天前" in head and "kg" in head, f"⑥ 日期＋相對天數＋右側總量（實際 {head!r}）")
        chips = cardsh.first.locator(".set-chip")
        check(chips.count() == 2, f"⑥ 每組一顆 chip（實際 {chips.count()}）")
        best_bg = css(page, ".hist-card:nth-child(1) .set-chip.best", "backgroundColor")
        plain_bg = css(page, ".hist-card:nth-child(1) .set-chip:not(.best)", "backgroundColor")
        check(best_bg == accent and plain_bg != accent,
              f"⑥ 當次最佳組用 --accent 底（{best_bg} vs {plain_bg}）")
        check(page.locator(".hist-card .set-chip.best svg").count() >= 1,
              "⑥ 最佳組 chip 尾綴獎盃圖示")
        check(page.locator(".hist-card .set-chip.best").count() == 5,
              "⑥ 每張卡各標一顆最佳組（不是整頁只標一顆，也不是同重量標兩顆）")

        # ⑦ 不再有 ★ 字元
        body_text = page.locator(".exercise-detail").inner_text()
        check("★" not in body_text and "🏆" not in body_text,
              "⑦ PR 標記不再出現 ★／🏆 字元（改用向量圖示）")
        sw = (Path(__file__).resolve().parents[2] / "app/static/sw.js").read_text(encoding="utf-8")
        check('"/js/icons.js"' in sw, "⑦ icons.js 在 SW SHELL 內（沒有新增檔案，但確認沒漏）")

        # ⑧ 觸控目標與水平捲動
        small = page.evaluate(
            """() => [...document.querySelectorAll('.exercise-detail button')]
                 .map(b => ({ t: b.innerText.trim().slice(0, 12),
                              w: b.getBoundingClientRect().width,
                              h: b.getBoundingClientRect().height }))
                 .filter(x => x.w < 44 || x.h < 44)"""
        )
        check(not small, f"⑧ 頁內按鈕觸控區皆 ≥44px（不足：{small}）")
        check(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"),
              "⑧ 無水平捲動")

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
