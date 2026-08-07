"""F135 E2E：折線圖高 N 時，未選中點依區間點數分級縮小、避免點與點黏成一條粗線（①–⑤）。

跑法：`uv run python tests/e2e/verify_f135.py`

沿用 F134 的導覽 helper（open_detail／md，來自 verify_f134），不重寫。兩個情境：
- 腿彎舉（Leg Curl）：N=50——320px 寬、圖寬 252px 情境下① 直徑分級與② 相鄰圓緣間距的
  極限案例（acceptance 原文舉的正是這組數字）。
- 腿伸展（Leg Extension）：N=21——20/40 分級邊界的上緣，釘住「> 20 就要進 6px 檔」。

兩個情境的每一筆訓練重量都刻意在時間軸上嚴格遞增（累進 PR 定義下每一次都是新 PR），
製造獎盃最壞情況：N=50 時獎盃 icon（8px）比點距（~5px）還寬，重疊無法避免——用來驗證
④「重疊無法避免時縮小 icon、但不省略任何一個」；N=21 時 icon（9px）比點距（12px）窄，
用來驗證「能避免重疊時就不重疊」。
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
from verify_f67 import TOKEN, safe_port, setup_and_home, start_server  # noqa: E402
from verify_f134 import open_detail  # noqa: E402

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
    """單筆訓練（一組）。回傳日期字串（YYYY-MM-DD）。"""
    day = (date.today() - timedelta(days=days_ago)).isoformat()
    workout = api(base, "POST", "/api/workouts", {"date": day})
    api(base, "POST", f"/api/workouts/{workout['id']}/sets", {
        "client_uuid": f"f135-{tag}-{days_ago:03d}",
        "exercise_id": ex_id,
        "set_number": 1,
        "weight_kg": weight,
        "reps": reps,
        "rpe": 7,
    })
    return day


def seed(base: str) -> dict:
    """兩個情境動作，重量在時間軸上嚴格遞增——每一筆都是累進 PR（見檔頭的最壞情況設計）。"""
    exercises = api(base, "GET", "/api/exercises")
    leg_curl = next(e for e in exercises if e["name_en"].lower() == "leg curl")
    leg_ext = next(e for e in exercises if e["name_en"].lower() == "leg extension")

    n50 = 50
    for i in range(n50):
        log_set(base, leg_curl["id"], n50 - i, 40.0 + i * 0.5, 8, "curl")

    n21 = 21
    for i in range(n21):
        log_set(base, leg_ext["id"], n21 - i, 30.0 + i * 1.0, 10, "ext")

    return {"leg_curl_id": leg_curl["id"], "leg_ext_id": leg_ext["id"]}


def edge_gaps(boxes: list[dict]) -> list[float]:
    """相鄰兩個框的圓緣（外框緣）間距＝中心距離－直徑（假設同一批框寬度一致，取第一個代表）。"""
    d = boxes[0]["width"]
    centers = [b["x"] + b["width"] / 2 for b in boxes]
    return [(centers[i + 1] - centers[i]) - d for i in range(len(centers) - 1)]


def check_hit_consistency(
    page, n: int, chart_box: dict, points_locator, indices: list[int], scen: str,
) -> None:
    """⑤ 命中寬 ≥ min(44, 圖寬/N)，且頭尾點與內部點一致（沿用 F134 ⑥ 的二分搜尋手法）。"""
    xs = [chart_box["x"] + ((i + 0.5) / n) * chart_box["width"] for i in range(n)]
    y_mid = chart_box["y"] + chart_box["height"] / 2
    chart_left = chart_box["x"]
    chart_right = chart_box["x"] + chart_box["width"]
    threshold = min(44.0, chart_box["width"] / n)

    def label_at(idx: int) -> str:
        return points_locator.nth(idx).get_attribute("aria-label")

    def click_x(x: float) -> str | None:
        page.locator(".bars-head").click()
        page.wait_for_timeout(60)
        page.mouse.click(x, y_mid)
        page.wait_for_timeout(90)
        sel = page.locator(".line-pt.sel")
        return sel.get_attribute("aria-label") if sel.count() == 1 else None

    def find_boundary(lo: float, hi: float, lo_label, hi_label) -> float:
        for _ in range(16):
            mid = (lo + hi) / 2
            got = click_x(mid)
            lo, hi = (mid, hi) if got == lo_label else (lo, mid)
        return (lo + hi) / 2

    for idx in indices:
        if idx == 0:
            check(click_x(chart_left + 1) == label_at(0), f"{scen}⑤（前置）容器左緣選中頭點")
            right = find_boundary(xs[0], xs[1], label_at(0), label_at(1))
            width, side = right - chart_left, "頭"
        elif idx == n - 1:
            check(click_x(chart_right - 1) == label_at(n - 1), f"{scen}⑤（前置）容器右緣選中尾點")
            left = find_boundary(xs[n - 2], xs[n - 1], label_at(n - 2), label_at(n - 1))
            width, side = chart_right - left, "尾"
        else:
            left = find_boundary(xs[idx - 1], xs[idx], label_at(idx - 1), label_at(idx))
            right = find_boundary(xs[idx], xs[idx + 1], label_at(idx), label_at(idx + 1))
            width, side = right - left, "中段"
        # -1.5px：滑鼠事件座標會被瀏覽器量化到整數 CSS px（實測見 N=21 內部點：理論邊界在
        # x=274.0 但實測翻轉發生在 274~275 之間），二分搜尋收斂到量化格點上會再多算入
        # 最多 1px 誤差——比 F134 ⑥ 命中寬測試（N=8、間距 31.5px）的 -1px 容差略寬，
        # 因為這裡間距更小（12px／5px），量化誤差占比更高。
        check(width >= threshold - 1.5,
              f"{scen}⑤ N={n} 點{idx}（{side}）命中寬{width:.1f}px"
              f"≥{threshold:.1f}px-1.5px量化容差={threshold - 1.5:.1f}px")


def run_scenario(browser, base: str, name: str, ex_id: int, n: int, expect_pt: float,
                  expect_icon: float, scen: str) -> None:
    ctx = browser.new_context(viewport={"width": 320, "height": 780})
    page = ctx.new_page()
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    open_detail(page, "腿", name)

    pts = page.locator(".line-pt")
    count = pts.count()
    check(count == n, f"{scen}（前置）N={n} 個資料點都畫出來（實際 {count}）")

    # ① 未選中點直徑依分級
    boxes = [pts.nth(i).bounding_box() for i in range(count)]
    diam = boxes[0]["width"]
    check(abs(diam - expect_pt) < 0.6,
          f"{scen}① N={n} 未選中點直徑＝{diam:.2f}px（預期 {expect_pt}px 分級）")

    # ② 相鄰未選中點的圓緣間距 ≥ 1px
    gaps = edge_gaps(boxes)
    min_gap = min(gaps)
    check(min_gap >= 1 - 0.3,
          f"{scen}② N={n} 相鄰未選中點最小圓緣間距＝{min_gap:.2f}px（≥1px）")

    # ⑤ 命中寬與頭尾一致性（頭／中段／尾）
    chart_box = page.locator(".line-chart").bounding_box()
    mid_idx = n // 2
    check_hit_consistency(page, n, chart_box, pts, [0, mid_idx, n - 1], scen)

    # ③ 選中點尺寸不變（維持 13px，與 F134 現行一致）
    page.locator(".bars-head").click()
    page.wait_for_timeout(80)
    pts.nth(mid_idx).click()
    page.wait_for_timeout(200)
    sel_box = page.locator(".line-pt.sel").bounding_box()
    sel_ok = (sel_box is not None and abs(sel_box["width"] - 13) < 0.6
              and abs(sel_box["height"] - 13) < 0.6)
    check(sel_ok, f"{scen}③ 選中點尺寸不變（實際 {sel_box['width']:.2f}x{sel_box['height']:.2f}px，"
          "預期 13x13px）")

    # ④ PR 獎盃：不省略任何一個 ＋ icon 依分級縮小
    flags = page.locator(".line-flag")
    flag_count = flags.count()
    check(flag_count == n, f"{scen}④ 全部 N={n} 筆皆為累進 PR，獎盃不省略（實際 {flag_count}）")
    icon_w = flags.locator("svg").nth(0).bounding_box()["width"]
    check(abs(icon_w - expect_icon) < 0.6,
          f"{scen}④ N={n} 獎盃 icon 尺寸＝{icon_w:.2f}px（預期 {expect_icon}px 分級）")
    flag_boxes = [flags.locator("svg").nth(i).bounding_box() for i in range(flag_count)]
    min_flag_gap = min(edge_gaps(flag_boxes))
    spacing = diam + min_gap  # 點中心間距＝點距（gap 定義見 edge_gaps：中心距離－直徑）
    print(f"    [量測] {scen}④ 相鄰獎盃最小間距={min_flag_gap:.2f}px "
          f"(icon={expect_icon}px, 點距≈{spacing:.2f}px)")
    if expect_icon < spacing:
        # 點距比 icon 寬：重疊可避免，這裡才要求真的不重疊
        check(min_flag_gap >= -0.3,
              f"{scen}④ 點距（{spacing:.2f}px）>icon（{expect_icon}px），相鄰獎盃不重疊"
              f"（間距 {min_flag_gap:.2f}px）")
    else:
        print(f"    [量測] {scen}④ 點距<icon 寬，重疊在此密度下無法避免"
              "（acceptance 允許，僅要求已縮小且不省略）")

    ctx.close()


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f135-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        edge = seed(base)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            # N=50：> 40 分級門檻，未選中點 4px、獎盃 icon 8px
            run_scenario(browser, base, "腿彎舉", edge["leg_curl_id"], 50, 4.0, 8.0, "[N=50] ")
            # N=21：20/40 邊界上緣，未選中點 6px、獎盃 icon 9px
            run_scenario(browser, base, "腿伸展", edge["leg_ext_id"], 21, 6.0, 9.0, "[N=21] ")
            browser.close()
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
