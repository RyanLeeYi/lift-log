"""F98 E2E：編輯課表動作卡的收合／展開（拖曳時全部收起）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f98.py`

⚠ **必須含觸控節**（⑩ 明訂）。F97 的教訓：碰觸控手勢的東西用滑鼠測會假綠——
   滑鼠 31/31 全綠、真手指完全拖不動。這條同時碰「點一下」「長按」「捲動」三種手勢，
   互搶的邊界只有觸控事件測得出來。

⚠ ⑤ 最容易寫壞的是「拖完那一下 click」：瀏覽器在拖曳結束後仍會補送 click，
   不擋掉的話每次拖完卡片都會自己收起來。那條反面在觸控節裡。
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
    open_templates,
    safe_port,
    setup_and_home,
    start_server,
)

LONG_PRESS_MS = 300
CARD_HI = "rgb(59, 52, 44)"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def add_exercise(page, name: str) -> None:
    page.locator(".tpl-add-open").click()
    page.wait_for_timeout(700)
    page.locator(".modal .exercise-item").filter(has_text=name).first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="加入").first.click()
    page.wait_for_timeout(700)


def expanded_count(page) -> int:
    return page.locator(".tpl-item.expanded").count()


def body_visible(page, index: int) -> bool:
    return page.locator(".tpl-item").nth(index).locator(".tpl-item-controls").first.is_visible()


def summary_visible(page, index: int) -> bool:
    return page.locator(".tpl-item").nth(index).locator(".tpl-item-summary").first.is_visible()


def open_editor(page) -> None:
    open_templates(page)
    page.get_by_role("button", name="新課表").first.click()
    page.wait_for_selector(".template-edit", timeout=8000)
    page.wait_for_timeout(400)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f98-"))
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
        open_editor(page)
        page.locator(".tpl-name-input").fill("F98 收放")
        for name in ("深蹲", "臥推", "引體向上", "肩推"):
            add_exercise(page, name)

        # ② 預設全部收合
        check(expanded_count(page) == 0, f"② 預設全部收合（展開 {expanded_count(page)} 張）")
        check(not body_visible(page, 0), "② 收合態看不到組數控制列")
        check(summary_visible(page, 0), "① 收合態顯示「N 組 · 休息 Xs」摘要")
        summary = page.locator(".tpl-item-summary").first.inner_text()
        check("組" in summary, f"① 摘要講出組數（{summary}）")
        check(
            page.locator(".tpl-item").first.locator(".tpl-item-del").first.is_visible(),
            "① 收合態刪除鈕仍看得到（它是收合後唯一還在的操作）",
        )

        collapsed_h = page.locator(".tpl-item").first.bounding_box()["height"]

        # ③ 點卡片展開
        page.locator(".tpl-item").first.locator(".tpl-item-name").click()
        page.wait_for_timeout(400)
        check(expanded_count(page) == 1, "③ 點卡片展開")
        check(body_visible(page, 0), "① 展開態看得到組數控制列")
        check(
            page.locator(".tpl-item").first.locator(".tpl-item-rest").first.is_visible(),
            "① 展開態看得到參考休息（＝原本的完整內容）",
        )
        check(not summary_visible(page, 0), "① 展開態不再顯示摘要（同一份資訊不重複兩次）")
        expanded_h = page.locator(".tpl-item").first.bounding_box()["height"]
        check(
            expanded_h > collapsed_h + 40,
            f"① 展開明顯比收合高（{collapsed_h:.0f} → {expanded_h:.0f}）",
        )

        # ③ 互斥：點第二張，第一張要自己收起來
        page.locator(".tpl-item").nth(1).locator(".tpl-item-name").click()
        page.wait_for_timeout(400)
        check(expanded_count(page) == 1, f"③ 互斥：同時只開一張（實際 {expanded_count(page)}）")
        check(body_visible(page, 1) and not body_visible(page, 0), "③ 展開的是剛點的那一張")

        # ③ 再點一次同一張＝收合
        page.locator(".tpl-item").nth(1).locator(".tpl-item-name").click()
        page.wait_for_timeout(400)
        check(expanded_count(page) == 0, "③ 再點一次收合")

        # ③ 反面：點刪除鈕不算點卡片（不得順手收放）
        page.locator(".tpl-item").first.locator(".tpl-item-name").click()
        page.wait_for_timeout(300)
        before_rows = page.locator(".tpl-item").count()
        page.locator(".tpl-item").nth(1).locator(".tpl-item-del").click()
        page.wait_for_timeout(500)
        check(
            page.locator(".tpl-item").count() == before_rows - 1,
            "③ 反面：刪除鈕仍然是刪除（沒有被收放接管）",
        )
        check(
            expanded_count(page) == 1,
            f"③ 反面：按刪除鈕不會順手收放別張卡（展開數 {expanded_count(page)}）",
        )

        # ⑨ 收放不進草稿：只收放不改內容 → 不得被判定成「有未儲存的變更」
        page.get_by_role("button", name="儲存課表").click()
        page.wait_for_timeout(1400)
        page.locator(".tpl-row").first.get_by_role("button", name="編輯").click()
        page.wait_for_selector(".template-edit", timeout=8000)
        page.wait_for_timeout(500)
        check(expanded_count(page) == 0, "② 重新進編輯也是全部收合")
        page.locator(".tpl-item").first.locator(".tpl-item-name").click()
        page.wait_for_timeout(300)
        page.locator(".tpl-item").first.locator(".tpl-item-name").click()
        page.wait_for_timeout(300)
        page.get_by_role("button", name="課表列表").click()
        page.wait_for_timeout(600)
        check(
            page.locator(".confirm-modal").count() == 0,
            "⑨ 只收放不改內容 → 不得跳「有未儲存的變更」（收放是檢視狀態不是課表內容）",
        )

        run_touch_checks(browser, base)
        browser.close()


# ──────────────────────────────────────────────────────────────────────
# 觸控節（⑩ 明訂必須有）
# ──────────────────────────────────────────────────────────────────────


def touch(cdp, kind, x=0.0, y=0.0) -> None:
    points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})


def run_touch_checks(browser, base: str) -> None:  # noqa: C901
    ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    open_editor(page)
    page.locator(".tpl-name-input").fill("F98 觸控")
    for name in ("深蹲", "臥推", "引體向上", "肩推", "槓鈴彎舉", "腿推"):
        add_exercise(page, name)

    def card_point(index: int) -> tuple[float, float]:
        box = page.locator(".tpl-item").nth(index).bounding_box()
        return box["x"] + box["width"] / 2, box["y"] + 12

    def order() -> list[str]:
        return page.locator(".tpl-item .n-zh").all_inner_texts()

    # ⑤ 點一下（不移動、未過門檻）＝收放
    x, y = card_point(0)
    touch(cdp, "touchStart", x, y)
    page.wait_for_timeout(80)
    touch(cdp, "touchEnd")
    page.wait_for_timeout(500)
    check(expanded_count(page) == 1, "⑤ 觸控：點一下＝收放（未過長按門檻）")

    # ⑤ 按下就滑＝捲清單，不得收放也不得排序
    before = order()
    page.eval_on_selector(".tpl-items", "e => { e.scrollTop = 0; }")
    expanded_before = expanded_count(page)
    x, y = card_point(1)
    touch(cdp, "touchStart", x, y)
    for step in range(1, 7):
        touch(cdp, "touchMove", x, y - 30 * step)
        page.wait_for_timeout(30)
    touch(cdp, "touchEnd")
    page.wait_for_timeout(500)
    scrolled = page.eval_on_selector(".tpl-items", "e => e.scrollTop")
    check(scrolled > 0, f"⑤ 觸控：按下就滑＝捲清單（scrollTop {scrolled}）")
    check(order() == before, "⑤ 觸控：捲動不得改變順序")
    check(
        expanded_count(page) == expanded_before,
        "⑤ 觸控：捲動不得順手收放（三種手勢不互搶的核心）",
    )

    # ④ 長按進入拖曳時，**所有**卡片一律收起
    page.eval_on_selector(".tpl-items", "e => { e.scrollTop = 0; }")
    page.wait_for_timeout(300)
    check(expanded_count(page) == 1, "前提：拖之前有一張是展開的")
    x, y = card_point(2)
    touch(cdp, "touchStart", x, y)
    page.wait_for_timeout(LONG_PRESS_MS + 150)
    check(page.locator(".tpl-item.dragging").count() == 1, "② 長按 300ms 進入拖曳（F97 門檻不變）")
    visible_bodies = sum(
        1 for i in range(page.locator(".tpl-item").count()) if body_visible(page, i)
    )
    check(
        visible_bodies == 0,
        f"④ 拖曳中**所有**卡片收起（仍看得到控制列的有 {visible_bodies} 張）",
    )
    check(
        page.locator(".tpl-item.expanded").count() == 1,
        "④ 展開狀態只是被蓋掉、沒有被清空（放開後才恢復得回來）",
    )
    drag_bg = page.locator(".tpl-item.dragging").evaluate(
        "e => getComputedStyle(e).backgroundColor"
    )
    check(drag_bg == CARD_HI, f"F97 ③ 不回歸：拖曳中的卡仍是 --card-hi（{drag_bg}）")

    # 拖到下一張之後放開
    box2 = page.locator(".tpl-item").nth(3).bounding_box()
    target_y = box2["y"] + box2["height"] / 2 + 10
    for step in range(1, 9):
        touch(cdp, "touchMove", x, y + (target_y - y) * step / 8)
        page.wait_for_timeout(40)
    touch(cdp, "touchEnd")
    page.wait_for_timeout(600)

    check(order() != before, f"F97 不回歸：拖曳仍然改得動順序（{order()}）")
    # ④ 放開後恢復拖曳前的展開狀態
    check(
        expanded_count(page) == 1,
        f"④ 放開後恢復原本的展開狀態（實際展開 {expanded_count(page)} 張）",
    )
    # ⑤ 拖完那一下的 click 不得觸發收放——這是本條最容易壞的地方
    check(
        page.locator(".tpl-item.dragging").count() == 0,
        "⑥ 放開後不留拖曳態",
    )
    dragged_expanded = page.evaluate(
        "() => [...document.querySelectorAll('.tpl-item')]"
        ".filter(c => c.classList.contains('expanded')).length"
    )
    check(
        dragged_expanded == 1,
        f"⑤ 拖完那一下的 click 沒有觸發收放（展開數仍是 1，實際 {dragged_expanded}）",
    )

    ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())
