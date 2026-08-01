"""F84 驗證：logger 改版（快調列、休息圓環、四顆控制）。

跑法：`uv run python tests/e2e/verify_f84.py`

兩個重點：
1. ±15s 必須**同時**改剩餘與目標——只改剩餘的話圓環的分母不動，畫面上的比例會說謊。
2. 版面高度：休息態的內容不能把主按鈕推到摺線下（handoff 特別警告過），
   所以 412×892 與 360×640 都要量主按鈕的實際位置，不是「看起來還好」。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
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


def open_logger(page, base: str) -> None:
    start_from_home(page)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(700)
    page.locator("button").filter(has_text="深蹲").first.click()
    page.wait_for_timeout(900)


def rest_state(page) -> dict:
    return page.evaluate(
        "async () => {"
        "  const s = await import('/js/state.js');"
        "  return { remaining: s.restRemainingSeconds(), target: s.state.restTargetSeconds,"
        "           paused: s.restPaused(), started: s.state.restStartedAt !== null };"
        "}"
    )


def ring_ratio(page) -> float:
    """從 stroke-dashoffset 反推環走了多少——這是「分母有沒有跟著改」的唯一硬證據。"""
    return page.evaluate(
        "() => {"
        "  const c = document.querySelector('.rest-ring .ring-value');"
        "  const total = Number(c.getAttribute('stroke-dasharray'));"
        "  const offset = Number(c.getAttribute('stroke-dashoffset'));"
        "  return 1 - offset / total;"
        "}"
    )


def main() -> int:
    port = free_port()
    db = e2e_tmp() / f"liftlog_f84_{port}.db"
    release = e2e_tmp() / f"liftlog_f84_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            open_logger(page, base)

            # ① 標題列
            head = page.locator(".exercise-head")
            check(head.locator(".logger-back").count() == 1, "① 左上有返回")
            check("第 1 組" in head.locator(".alias").inner_text(),
                  f"① 副標帶組號（{head.locator('.alias').inner_text()}）")
            check(head.locator(".logger-detail").count() == 1, "① 右上有動作表現入口")

            # ② 就緒態：上次提示卡
            check(page.locator(".last-ref").count() == 1, "② 就緒態有上次提示卡")
            # ⚠ 快調列三顆鈕已由 **F101 ①** 拿掉（與下方 KG 步進器的 ±2.5 重複、「減量」語意含糊），
            # 卡片本身改成可點、開視窗看上次的全部組。這條斷言翻面成「不得殘留」——
            # 原本那條從 F101 上線起就一直是紅的，直到 2026-07-31 才被發現
            #（F84 當時沒標 superseded_by）。
            check(
                page.locator(".quick-row").count() == 0,
                f"② F101 ① 取代：快調列已移除（殘留 {page.locator('.quick-row').count()} 個）",
            )
            check(page.locator(".rest-card").count() == 0, "② 就緒態不顯示休息卡")
            # 「只填值不送出」那組斷言隨快調列一起搬到 **verify_f101**——
            # F101 ③ 把同一個分寸接了過去（點視窗裡的任一組＝填進步進器、不送出）。
            # 不在這裡重寫一份：同一個行為由兩支腳本各驗一次，改版時只會有一支被記得更新。

            # ⑥ 舊的休息秒數循環 chip 不該還在
            check(page.locator(".rest-hint").count() == 0, "⑥ 60/90/120/180 循環 chip 已移除")

            # ⑩⑨ 就緒態的觸控與版面
            check(not undersized(page), f"⑩ 就緒態觸控 ≥44px（不足：{undersized(page)}）")
            no_hscroll = "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
            check(page.evaluate(no_hscroll), "⑩ 就緒態無水平捲動")

            # 記一組 → 進休息態
            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(1200)

            # ④ 休息卡取代上方那塊
            check(page.locator(".rest-card").count() == 1, "④ 休息態顯示休息卡")
            check(page.locator(".last-ref").count() == 0, "④ 休息態不再顯示上次提示卡")
            check(page.locator(".rest-status").inner_text() == "休息一下",
                  f"④ 狀態字（{page.locator('.rest-status').inner_text()}）")
            check(page.locator(".rest-ring").count() == 1, "④ 有圓環")

            # ③ 已完成組顯示口語詞而不是 @6
            done_rpe = page.locator(".done-list .done-rpe").first.inner_text()
            check(done_rpe in ("輕鬆", "有餘力", "吃力", "很吃力", "力竭"),
                  f"③ 組列顯示累度口語詞（{done_rpe}）")

            # ⑧ 底部固定區在兩態都在
            check(page.locator(".logger-foot .steppers").count() == 1, "⑧ 休息態仍有步進器")
            check(page.get_by_role("button", name="繼續下一組").count() == 1,
                  "⑧ 休息態主按鈕是「繼續下一組」")

            # ⑤ 控制列四顆
            controls = page.locator(".rest-controls .chip")
            check(controls.count() == 4, f"⑤ 控制列四顆（{controls.count()}）")
            names = [controls.nth(i).inner_text().strip() for i in range(4)]
            check(names == ["暫停", "停止", "−15s", "+15s"], f"⑤ 四顆的文案（{names}）")

            # ⑤ ±15s 同時改剩餘與目標（圓環分母跟著變）
            before = rest_state(page)
            before_ratio = ring_ratio(page)
            page.locator(".rest-plus").click()
            page.wait_for_timeout(500)
            after = rest_state(page)
            check(after["target"] == before["target"] + 15,
                  f"⑤ +15s 改目標（{before['target']} → {after['target']}）")
            check(after["remaining"] >= before["remaining"] + 14,
                  f"⑤ +15s 同時改剩餘（{before['remaining']} → {after['remaining']}）")
            after_ratio = ring_ratio(page)
            check(abs(after_ratio - before_ratio) < 0.08,
                  f"⑤ 分母跟著改：環的比例幾乎不動（{before_ratio:.3f} → {after_ratio:.3f}）")
            check(f"/ {after['target']}s" in page.locator(".rest-ring .target").inner_text(),
                  f"⑤ 環中央顯示新目標（{page.locator('.rest-ring .target').inner_text()}）")

            page.locator(".rest-minus").click()
            page.wait_for_timeout(500)
            back = rest_state(page)
            check(back["target"] == before["target"],
                  f"⑤ −15s 改回原目標（{back['target']}）")

            # ⑪ F71：暫停凍結計時
            page.locator(".rest-controls .chip", has_text="暫停").click()
            page.wait_for_timeout(400)
            paused = rest_state(page)
            check(paused["paused"] is True, "⑪ F71 暫停狀態成立")
            check(page.locator(".rest-status").inner_text() == "已暫停",
                  f"⑪ 暫停時狀態字（{page.locator('.rest-status').inner_text()}）")
            page.wait_for_timeout(2200)
            still = rest_state(page)
            check(abs(still["remaining"] - paused["remaining"]) <= 1,
                  f"⑪ F71 暫停期間計時凍結（{paused['remaining']} → {still['remaining']}）")
            page.locator(".rest-controls .chip", has_text="繼續").click()
            page.wait_for_timeout(400)
            check(rest_state(page)["paused"] is False, "⑪ F71 繼續後回到計時中")

            # ⑨ 休息態的版面高度——主按鈕不得被推到摺線下
            box = page.locator(".log-btn").bounding_box()
            check(box is not None and box["y"] + box["height"] <= PHONE["height"] + 1,
                  f"⑨ {PHONE['width']}×{PHONE['height']}：主按鈕完整在可視範圍（{box}）")
            check(page.evaluate(no_hscroll), "⑩ 休息態無水平捲動")
            check(not undersized(page), f"⑩ 休息態觸控 ≥44px（不足：{undersized(page)}）")

            # ⑦ 超時：圓環、數字、主按鈕同時轉 --over
            page.evaluate(
                "async () => {"
                "  const s = await import('/js/state.js');"
                "  s.state.restResumedAt -= 300_000;"
                "}"
            )
            page.wait_for_timeout(1600)
            check("over" in (page.locator(".rest-ring").get_attribute("class") or ""),
                  "⑦ 超時時圓環轉警示色")
            digits = page.locator(".rest-ring .digits").inner_text()
            check(digits.startswith("+"), f"⑦ 超時顯示 +m:ss（{digits}）")
            check("over" in (page.locator(".log-btn").get_attribute("class") or ""),
                  "⑦ 超時時主按鈕同步轉色")
            check(page.locator(".rest-status").inner_text() == "超時了",
                  f"⑦ 狀態字轉「超時了」（{page.locator('.rest-status').inner_text()}）")
            stop_cls = page.locator(".stop-rest").get_attribute("class") or ""
            check("alarming" in stop_cls, f"⑪ F73 響著時停止鈕掛上警示 class（{stop_cls}）")
            # ⚠ class 對不代表看得出來：.rest-controls .chip 的 specificity 比 .btn-danger 高，
            # 只驗 class 會讓「顏色其實沒變」通過（Codex 2026-07-29 量 computed style 才抓到）
            alarm_bg = page.locator(".stop-rest").evaluate(
                "el => getComputedStyle(el).backgroundColor"
            )
            check(alarm_bg == "rgb(201, 106, 78)", f"⑪ F73 停止鈕實際底色轉赤陶（{alarm_bg}）")

            # ⑪ F71：停止＝結束這段休息
            page.locator(".stop-rest").click()
            page.wait_for_timeout(600)
            check(rest_state(page)["started"] is False, "⑪ F71 停止結束休息")
            check(page.locator(".last-ref").count() == 1, "④ 停止後回到就緒態的上次提示卡")
            ctx.close()

            # ⑨ 實機尺寸：Ryan 的 Note10+ 把顯示密度調成 600，CSS 可視高度只有約 727px——
            # 不是「小手機」，但版面需要 828px，所以主按鈕會被切掉。第一版門檻訂 700 就漏了這台，
            # 而 390×844 與 360×640 兩個測試尺寸剛好一上一下把它跳過去（實機截圖才看到）。
            for size in ({"width": 384, "height": 727}, {"width": 360, "height": 640}):
                ctx = browser.new_context(viewport=size)
                page = ctx.new_page()
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_selector("input", timeout=10_000)
                setup_and_home(page)
                open_logger(page, base)
                # F109 ④：⑨ 原本只量休息態。就緒態（還沒按下「完成這組」）也要量——
                # 兩者的版面組成不同，休息態沒事不代表就緒態沒事，反之亦然。
                ready_over = page.evaluate(
                    "() => document.documentElement.scrollHeight - window.innerHeight"
                )
                check(ready_over <= 1,
                      f"⑨ {size['width']}×{size['height']}：**就緒態**不產生垂直溢出"
                      f"（{ready_over}px）")
                page.get_by_role("button", name="完成這組").click()
                page.wait_for_timeout(1200)
                # 不可以先 scroll_into_view：那會讓這條永遠通過（Codex 2026-07-29 P2）
                box = page.locator(".log-btn").bounding_box()
                fits = box is not None and box["y"] >= 0 and (
                    box["y"] + box["height"] <= size["height"] + 1
                )
                check(fits, f"⑨ {size['width']}×{size['height']}：主按鈕完整可見（{box}）")
                overflow = page.evaluate(
                    "() => document.documentElement.scrollHeight - window.innerHeight"
                )
                # F109：溢出時要看得出**是誰吃掉的**，否則只知道「差幾 px」還得再猜一輪
                # （F117 就是靠同樣的診斷欄位一次修對）
                kids = page.evaluate(
                    """() => [...document.querySelectorAll('.screen.logger > *')]
                         .map(c => (c.className || c.tagName) + ':' +
                              Math.round(c.getBoundingClientRect().height))"""
                )
                check(overflow <= 1,
                      f"⑨ {size['width']}×{size['height']}：休息態不產生垂直溢出"
                      f"（{overflow}px；{kids}）")
                check(page.evaluate(no_hscroll),
                      f"⑨ {size['width']}×{size['height']} 無水平捲動")
                check(page.locator(".rest-ring").count() == 1,
                      f"⑨ {size['width']}×{size['height']} 仍畫得出圓環")
                ctx.close()

            ctx = browser.new_context(viewport={"width": 360, "height": 640})
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            open_logger(page, base)
            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(1200)
            # ⚠ 不可以先 scroll_into_view：那會讓「主按鈕不得被推到摺線下」這條永遠通過
            #（Codex 2026-07-29 P2）。要在任何捲動之前量，並且順便確認頁面根本沒有垂直溢出。
            box = page.locator(".log-btn").bounding_box()
            check(box is not None and box["y"] >= 0 and box["y"] + box["height"] <= 641,
                  f"⑨ 360×640：主按鈕完整可見（未捲動即量測）（{box}）")
            overflow = page.evaluate(
                "() => document.documentElement.scrollHeight - window.innerHeight"
            )
            check(overflow <= 1, f"⑨ 360×640：休息態不產生垂直溢出（溢出 {overflow}px）")
            check(page.evaluate(no_hscroll), "⑨ 360×640 無水平捲動")
            check(page.locator(".rest-ring").count() == 1, "⑨ 矮螢幕仍畫得出圓環")
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
