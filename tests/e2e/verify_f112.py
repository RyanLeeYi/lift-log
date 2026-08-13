"""F112 E2E：就緒態可先設定這組之後的休息秒數。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f112.py`

Ryan 2026-08-01：「計時頁面在進入完成這組之前，可以讓使用者自己修改休息時間，
跟重量還有次數類似」。版面選了「獨立一列，在 KG／REPS 下方」。

⚠ 這支最重要的一條是 ⑤：**改完之後記一組，這輪休息要真的用新值起跑**。
只驗「數字有變」的話，「畫面改了但沒寫進去」會全綠——那是最難察覺的一種壞法，
因為使用者要等到休息開始才會發現倒數不是他設的秒數。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
    wait_home,
)

RYAN = {"width": 384, "height": 727}

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def preset(page):
    return page.locator(".rest-preset")


def preset_value(page) -> str:
    return preset(page).locator("output").first.inner_text().strip()


def into_logger(page) -> None:
    wait_home(page)
    start_from_home(page)
    page.wait_for_timeout(1200)
    page.locator(".exercise-item").first.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(500)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f112-"))
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


def run_checks(base: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=RYAN)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        into_logger(page)

        # ── ① 就緒態有這一列，且在 KG／REPS 下方 ─────────────────
        check(preset(page).count() == 1, "① 就緒態有休息秒數這一列")
        order = page.evaluate(
            """() => {
                 const s = document.querySelector('.steppers');
                 const r = document.querySelector('.rest-preset');
                 if (!s || !r) return null;
                 return s.getBoundingClientRect().bottom <= r.getBoundingClientRect().top + 1;
               }"""
        )
        check(order is True, "① 在 KG／REPS **下方**獨立一列（不是三欄並排）")
        check(
            page.locator(".steppers .stepper").count() == 2,
            f"① 反面：KG／REPS 仍是兩欄，沒被擠成三欄"
            f"（{page.locator('.steppers .stepper').count()}）",
        )

        # ── ② 值＝這個動作的參考休息 ────────────────────────────
        check(preset_value(page) == "60", f"② 初值是這個動作的參考休息（{preset_value(page)}）")

        # ── ③ 上下限 ───────────────────────────────────────────
        plus = preset(page).locator(".pair .btn").last
        minus = preset(page).locator(".pair .btn").first
        plus.click()
        page.wait_for_timeout(350)
        check(preset_value(page) == "75", f"② +15 一階（{preset_value(page)}）")
        for _ in range(10):
            minus.click()
            page.wait_for_timeout(120)
        check(preset_value(page) == "15", f"③ 下限 15s，不會掉到 0 或負數（{preset_value(page)}）")
        for _ in range(3):
            plus.click()
            page.wait_for_timeout(150)
        check(preset_value(page) == "60", f"回到 60 準備下一段（{preset_value(page)}）")

        # ── ④ 直接輸入 ─────────────────────────────────────────
        out = preset(page).locator("output").first
        out.click()
        page.wait_for_timeout(300)
        box = preset(page).locator("input.value-input")
        check(box.count() == 1, "④ 點數字就地換成輸入框（沿用 F102）")
        box.fill("90")
        box.press("Enter")
        page.wait_for_timeout(500)
        check(preset_value(page) == "90", f"④ 合法輸入寫進去（{preset_value(page)}）")

        preset(page).locator("output").first.click()
        page.wait_for_timeout(300)
        box = preset(page).locator("input.value-input")
        box.fill("abc")
        box.press("Enter")
        page.wait_for_timeout(500)
        check(
            preset_value(page) == "90",
            f"④ 反面：非法輸入還原原值，不寫入（{preset_value(page)}）",
        )

        preset(page).locator("output").first.click()
        page.wait_for_timeout(300)
        box = preset(page).locator("input.value-input")
        box.fill("5")  # 低於下限
        box.press("Enter")
        page.wait_for_timeout(500)
        check(preset_value(page) == "90", f"④ 反面：低於下限的輸入不被接受（{preset_value(page)}）")

        # ── ⑦ 觸控 ────────────────────────────────────────────
        boxes = [preset(page).locator(".pair .btn").nth(i).bounding_box() for i in range(2)]
        check(
            all(b["height"] >= 44 and b["width"] >= 44 for b in boxes),
            f"⑦ ± 兩顆 ≥44×44（{[f'{b['width']:.0f}x{b['height']:.0f}' for b in boxes]}）",
        )
        gap = boxes[1]["x"] - (boxes[0]["x"] + boxes[0]["width"])
        check(gap >= 8, f"⑦ ± 之間 ≥8px（{gap:.0f}px）")

        # ── ⑤ 記一組之後，這輪休息要用新值起跑（本支的重點）──────
        page.locator(".log-btn").first.click()
        page.wait_for_selector(".rest-card", timeout=8000)
        page.wait_for_timeout(800)
        target = page.locator(".rest-ring-text .target").first.inner_text()
        check(
            "90" in target,
            f"⑤ 這輪休息用設定的 90s 起跑（圓環分母：{target!r}）——"
            f"只驗「數字有變」的話，畫面改了但沒寫進去會全綠",
        )

        # ── ⑥ 休息態不顯示 ────────────────────────────────────
        check(
            preset(page).count() == 0,
            "⑥ 休息態不顯示這一列（休息卡上已經有 ±15s，兩處可改會讓人不知道信哪個）",
        )

        # ── ⑨ F84 ⑥ 不回歸：循環 chip 不得回來 ──────────────────
        check(
            page.locator(".rest-hint").count() == 0,
            "⑨ F84 ⑥ 不回歸：60/90/120/180 循環 chip 沒有回來（本條是步進器不是 chip）",
        )

        # ── ② 持久化：重新整理之後仍是 90 ───────────────────────
        # ⚠ 重整之後 app 回到**首頁**（畫面本身不持久化，只有訓練狀態持久化），
        # 所以要照正常路徑重新走進計時頁，不能等 .logger-foot 自己出現。
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        into_logger(page)
        # F66：休息會被還原 → 先結束它才回得到就緒態
        if page.locator(".rest-card").count():
            page.locator(".log-btn").first.click()  # 繼續下一組
            page.wait_for_selector(".rest-preset", timeout=8000)
            page.wait_for_timeout(400)
        check(
            preset(page).count() == 1 and preset_value(page) == "90",
            f"② 寫進 restHintOverrides 並持久化（重整後 {preset_value(page)}）",
        )

        # ── ⑧ 溢出 ────────────────────────────────────────────
        for size in (RYAN, {"width": 390, "height": 844}, {"width": 360, "height": 640}):
            page.set_viewport_size(size)
            page.wait_for_timeout(400)
            over = page.evaluate(
                "() => document.documentElement.scrollHeight - window.innerHeight"
            )
            label = f"{size['width']}×{size['height']}"
            if size["height"] == 640:
                check(over <= 9, f"⑧ {label} 就緒態溢出未惡化（{over}px，既有 F109 是 9px）")
            else:
                check(over <= 1, f"⑧ {label} 就緒態不得垂直溢出（{over}px）")

        ctx.close()
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
