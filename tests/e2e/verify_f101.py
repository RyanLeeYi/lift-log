"""F101 E2E：上次提示卡改成可點的完整紀錄視窗（取代快調列）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f101.py`

⚠ ③ 的反面是這條最容易寫壞的地方：點某一組是**只填值不送出**。
   少了那條反面，「點一下就直接記一筆」的實作也會全綠——而那是破壞性的（多一筆假紀錄）。

⚠ ④ 第一次做這個動作時卡片不可點。少了這條，開一個空視窗的實作也全綠。
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
    PHONE,
    end_workout,
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
    wait_home,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def value_of(page, index: int) -> str:
    return page.locator(".stepper").nth(index).locator("output").first.inner_text()


def set_value(page, index: int, text: str) -> None:
    page.locator(".stepper").nth(index).locator("output.editable").click()
    page.wait_for_timeout(200)
    page.locator(".stepper").nth(index).locator(".value-input").fill(text)
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)


def log_set(page, weight: str, reps: str) -> None:
    set_value(page, 0, weight)
    set_value(page, 1, reps)
    page.locator(".log-btn").first.click()
    page.wait_for_timeout(900)
    stop = page.locator(".rest-card").get_by_role("button", name="停止")
    if stop.count():
        stop.first.click()
        page.wait_for_timeout(400)


def back_to_picker(page) -> None:
    """logger 左上的返回箭頭＝回動作選擇（F42），不結束訓練。"""
    page.locator(".exercise-head button").first.click()
    page.wait_for_timeout(900)


def open_first_exercise(page) -> None:
    wait_home(page)
    start_from_home(page)
    page.wait_for_timeout(1200)
    page.locator(".exercise-item").first.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(500)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f101-"))
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


def run_checks(base: str) -> None:  # noqa: C901
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)

        # ── 第一次做這個動作：④ 卡片不可點 ──
        open_first_exercise(page)
        check(
            page.locator(".quick-row").count() == 0
            and page.get_by_role("button", name="同上").count() == 0,
            "① 快調列（同上／+2.5kg／減量）已移除",
        )
        check(
            page.locator(".last-ref.tappable").count() == 0,
            "④ 第一次做這個動作 → 卡片不可點（不要開一個空視窗）",
        )
        check(
            page.locator(".last-ref-more").count() == 0,
            "④ 反面：不可點時不顯示「N 組 ›」的可點線索",
        )

        # 記三組不同的值，結束訓練 → 下一次進來就有「上次」了
        log_set(page, "60", "10")
        log_set(page, "62.5", "8")
        log_set(page, "65", "6")
        back_to_picker(page)
        end_workout(page)
        page.wait_for_timeout(1500)

        # ── 第二次：卡片可點，視窗列出上次全部組 ──
        open_first_exercise(page)
        card = page.locator(".last-ref.tappable")
        check(card.count() == 1, "② 有上次紀錄時卡片可點")
        check(
            "3 組" in page.locator(".last-ref-more").inner_text(),
            f"⑤ 卡片看得出可點且講出有幾組（{page.locator('.last-ref-more').inner_text()}）",
        )
        box = card.bounding_box()
        check(box["height"] >= 44, f"⑤ 觸控目標 ≥44px（實際 {box['height']:.0f}）")

        card.click()
        page.wait_for_timeout(500)
        rows = page.locator(".last-set-row")
        check(rows.count() == 3, f"② 視窗列出上次的**全部**組（實際 {rows.count()}）")
        text = page.locator(".last-sets-list").inner_text()
        check(
            "60" in text and "62.5" in text and "65" in text,
            f"② 三組的值都在（實際「{text.replace(chr(10), ' / ')[:70]}」）",
        )

        # ③ 點某一組＝把值填進步進器並關窗
        before_rows = page.locator(".done-row").count()
        rows.nth(1).click()  # 第二組 62.5 × 8
        page.wait_for_timeout(600)
        check(page.locator(".last-sets-list").count() == 0, "③ 點完關窗")
        check(
            value_of(page, 0) == "62.5" and value_of(page, 1) == "8",
            f"③ 點第二組把值填進步進器（實際 {value_of(page, 0)} × {value_of(page, 1)}）",
        )
        # ③ 反面：只填值**不送出**——直接記一筆是破壞性的
        check(
            page.locator(".done-row").count() == before_rows,
            f"③ 反面：只填值不送出，沒有多出紀錄（{before_rows} → "
            f"{page.locator('.done-row').count()}）",
        )

        # 換一組驗第一組也能點（不是只有第二列綁對）
        page.locator(".last-ref.tappable").click()
        page.wait_for_timeout(400)
        page.locator(".last-set-row").first.click()
        page.wait_for_timeout(500)
        check(
            value_of(page, 0) == "60" and value_of(page, 1) == "10",
            f"③ 點第一組同樣正確（實際 {value_of(page, 0)} × {value_of(page, 1)}）",
        )

        # ⑥ 點遮罩關窗
        page.locator(".last-ref.tappable").click()
        page.wait_for_timeout(400)
        page.locator(".modal-overlay").click(position={"x": 5, "y": 5})
        page.wait_for_timeout(400)
        check(page.locator(".last-sets-list").count() == 0, "⑥ 點遮罩關窗（沿用既有 modal 慣例）")

        # 視窗開著時是真的 modal：底下的返回鍵點不到
        page.locator(".last-ref.tappable").click()
        page.wait_for_timeout(400)
        blocked = page.evaluate(
            "() => { const back = document.querySelector('.exercise-head button');"
            " const r = back.getBoundingClientRect();"
            " const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
            " return !back.contains(top) && top !== back; }"
        )
        check(blocked, "⑥ 視窗開著時遮罩擋住底下的操作（是真的 modal）")
        page.locator(".modal-overlay").click(position={"x": 5, "y": 5})
        page.wait_for_timeout(400)

        # 換動作：卡片要換成新動作自己的狀態，不得殘留上一個動作的資料
        back_to_picker(page)
        page.locator(".exercise-item").nth(1).click()
        page.wait_for_selector(".logger-foot", timeout=8000)
        page.wait_for_timeout(600)
        check(page.locator(".last-sets-list").count() == 0, "換動作後視窗不殘留")
        check(
            page.locator(".last-ref.tappable").count() == 0,
            "換動作後卡片回到「沒做過」的狀態——上一個動作的三組不得殘留在這裡",
        )

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
