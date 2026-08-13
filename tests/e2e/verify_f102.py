"""F102 E2E：重量與次數可直接輸入（± 保留）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f102.py`

⚠ 這條的重點一半在**反面**：不合法的輸入要「還原原值」，不是清成 0、不是送 NaN。
   只驗「輸入 100 會變 100」的話，把任何字串都硬轉成數字的實作也全綠。

⚠ ④ 輸入途中不得整頁重繪——重繪會把 input 拆掉，手機上鍵盤跟著收起來。
   驗法是輸入到一半檢查焦點還在不在那個 input 上（同一個節點）。
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


def kg(page):
    return page.locator(".stepper").first.locator("output.editable")


def reps(page):
    return page.locator(".stepper").nth(1).locator("output.editable")


def value_of(page, index: int) -> str:
    return page.locator(".stepper").nth(index).locator("output, .value-input").first.input_value() \
        if page.locator(".stepper").nth(index).locator(".value-input").count() \
        else page.locator(".stepper").nth(index).locator("output").first.inner_text()


def type_into(page, index: int, text: str, commit: str = "Enter") -> None:
    """點數字 → 進入輸入態 → 輸入 → 送出。"""
    page.locator(".stepper").nth(index).locator("output.editable").click()
    page.wait_for_timeout(200)
    page.locator(".stepper").nth(index).locator(".value-input").fill(text)
    page.wait_for_timeout(100)
    if commit == "Enter":
        page.keyboard.press("Enter")
    elif commit == "blur":
        page.locator(".logger-foot").click(position={"x": 5, "y": 5})
    else:
        page.keyboard.press("Escape")
    page.wait_for_timeout(400)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f102-"))
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
        wait_home(page)
        start_from_home(page)
        page.wait_for_timeout(1200)
        page.locator(".exercise-item").first.click()
        page.wait_for_selector(".logger-foot", timeout=8000)
        page.wait_for_timeout(500)

        # ① 兩個數字都可點
        check(kg(page).count() == 1, "① KG 的數字可點擊直接輸入")
        check(reps(page).count() == 1, "⑤ REPS 同樣可點擊直接輸入（只做一半會變兩種操作習慣）")

        # ② ± 保留
        pair = page.locator(".stepper").first.locator(".pair .btn")
        check(pair.count() == 2, f"② KG 的 ± 兩顆保留（實際 {pair.count()}）")
        before = value_of(page, 0)
        pair.nth(1).click()
        page.wait_for_timeout(400)
        check(
            value_of(page, 0) != before,
            f"② ± 仍然有效（{before} → {value_of(page, 0)}）——這是補一條路不是取代",
        )

        # ⑥ 觸控目標
        box = kg(page).bounding_box()
        check(box["height"] >= 44, f"⑥ 數字可點區 ≥44px（實際 {box['height']:.0f}）")
        gap = page.evaluate(
            """() => {
                 const s = document.querySelector('.stepper');
                 const out = s.querySelector('output.editable').getBoundingClientRect();
                 const btn = s.querySelector('.pair .btn').getBoundingClientRect();
                 return Math.max(btn.top - out.bottom, out.top - btn.bottom, 0);
               }"""
        )
        check(gap >= 8, f"⑥ 數字與 ± 的間距 ≥8px（實際 {gap:.0f}）")

        # ④ 輸入途中不整頁重繪（重繪會把 input 拆掉、鍵盤收起）
        kg(page).click()
        page.wait_for_timeout(200)
        node_id = page.evaluate(
            "() => { const i = document.querySelector('.value-input');"
            " i.dataset.probe = 'x'; return document.activeElement === i; }"
        )
        check(node_id, "④ 點下去就進入輸入態且取得焦點")
        page.keyboard.type("12")
        page.wait_for_timeout(300)
        still = page.evaluate(
            "() => { const i = document.querySelector('.value-input');"
            " return !!i && i.dataset.probe === 'x' && document.activeElement === i; }"
        )
        check(still, "④ 輸入途中不整頁重繪——input 還是同一個節點、焦點還在")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ① 正面：輸入 100
        type_into(page, 0, "100")
        check(value_of(page, 0) == "100", f"① 輸入 100 生效（實際 {value_of(page, 0)}）")
        type_into(page, 1, "12")
        check(value_of(page, 1) == "12", f"⑤ REPS 輸入 12 生效（實際 {value_of(page, 1)}）")

        # ③ 反面：非法輸入一律還原原值
        for bad, why in [
            ("abc", "非數字"),
            ("-5", "負數"),
            ("12.34", "兩位小數"),
            ("", "空白"),
        ]:
            type_into(page, 0, bad)
            check(
                value_of(page, 0) == "100",
                f"③ 反面：{why}「{bad}」被擋下且還原原值 100（實際 {value_of(page, 0)}）",
            )

        # ③ 一位小數是合法的（別擋過頭）
        type_into(page, 0, "62.5")
        check(value_of(page, 0) == "62.5", f"③ 一位小數合法（實際 {value_of(page, 0)}）")

        # Escape 取消不改值
        page.locator(".stepper").first.locator("output.editable").click()
        page.wait_for_timeout(200)
        page.locator(".stepper").first.locator(".value-input").fill("777")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        check(value_of(page, 0) == "62.5", f"Escape 取消不改值（實際 {value_of(page, 0)}）")

        # 失焦也算送出
        type_into(page, 0, "80", commit="blur")
        check(value_of(page, 0) == "80", f"④ 失焦即生效（實際 {value_of(page, 0)}）")

        # ⑦ 不回歸：輸入的值真的送得出去
        type_into(page, 1, "7")
        page.locator(".log-btn").first.click()
        page.wait_for_timeout(1200)
        row = page.locator(".done-row").first.inner_text()
        check(
            "80" in row and "7" in row,
            f"⑦ 輸入的值真的送出並出現在組列（實際「{row.strip()[:40]}」）",
        )

        # ⚠ 2026-08-01 做 F113 時發現的**既有違規**：`@media (max-height: 840px)` 把步進器的
        # 內距與字級收小之後，± 在 384×727（Ryan 的實機）量到 39px 高——低於 F74／F77
        # 訂的 44px。390×844 量到 49px，所以這個違規一直沒被抓到。
        # 那是每一組都要按、常常還是濕手在按的按鈕，所以把這個尺寸永久釘進來。
        page.set_viewport_size({"width": 384, "height": 727})
        page.wait_for_timeout(400)
        small = page.evaluate(
            """() => [...document.querySelectorAll('.logger-foot .steppers .pair .btn')]
                 .map(b => b.getBoundingClientRect())
                 .filter(r => r.width < 44 || r.height < 44)
                 .map(r => Math.round(r.width) + 'x' + Math.round(r.height))"""
        )
        check(not small, f"F74／F77 不回歸：384×727 的 ± 仍 ≥44px（不足：{small}）")

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
