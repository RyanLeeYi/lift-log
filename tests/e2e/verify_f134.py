"""F134 E2E：動作表現頁改用可點選的折線圖（取代 F86 ⑤ 的長條圖），①–⑫。

跑法：`uv run python tests/e2e/verify_f134.py`

⚠ 量測一律問**渲染結果**（bounding_box／getAttribute／實際文字），不問 class 名稱有沒有掛上去
（同 verify_f86 的教訓）。

四個情境動作：
- 深蹲（Squat）：沿用 verify_f86.seed 的五筆遞增資料——一般情況、PR 標記、點選切換／關閉。
- 臥推（Bench Press）：一筆——① N=1 邊界（畫點不畫線）。
- 硬舉（Deadlift）：四筆同重量——① y 值全同邊界（不得除以 0）。
- 槓鈴划船（Barbell Row）：八筆遞增、320px 寬——⑥ 命中寬度實測、⑦ 最左/最右浮動框不裁切。
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

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    TOKEN,
    safe_port,
    setup_and_home,
    start_server,
    wait_home,
)
from verify_f86 import seed as seed_squat  # noqa: E402

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
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{method} {path} → {exc.code}: {exc.read().decode()[:300]}") from None
    return json.loads(raw) if raw.strip() else None


def log_set(base: str, ex_id: int, days_ago: int, weight: float, reps: int, tag: str) -> str:
    """單筆訓練（一組）。回傳日期字串（YYYY-MM-DD）供斷言比對用。"""
    day = (date.today() - timedelta(days=days_ago)).isoformat()
    workout = api(base, "POST", "/api/workouts", {"date": day})
    api(base, "POST", f"/api/workouts/{workout['id']}/sets", {
        "client_uuid": f"f134-{tag}-{days_ago:03d}",
        "exercise_id": ex_id,
        "set_number": 1,
        "weight_kg": weight,
        "reps": reps,
        "rpe": 7,
    })
    return day


def seed_edge_cases(base: str) -> dict:
    exercises = api(base, "GET", "/api/exercises")
    bench = next(e for e in exercises if e["name_en"].lower() == "bench press")
    deadlift = next(e for e in exercises if e["name_en"].lower() == "deadlift")
    row = next(e for e in exercises if e["name_en"].lower() == "barbell row")

    # 臥推：唯一一筆——① N=1 邊界
    bench_day = log_set(base, bench["id"], 5, 80.0, 5, "bench")

    # 硬舉：四筆同重量——① y 值全同邊界
    deadlift_days = [log_set(base, deadlift["id"], d, 100.0, 5, "dl") for d in (25, 18, 11, 4)]

    # 槓鈴划船：八筆遞增——⑥⑦ 命中寬與邊界不裁切（320px 寬用）
    row_plan = [(60, 40.0), (52, 42.0), (44, 44.0), (36, 46.0),
                (28, 48.0), (20, 50.0), (12, 52.0), (4, 54.0)]
    row_days = [log_set(base, row["id"], d, w, 8, "row") for d, w in row_plan]

    return {
        "bench_day": bench_day,
        "deadlift_days": deadlift_days,
        "row_days": row_days,
    }


def open_detail(page, muscle: str, name: str) -> None:
    page.locator(".bottom-nav").get_by_role("button", name="表現").click()
    page.wait_for_timeout(900)
    page.get_by_role("button", name=muscle).first.click()
    page.wait_for_timeout(700)
    page.get_by_role("button", name=name).first.click()
    page.wait_for_selector(".exercise-detail", timeout=8000)
    page.wait_for_timeout(600)


def go_home(page, base: str) -> None:
    page.goto(base, wait_until="domcontentloaded")
    wait_home(page)


def md(day: str) -> str:
    """跟 exercise-detail.js 的日期渲染同一份算式：MM-DD → MM/DD。"""
    return day[5:].replace("-", "/")


def selected_label(page) -> str | None:
    sel = page.locator(".line-pt.sel")
    if sel.count() != 1:
        return None
    return sel.get_attribute("aria-label")


def tip_texts(page) -> tuple[str, str, str]:
    tip = page.locator(".line-tip")
    return (
        tip.locator(".line-tip-date").inner_text().strip(),
        tip.locator(".line-tip-sets").inner_text().strip(),
        tip.locator(".line-tip-best").inner_text().strip(),
    )


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f134-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        seed_squat(base)
        edge = seed_edge_cases(base)
        run_checks(base, edge)
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


def run_checks(base: str, edge: dict) -> None:  # noqa: C901
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---------- 一般情況（深蹲，五筆遞增）＋ PR 標記 ＋ 點選切換／關閉 ----------
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        open_detail(page, "腿", "深蹲")

        # ① 五個資料點、一條折線；最高點沒被容器上緣裁切
        pts = page.locator(".line-pt")
        check(pts.count() == 5, f"① 五次訓練＝五個資料點（實際 {pts.count()}）")
        check(page.locator(".line-path").count() == 1, "① 五個點以一條折線相連")
        chart_top = page.locator(".line-chart").bounding_box()["y"]
        tops = [pts.nth(i).bounding_box()["y"] for i in range(5)]
        check(min(tops) >= chart_top - 0.5,
              f"① 最高點（75kg）沒有被容器上緣裁切（點頂 {min(tops):.1f}, 容器頂 {chart_top:.1f}）")
        heights = [pts.nth(i).bounding_box()["height"] for i in range(5)]
        check(all(h > 0 for h in heights), "① 每個點的半徑都完整可見（渲染高度 > 0）")

        # ② PR 標記：沿用累進判定——種子資料第三次比上次輕，不該有獎盃；其餘四次該有
        flags = page.locator(".line-flag")
        check(flags.count() == 4, f"② 四次突破各一個獎盃圖示（實際 {flags.count()}）")

        # ③ 既有資訊保留：.bars-max 與 .bars-foot
        head_max = page.locator(".bars-max").inner_text().strip()
        check(head_max.startswith("75"), f"③ 標題列右側是區間最大值（實際 {head_max}）")
        foot = page.locator(".bars-foot").inner_text()
        check("月" in foot and "個人紀錄" in foot, f"③ 底部標示（實際 {foot!r}）")

        # ④ 點資料點顯示三項齊全，且與歷史清單同一天那張卡一致
        pts.nth(4).click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "④ 點資料點出現浮動資訊")
        d, n, b = tip_texts(page)
        hist_first = page.locator(".hist-card").first  # 新→舊，第一張＝最後一次訓練
        hist_date = hist_first.locator(".hist-date").inner_text().strip()
        best_chip = hist_first.locator(".set-chip.best").inner_text()
        check(d == hist_date, f"④ 浮動資訊日期與歷史清單同一天一致（{d!r} vs {hist_date!r}）")
        # verify_f86.seed 的每筆訓練都是兩組（見該檔 seed() 的 plan）
        check(n == "2 組", f"④ 浮動資訊組數正確（實際 {n!r}）")
        check(b.replace(" ", "") == "75kg×5", f"④ 浮動資訊最佳組正確（實際 {b!r}）")
        check("75" in best_chip, f"④ 與歷史清單卡片的最佳組 chip 一致（{best_chip!r}）")

        # ⑤ 選中狀態：有視覺區別
        check(page.locator(".line-pt.sel").count() == 1, "⑤ 被選中的點有視覺區別（.sel）")

        # ⑤ 點另一個點 → 換內容、不累積第二個框
        pts.nth(0).click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "⑤ 點另一個點：只有一個浮動框（不累積）")
        d2, n2, b2 = tip_texts(page)
        check(d2 != d, f"⑤ 內容已換成新選中的點（{d!r} → {d2!r}）")

        # ⑤ 再點同一個已選中的點 → 關閉
        pts.nth(0).click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 0, "⑤ 再點同一個已選中的點：浮動資訊關閉")
        check(page.locator(".line-pt.sel").count() == 0, "⑤ 再點同一個已選中的點：選中狀態清除")

        # ⑤ 點圖表區空白處（非折線圖本身，如標題列）→ 關閉
        pts.nth(2).click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "⑤（前置）先選中一個點")
        page.locator(".bars-head").click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 0,
              "⑤ 點圖表區空白處（.bars-head）：浮動資訊關閉")

        # ⑤ 切換區間藥丸 → 浮動資訊與選中狀態清除
        pts.nth(2).click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "⑤（前置）先選中一個點")
        page.locator('.range-pills button:has-text("1M")').click()
        page.wait_for_timeout(700)
        check(page.locator(".line-tip").count() == 0, "⑤ 切換區間藥丸：浮動資訊清除")
        check(page.locator(".line-pt.sel").count() == 0, "⑤ 切換區間藥丸：選中狀態清除")
        page.locator('.range-pills button:has-text("全部")').click()
        page.wait_for_timeout(700)

        ctx.close()

        # ---------- ① N=1 邊界（臥推） ----------
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        open_detail(page, "胸", "臥推")
        check(page.locator(".line-pt").count() == 1, "⑧ N=1：畫一個點")
        check(page.locator(".line-path").count() == 0, "⑧ N=1：不畫線（一點連不成線）")
        page.locator(".line-pt").first.click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "⑧ N=1：點擊照常可用")
        d, n, b = tip_texts(page)
        check(d == md(edge["bench_day"]), f"⑧ N=1：浮動資訊日期正確（{d!r}）")
        ctx.close()

        # ---------- ⑧ y 值全同邊界（硬舉） ----------
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        open_detail(page, "背", "硬舉")
        dl_pts = page.locator(".line-pt")
        check(dl_pts.count() == 4, f"⑧ 同重量：四個點都畫出來（實際 {dl_pts.count()}）")
        dl_tops = [round(dl_pts.nth(i).bounding_box()["y"], 1) for i in range(4)]
        check(len(set(dl_tops)) == 1,
              f"⑧ 同重量：所有點畫在同一水平線（不除以 0）（實際 {dl_tops}）")
        check(page.locator(".line-path").count() == 1, "⑧ 同重量：折線水平存在")
        dl_pts.nth(1).click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "⑧ 同重量：點仍可點")
        ctx.close()

        # ---------- ⑥⑦ 命中寬度與邊界不裁切（槓鈴划船，320px 寬，八點） ----------
        ctx = browser.new_context(viewport={"width": 320, "height": 780})
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        open_detail(page, "背", "槓鈴划船")
        row_pts = page.locator(".line-pt")
        n = row_pts.count()
        check(n == 8, f"⑥⑦（前置）八個資料點都畫出來（實際 {n}）")

        chart_box = page.locator(".line-chart").bounding_box()
        y_mid = chart_box["y"] + chart_box["height"] / 2
        # x 佈局＝內縮等格：每個點各占 1/n 格、落在格子中心（(i+0.5)/n）——頭尾點也拿滿
        # 一整格寬，不會貼齊容器邊緣（P1 review：貼邊會讓頭尾命中寬只剩內部點的一半）。
        xs = [chart_box["x"] + ((i + 0.5) / n) * chart_box["width"] for i in range(n)]

        def label_at(idx: int) -> str:
            return row_pts.nth(idx).get_attribute("aria-label")

        def click_x(x: float) -> str | None:
            # 先點空白處保證「未選中」，再點目標位置——選中狀態是 toggle：如果上一次呼叫
            # 剛好也選中同一個點，這一下會變成「再點已選中的點」而關閉（回傳 None），
            # 二分搜尋會因此誤判邊界。先重置成未選中，每次量測都是乾淨的「從無到選」。
            page.locator(".bars-head").click()
            page.wait_for_timeout(80)
            page.mouse.click(x, y_mid)
            page.wait_for_timeout(120)
            return selected_label(page)

        # ⑥「不要求精準落點」：在點 2 與點 3 之間、明顯偏向點 2 的位置點擊，仍選中點 2
        near2 = xs[2] + (xs[3] - xs[2]) * 0.3
        check(click_x(near2) == label_at(2),
              f"⑥ 點在兩點之間（偏點 2）仍選到最近的點（x={near2:.0f}）")
        near3 = xs[2] + (xs[3] - xs[2]) * 0.7
        check(click_x(near3) == label_at(3),
              f"⑥ 點在兩點之間（偏點 3）仍選到最近的點（x={near3:.0f}）")

        # ⑥ 命中寬度：二分搜尋左右邊界。中段內部點（3）左右都有鄰居可搜；
        # 頭尾點（0／n-1）只有一側有鄰居，另一側的邊界就是 .line-chart 容器本身的邊緣——
        # click_x() 已經把 frac clamp 在 [0,1]，容器邊緣的點擊必然落在頭/尾點的命中區內
        # （這正是 P1 review 抓到的地方：舊公式讓頭尾點貼齊容器邊緣，這一側的命中寬變成 0）。
        def find_boundary(lo: float, hi: float, lo_label: str, hi_label: str) -> float:
            for _ in range(18):
                mid = (lo + hi) / 2
                got = click_x(mid)
                if got == lo_label:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2

        threshold = min(44.0, chart_box["width"] / n)
        chart_left = chart_box["x"]
        chart_right = chart_box["x"] + chart_box["width"]

        def check_hit_width(label: str, width: float) -> None:
            check(width >= threshold - 1,  # -1px：滑鼠整數座標與二分搜尋收斂誤差
                  f"⑥ 320px 寬下{label}的命中寬 {width:.1f}px ≥ min(44, 圖寬/N={threshold:.1f})")
            print(f"    [量測] {label} 命中寬={width:.1f}px, 門檻={threshold:.1f}px, "
                  f"圖寬={chart_box['width']:.1f}px, N={n}")

        # 頭（index 0）：左邊界＝容器左緣（clamp 後必選點 0），右邊界＝與點 1 的二分搜尋。
        # 邊緣點擊用 1px 內縮，避免子像素落在 .line-chart 外緣（相鄰的卡片 padding）而誤觸關閉分支。
        check(click_x(chart_left + 1) == label_at(0), "⑥（前置）容器左緣的點擊選中頭點")
        head_right = find_boundary(xs[0], xs[1], label_at(0), label_at(1))
        check_hit_width("點 0（頭）", head_right - chart_left)

        # 中段內部點（3）：左右都有鄰居
        left_boundary = find_boundary(xs[2], xs[3], label_at(2), label_at(3))
        right_boundary = find_boundary(xs[3], xs[4], label_at(3), label_at(4))
        check_hit_width("點 3（中段）", right_boundary - left_boundary)

        # 尾（index n-1）：右邊界＝容器右緣（clamp 後必選最後一點），左邊界＝與前一點的二分搜尋
        check(click_x(chart_right - 1) == label_at(n - 1), "⑥（前置）容器右緣的點擊選中尾點")
        tail_left = find_boundary(xs[n - 2], xs[n - 1], label_at(n - 2), label_at(n - 1))
        check_hit_width("點 7（尾）", chart_right - tail_left)

        def check_tip_in_bounds(edge_label: str) -> None:
            """⑦ 浮動框不被容器裁切：框的左右緣都要落在 .line-chart 的範圍內。"""
            tip_box = page.locator(".line-tip").bounding_box()
            c_left, c_right = chart_box["x"], chart_box["x"] + chart_box["width"]
            t_left, t_right = tip_box["x"], tip_box["x"] + tip_box["width"]
            check(t_left >= c_left - 1,
                  f"⑦ {edge_label}選中：浮動框左緣未超出容器（{t_left:.0f}≥{c_left:.0f}）")
            check(t_right <= c_right + 1,
                  f"⑦ {edge_label}選中：浮動框右緣未超出容器（{t_right:.0f}≤{c_right:.0f}）")
            print(f"    [量測] {edge_label}浮動框 x={t_left:.1f}~{t_right:.1f}px, "
                  f"容器 x={c_left:.1f}~{c_right:.1f}px")

        # ⑦ 最左點被選中：浮動框不被容器裁切
        row_pts.nth(0).click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "⑦（前置）最左點可選中")
        check_tip_in_bounds("最左點")

        # ⑦ 最右點被選中：浮動框不被容器裁切
        row_pts.nth(n - 1).click()
        page.wait_for_timeout(300)
        check(page.locator(".line-tip").count() == 1, "⑦（前置）最右點可選中")
        check_tip_in_bounds("最右點")

        # ⑨ 不引入圖表庫：全程用 inline SVG（polyline）／CSS 自繪；package.json 依賴數量不變
        check(page.evaluate("() => !!document.querySelector('.line-chart svg.line-svg polyline, "
                             ".line-chart svg.line-svg')"),
              "⑨ 折線用 inline SVG 自繪（無第三方圖表庫節點特徵）")
        pkg_path = Path(__file__).resolve().parents[2] / "package.json"
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        # 這支 package.json 是 F61 的 Capacitor 殼（android 打包用），跟前端圖表無關；
        # F134 不引入圖表庫＝這裡的依賴數量不因這次改動而變（4 顆 @capacitor/*）。
        check(len(pkg.get("dependencies", {})) == 4,
              f"⑨ package.json 依賴數量不變（實際 {len(pkg.get('dependencies', {}))} 顆）")

        ctx.close()
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
