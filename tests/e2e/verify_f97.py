"""F97 E2E：編輯課表的拖曳排序（取代 ↑↓），①–⑧。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f97.py`

⚠ 滑鼠模擬測得到「拖了有沒有換順序」，測不到「濕手長按好不好按」與真手指的捲動搶手勢
   ——⑨ 的真機那半仍要人自己拖一次，這支不能代替它。

⚠ 每個能動的地方都配反面：只驗「拖了會換順序」的話，「一按下去就換」與「連捲動都會換」
   的實作也全綠。② 的長按門檻正是靠反面那條在守。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    open_templates,
    safe_port,
    setup_and_home,
    start_server,
)

LONG_PRESS_MS = 300
CARD_HI = "rgb(59, 52, 44)"  # --card-hi
DRAFT_KEY = "liftlog.templateDraft"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def css(page, selector: str, prop: str) -> str:
    return page.eval_on_selector(selector, "(e, p) => getComputedStyle(e)[p]", prop)


def add_exercise(page, name: str) -> None:
    page.locator(".tpl-add-open").click()
    page.wait_for_timeout(700)
    page.locator(".modal .exercise-item").filter(has_text=name).first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="加入").first.click()
    page.wait_for_timeout(700)


def order(page) -> list[str]:
    return page.locator(".tpl-item .n-zh").all_inner_texts()


def draft_order(page) -> list[int]:
    raw = page.evaluate(f"() => localStorage.getItem({json.dumps(DRAFT_KEY)})")
    if not raw:
        return []
    data = json.loads(raw)
    items = data.get("items") or (data.get("editing") or {}).get("items") or []
    return [i.get("exercise_id") for i in items]


def card_center(page, index: int) -> tuple[float, float]:
    box = page.locator(".tpl-item").nth(index).bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def press_and_hold(page, index: int) -> tuple[float, float]:
    """在第 index 張卡的**名稱區**按住並等過長按門檻（避開 ✕ 與 −＋ 那些按鈕）。"""
    box = page.locator(".tpl-item").nth(index).bounding_box()
    x = box["x"] + box["width"] / 2
    y = box["y"] + 14  # 名稱那一行，不是控制列
    page.mouse.move(x, y)
    page.mouse.down()
    page.wait_for_timeout(LONG_PRESS_MS + 150)
    return x, y


def ensure_expanded(page, index: int = 0) -> None:
    """把第 index 張卡確保成展開態。

    F98 之後卡片可收放，而前面的拖曳測試（放開時的那一下 click）也會動到收放狀態——
    盲目點一下切換會時對時錯。這裡先看 class 再決定要不要點。
    """
    card = page.locator(".tpl-item").nth(index)
    if "expanded" not in (card.get_attribute("class") or ""):
        card.locator(".tpl-item-name").click()
        page.wait_for_timeout(400)


def drag_to(page, x: float, y: float, steps: int = 8) -> None:
    page.mouse.move(x, y, steps=steps)
    page.wait_for_timeout(120)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f97-"))
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

        open_templates(page)
        page.get_by_role("button", name="新課表").first.click()
        page.wait_for_selector(".template-edit", timeout=8000)
        page.wait_for_timeout(400)
        page.locator(".tpl-name-input").fill("F97 拖曳測試")
        # F98 之後卡片預設收合、清單變矮——要夠多動作，捲動相關的斷言才有東西可捲
        for name in ("深蹲", "臥推", "引體向上", "肩推", "槓鈴彎舉", "腿推"):
            add_exercise(page, name)

        base_order = order(page)
        check(len(base_order) == 6, f"前提：六張卡依序排好（{base_order}）")

        # ① ↑↓ 已移除，✕ 保留（⑦）
        check(
            page.get_by_role("button", name="往上移").count() == 0
            and page.get_by_role("button", name="往下移").count() == 0,
            "① ↑↓ 兩顆排序鈕已移除",
        )
        check(
            page.locator(".tpl-item").first.get_by_role("button", name="移除這個動作").count() == 1,
            "⑦ ✕ 保留",
        )
        rounds = page.locator(".tpl-item").first.locator(".round-btn")
        check(rounds.count() == 3, f"⑦ 一張卡剩三顆圓鈕（減 加 刪除，實際 {rounds.count()}）")
        # F74／F88 ⑧ 的規矩：視覺 38、觸控區靠 ::after 補到 44——要量 ::after，不是元素本身
        touch = page.evaluate(
            """() => {
                 const b = document.querySelector('.tpl-item-del');
                 const r = getComputedStyle(b, '::after');
                 return { w: parseFloat(r.width), h: parseFloat(r.height) };
               }"""
        )
        check(
            touch["w"] >= 44 and touch["h"] >= 44,
            f"⑦ F74 觸控目標不回歸：✕ 的觸控區 ≥44×44（實際 {touch}）",
        )
        gap = page.evaluate(
            """() => {
                 const btns = [...document.querySelectorAll('.tpl-item .round-btn')];
                 const plus = btns[1].getBoundingClientRect();
                 const del = document.querySelector('.tpl-item-del').getBoundingClientRect();
                 return del.left - plus.right;
               }"""
        )
        check(gap >= 8, f"⑦ F74 不回歸：✕ 與 ＋ 的間距 ≥8px（實際 {gap:.0f}px）")

        # ② 反面（先驗這條）：**沒有**過長按門檻就移動 → 不排序
        x, y = card_center(page, 0)
        page.mouse.move(x, y - 20)
        page.mouse.down()
        page.mouse.move(x, y + 160, steps=6)  # 立刻移動＝捲清單的手勢
        page.mouse.up()
        page.wait_for_timeout(300)
        check(
            order(page) == base_order,
            f"② 反面：沒長按就移動＝捲清單，順序不能變（{order(page)}）",
        )
        check(
            page.locator(".tpl-item.dragging").count() == 0,
            "② 反面：短按拖動不得進入拖曳態",
        )

        # ③ 長按進入拖曳：那張卡 --card-hi ＋ 更重的陰影，其餘卡片讓位
        press_and_hold(page, 0)
        check(page.locator(".tpl-item.dragging").count() == 1, "② 長按 300ms 後進入拖曳態")
        drag_hi = css(page, ".tpl-item.dragging", "backgroundColor")
        drag_shadow = css(page, ".tpl-item.dragging", "boxShadow")
        rest_shadow = css(page, ".tpl-item:not(.dragging)", "boxShadow")
        check(drag_hi == CARD_HI, f"③ 拖曳中的卡用 --card-hi（實際 {drag_hi}）")
        check(
            drag_shadow != "none" and drag_shadow != rest_shadow,
            f"③ 拖曳中的卡陰影更重（拖曳 {drag_shadow[:28]} vs 其餘 {rest_shadow[:28]}）",
        )
        _, y2 = card_center(page, 1)
        drag_to(page, x, y2 + 20)
        shifted = page.eval_on_selector(
            ".tpl-item:nth-of-type(2)", "e => getComputedStyle(e).transform",
        )
        check(shifted != "none", f"③ 其餘卡片讓位（第二張 transform = {shifted}）")
        page.mouse.up()
        page.wait_for_timeout(400)

        # ⑤ 放開後順序真的改變，且草稿跟著更新
        after = order(page)
        expect = [base_order[1], base_order[0], *base_order[2:]]
        check(after == expect, f"① 拖曳把第一張移到第二個位置（{after}，預期 {expect}）")
        check(
            page.locator(".tpl-item.dragging").count() == 0
            and page.locator(".tpl-items.drag-active").count() == 0,
            "⑥ 放開後不留拖曳態的 class",
        )
        check(
            all(
                css(page, f".tpl-item:nth-of-type({i + 1})", "transform") == "none"
                for i in range(3)
            ),
            "⑥ 放開後不留殘餘位移（半拖曳的版面比拖不動更糟）",
        )
        draft = draft_order(page)
        check(len(draft) == 6, f"⑤ 草稿有六個動作（{draft}）")
        dom_after_reload_ready = draft[:2] != draft[1:]  # 只是確保有內容可比
        check(dom_after_reload_ready, "⑤ 草稿內容可比對")

        # ⑤ 草稿真的存到新順序：重新載入後畫面要是拖完的順序，不是拖之前的
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1600)
        restored = order(page)
        check(
            restored == expect,
            f"⑤ 重新載入後還原的是拖完的順序（{restored}，預期 {expect}）",
        )

        # ⑥ 拖到一半放回原位 ＝ 不變更
        before = order(page)
        x, y = press_and_hold(page, 0)
        _, y2 = card_center(page, 1)
        drag_to(page, x, y2 + 20)
        drag_to(page, x, y)  # 放回原處
        page.mouse.up()
        page.wait_for_timeout(400)
        check(order(page) == before, f"⑥ 拖回原位＝不變更順序（{order(page)}）")

        # ⑥ 拖曳中被中斷（切到背景）：回到穩定狀態，不留半拖曳的卡片
        x, y = press_and_hold(page, 0)
        drag_to(page, x, y + 60)
        page.evaluate(
            "() => { Object.defineProperty(document, 'visibilityState',"
            " { value: 'hidden', configurable: true });"
            " document.dispatchEvent(new Event('visibilitychange')); }"
        )
        page.wait_for_timeout(300)
        check(
            page.locator(".tpl-item.dragging").count() == 0,
            "⑥ 切到背景＝中斷拖曳，不留 .dragging",
        )
        check(
            css(page, ".tpl-item:nth-of-type(1)", "transform") == "none",
            "⑥ 中斷後位移已復原",
        )
        page.mouse.up()
        page.wait_for_timeout(200)
        check(order(page) == before, f"⑥ 中斷不得改動順序（{order(page)}）")

        # ⑧ F21 不回歸：超過 2 個動作＝可捲清單，且捲動位置在重繪後保留
        scroll_h = page.eval_on_selector(".tpl-items", "e => e.scrollHeight")
        client_h = page.eval_on_selector(".tpl-items", "e => e.clientHeight")
        check(
            page.locator(".tpl-items.scrollable").count() == 1,
            "⑧ F21 不回歸：3 個動作時清單可捲",
        )
        # F98：先把第一張點開再捲——展開的動作本身會捲動清單，順序反了會把 scrollTop 洗掉。
        # 另外收合態只看得到刪除鈕，所以要明確指定組數列裡的「減一組」，別誤按到刪除。
        ensure_expanded(page, 0)
        page.eval_on_selector(
            ".tpl-items",
            "e => { e.scrollTop = 30; e.dispatchEvent(new Event('scroll')); }",
        )
        page.wait_for_timeout(200)
        page.locator(".tpl-item").first.locator(".tpl-item-sets .round-btn").first.click()
        page.wait_for_timeout(400)
        kept = page.eval_on_selector(".tpl-items", "e => e.scrollTop")
        check(
            kept == 30,
            f"⑧ F21 不回歸：重繪後捲動位置保留（實際 {kept}，可捲 {scroll_h}>{client_h}）",
        )
        check(
            page.locator(".tpl-edit-foot").count() == 1
            and page.locator(".tpl-edit-foot .btn").count() == 3,
            "⑧ F51 不回歸：底部三顆鈕仍在自己的貼底容器裡",
        )

        # ⑧ F52 不回歸：加動作視窗的高度不隨搜尋結果數量抖動
        page.locator(".tpl-add-open").click()
        page.wait_for_timeout(700)
        modal_h = page.locator(".tpl-add-modal").bounding_box()["height"]
        page.locator(".tpl-add-modal input[type=search]").fill("深蹲")
        page.wait_for_timeout(900)
        modal_h2 = page.locator(".tpl-add-modal").bounding_box()["height"]
        check(
            abs(modal_h2 - modal_h) <= 2,
            f"⑧ F52 不回歸：搜尋篩掉大半結果後視窗高度不變（{modal_h:.0f} → {modal_h2:.0f}）",
        )
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        cancel = page.locator(".tpl-add-modal").get_by_role("button", name="取消")
        if cancel.count():
            cancel.first.click()
            page.wait_for_timeout(500)

        # ④ 拖到清單下緣自動捲動（沒有它，長清單根本拖不到目的地）
        page.eval_on_selector(".tpl-items", "e => { e.scrollTop = 0; }")
        page.wait_for_timeout(200)
        x, _ = press_and_hold(page, 0)
        list_box = page.locator(".tpl-items").bounding_box()
        drag_to(page, x, list_box["y"] + list_box["height"] - 8)
        page.wait_for_timeout(700)
        scrolled = page.eval_on_selector(".tpl-items", "e => e.scrollTop")
        check(scrolled > 0, f"④ 拖到下緣會自動捲動（scrollTop 0 → {scrolled}）")
        # 反面：拖回清單中央就該停下來（先移到中央、確定離開邊緣了，再歸零計數）
        mid_y = list_box["y"] + list_box["height"] / 2
        drag_to(page, x, mid_y)
        page.wait_for_timeout(300)
        page.eval_on_selector(".tpl-items", "e => { e.scrollTop = 20; }")
        page.wait_for_timeout(700)
        still = page.eval_on_selector(".tpl-items", "e => e.scrollTop")
        check(still == 20, f"④ 反面：拖在清單中央不自動捲（{still}）")
        page.mouse.up()
        page.wait_for_timeout(400)

        # ⑤ F30：存過之後再拖，未儲存判斷要涵蓋「只有順序變了」
        page.get_by_role("button", name="儲存課表").click()
        page.wait_for_timeout(1200)
        page.locator(".tpl-row").first.get_by_role("button", name="編輯").click()
        page.wait_for_selector(".template-edit", timeout=8000)
        page.wait_for_timeout(500)
        saved_order = order(page)
        page.get_by_role("button", name="課表列表").click()
        page.wait_for_timeout(400)
        check(
            page.locator(".confirm-modal").count() == 0,
            "⑤ 反面：剛進編輯什麼都沒改 → 離開不跳未儲存確認",
        )
        page.locator(".tpl-row").first.get_by_role("button", name="編輯").click()
        page.wait_for_selector(".template-edit", timeout=8000)
        page.wait_for_timeout(500)
        x, y = press_and_hold(page, 0)
        _, y2 = card_center(page, 1)
        drag_to(page, x, y2 + 20)
        page.mouse.up()
        page.wait_for_timeout(500)
        reordered = order(page)
        check(reordered != saved_order, f"⑤ 存檔後再拖也能改順序（{saved_order} → {reordered}）")
        page.get_by_role("button", name="課表列表").click()
        page.wait_for_timeout(500)
        check(
            page.locator(".confirm-modal").count() == 1,
            "⑤ F30 涵蓋順序變更：只改了順序沒存就離開，要跳未儲存確認",
        )
        ctx.close()

        run_touch_checks(browser, base)
        browser.close()


# ──────────────────────────────────────────────────────────────────────
# 觸控（真手指走的那條路）
#
# 2026-07-31：上面那整批滑鼠斷言全綠，Ryan 在真機上卻**拖不動**。
# 成因是手指與滑鼠在瀏覽器裡是兩套機制：捲動容器上的觸控預設由 compositor 接管，
# 它一判定是捲動就送 pointercancel 把拖曳抽走；而 pointermove 的 preventDefault()
# 對觸控無效，要擋只能擋 non-passive 的 touchmove。滑鼠 pipeline 完全碰不到這一段。
#
# 所以這一節用 CDP 的 Input.dispatchTouchEvent 發真的觸控事件，
# 並且**一定要配一條「捲動仍然正常」的反面**——把捲動整個擋死也會讓上面那條變綠。
# ──────────────────────────────────────────────────────────────────────


def touch(cdp, kind, x=0.0, y=0.0) -> None:
    points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})


def run_touch_checks(browser, base: str) -> None:
    ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    open_templates(page)
    page.get_by_role("button", name="新課表").first.click()
    page.wait_for_selector(".template-edit", timeout=8000)
    page.wait_for_timeout(400)
    page.locator(".tpl-name-input").fill("F97 觸控")
    # F98 之後卡片收合、清單變矮——要夠多動作，「清單真的捲得動」那條反面才有東西可捲
    for name in ("深蹲", "臥推", "引體向上", "肩推", "槓鈴彎舉", "腿推"):
        add_exercise(page, name)

    before = order(page)
    box = page.locator(".tpl-item").nth(0).bounding_box()
    x = box["x"] + box["width"] / 2
    y = box["y"] + 14
    box2 = page.locator(".tpl-item").nth(1).bounding_box()
    target_y = box2["y"] + box2["height"] / 2 + 20

    # 反面（先驗）：手指按下就滑＝捲清單，順序不變且清單真的捲了
    page.eval_on_selector(".tpl-items", "e => { e.scrollTop = 0; }")
    touch(cdp, "touchStart", x, y)
    for step in range(1, 7):
        touch(cdp, "touchMove", x, y - 30 * step)
        page.wait_for_timeout(30)
    touch(cdp, "touchEnd")
    page.wait_for_timeout(400)
    scrolled = page.eval_on_selector(".tpl-items", "e => e.scrollTop")
    check(order(page) == before, "觸控反面：按下就滑＝捲清單，順序不變")
    check(
        scrolled > 0,
        f"觸控反面：清單**真的捲得動**（scrollTop {scrolled}）——擋死捲動也會讓拖曳那條變綠",
    )

    # 正面：長按過門檻後拖曳，中途不得被 pointercancel 抽走
    page.eval_on_selector(".tpl-items", "e => { e.scrollTop = 0; }")
    page.wait_for_timeout(200)
    box = page.locator(".tpl-item").nth(0).bounding_box()
    x = box["x"] + box["width"] / 2
    y = box["y"] + 14
    touch(cdp, "touchStart", x, y)
    page.wait_for_timeout(LONG_PRESS_MS + 150)
    check(page.locator(".tpl-item.dragging").count() == 1, "觸控：長按 300ms 進入拖曳態")
    for step in range(1, 9):
        touch(cdp, "touchMove", x, y + (target_y - y) * step / 8)
        page.wait_for_timeout(40)
    # 這一條就是真機掛掉的地方：長按有進拖曳態，手指一動就被 compositor 抽走
    check(
        page.locator(".tpl-item.dragging").count() == 1,
        "觸控：**手指移動後仍在拖曳態**（真機拖不動就是掛在這裡）",
    )
    touch(cdp, "touchEnd")
    page.wait_for_timeout(500)
    after = order(page)
    check(after != before, f"觸控：拖曳真的改變了順序（{before} → {after}）")
    ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())
