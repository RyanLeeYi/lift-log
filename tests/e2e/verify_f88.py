"""F88 E2E：編輯課表改版（動作卡 ＋ 圓鈕控制列），①–⑧。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f88.py`

⚠ 量測一律問渲染結果（getComputedStyle／bounding_box），不問 class 名稱。
⚠ ⑧ 的重點是「視覺 38px、觸控 44px」——所以要**同時**量兩個數字，
   只量其中一個都會讓另一半悄悄失守。
"""

from __future__ import annotations

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


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f88-"))
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
        page.wait_for_timeout(500)

        # ① 課表名 input
        check(page.locator(".tpl-name-input").count() == 1, "① 課表名 input 有自己的樣式")
        check(css(page, ".tpl-name-input", "borderTopWidth") == "0px", "① 無邊框")
        check(css(page, ".tpl-name-input", "borderRadius") == "18px", "① r18")
        check(css(page, ".tpl-name-input", "fontWeight") == "700", "① Archivo 700")
        check(css(page, ".tpl-name-input", "fontSize") == "17px", "① 17px")
        page.locator(".tpl-name-input").fill("F88 測試課表")

        for name in ("深蹲", "臥推", "硬舉"):
            add_exercise(page, name)

        cards = page.locator(".tpl-item")
        check(cards.count() == 3, f"② 三個動作三張卡（實際 {cards.count()}）")
        # F96 ⑤：原本驗「第一張用 --card-hi 站出來」。編輯課表沒有「選中」這個概念，
        # 那個高亮是純裝飾又會誤導，F96 拿掉了——所以這裡改驗新條文的目的：**底色一致**。
        # 不是把斷言刪掉；一致性同樣需要有人守著（下一個誤加高亮的實作要在這裡掛掉）。
        first_bg = css(page, ".tpl-item:nth-of-type(1)", "backgroundColor")
        other_bg = css(page, ".tpl-item:nth-of-type(2)", "backgroundColor")
        check(first_bg == other_bg, f"② 每張卡底色一致，第一張不特別（{first_bg} vs {other_bg}）")
        check(css(page, ".tpl-item-name .n-zh", "fontWeight") == "700", "② 名稱 700")
        check(css(page, ".tpl-item-name .n-zh", "fontSize") == "16px", "② 名稱 16px")
        check(css(page, ".tpl-item-name .n-alias", "fontSize") == "11px", "② 別名 11px")

        # ③ 圓鈕與圖示。
        # F97 ⑦：排序改拖曳後控制列從五顆變三顆（減 加 刪除），F88 ③ 的「右 上下箭頭 刪除」
        # 那一句已 superseded_by F97。圓鈕本身的規格（圓形、向量圖示、間距、觸控區）不變。
        rounds = page.locator(".tpl-item").first.locator(".round-btn")
        check(rounds.count() == 3, f"③ 一張卡三顆圓鈕（減 加 刪除，實際 {rounds.count()}）")
        radius = css(page, ".round-btn", "borderRadius")
        check(radius == "50%", f"③ 圓鈕是圓的（{radius}）")
        # F98：刪除鈕移到標題列（收合後那是唯一還看得到的一列，留在下面會跟著被收起來）
        svgs = page.locator(".tpl-item").first.locator(".tpl-item-del svg")
        check(svgs.count() == 1, f"③ 刪除鈕用向量圖示（實際 {svgs.count()}）")
        src_dir = Path(__file__).resolve().parents[2] / "app/static/js"
        chars = {
            f.name: [c for c in "↑↓✕" if c in f.read_text(encoding="utf-8")]
            for f in src_dir.glob("*.js")
        }
        leftover = {k: v for k, v in chars.items() if v}
        check(not leftover, f"③ app/static/js 內不再出現 ↑↓✕ 字元（殘留：{leftover}）")
        del_color = css(page, ".tpl-item-del", "color")
        other_color = css(page, ".tpl-item-sets .round-btn", "color")
        check(del_color != other_color,
              f"③ 刪除鈕用 --over，與其餘圓鈕不同色（{del_color} vs {other_color}）")
        # F98 起兩顆不在同一列了，量的是實際的最短距離（誤觸防線的本意），不是單軸差
        gap = page.evaluate(
            """() => {
                 const card = document.querySelector('.tpl-item');
                 const d = card.querySelector('.tpl-item-del').getBoundingClientRect();
                 const p = card.querySelectorAll('.tpl-item-sets .round-btn')[1]
                   .getBoundingClientRect();
                 const dx = Math.max(0, Math.max(d.left - p.right, p.left - d.right));
                 const dy = Math.max(0, Math.max(d.top - p.bottom, p.top - d.bottom));
                 return Math.round(Math.hypot(dx, dy));
               }"""
        )
        check(gap >= 6, f"③ 刪除鈕與加組鈕的實際距離 ≥6px（實際 {gap}px，誤觸防線）")

        # F98 ②：卡片預設收合，參考休息在展開後才看得到——先點開第一張
        page.locator(".tpl-item").first.locator(".tpl-item-name").click()
        page.wait_for_timeout(400)

        # ④ 分隔線後的參考休息
        rest = page.locator(".tpl-item").first.locator(".tpl-item-rest")
        check("參考休息" in rest.inner_text(), "④ 標籤是「參考休息」")
        check(css(page, ".tpl-item-rest", "borderTopWidth") == "1px", "④ 前面有分隔線")
        rest.locator("button").filter(has_text="90s").first.click()
        page.wait_for_timeout(500)
        on_color = css(page, ".tpl-item-rest .chip.on", "color")
        on_bg = css(page, ".tpl-item-rest .chip.on", "backgroundColor")
        accent = css(page, ".btn-primary", "backgroundColor")
        check(on_color == accent, f"④ 選中的秒數用 --accent 字（{on_color} vs {accent}）")
        # ⚠ 只驗文字色會漏掉「琥珀字配琥珀底、字整個消失」——真機截圖抓到的。
        # 條文要的是「--accent 字」，那就必須看得見，所以字色與底色不能相同。
        check(on_bg != on_color,
              f"④ 選中的秒數看得見（字 {on_color} 不等於底 {on_bg}）")

        # ⑤ 加動作鈕
        check(css(page, ".tpl-add-open", "backgroundColor") in ("rgba(0, 0, 0, 0)", "transparent"),
              "⑤ 「＋ 加動作」透明底")
        check(css(page, ".tpl-add-open", "borderTopWidth") == "1px", "⑤ 1px 細框")

        # ⑥ 底部按鈕與貼底（F51 不回歸）
        foot = page.locator(".tpl-edit-foot")
        # getComputedStyle 會把 margin-top:auto 解析成實際 px，問宣告問不到。
        # 改量它真正要保證的行為：刪掉一個動作（清單縮短）後，底部按鈕**不會往上跳**。
        # F51 的理由就是「剛按完刪除的手指正落在儲存上」——量位移才是量那件事。
        foot_before = page.locator(".tpl-edit-foot").bounding_box()["y"]
        page.locator(".tpl-item").first.locator(".tpl-item-del").click()
        page.wait_for_timeout(700)
        foot_after = page.locator(".tpl-edit-foot").bounding_box()["y"]
        # 危害是「往上跳」（手指落在剛好移過來的儲存鈕上），往下移不構成誤觸
        check(foot_after >= foot_before - 2,
              f"⑥ 刪一個動作後底部按鈕不上移（{round(foot_before)} → {round(foot_after)}）")
        css_text = (Path(__file__).resolve().parents[2] / "app/static/css/app.css").read_text(
            encoding="utf-8"
        )
        check("margin-top: auto" in css_text.split(".tpl-edit-foot")[1][:200],
              "⑥ .tpl-edit-foot 仍宣告 margin-top: auto（F51 的機制本身）")
        add_exercise(page, "深蹲")  # 補回來，後面的 ⑦ 需要 3 個動作
        save_bg = css(page, ".tpl-edit-foot .btn-primary", "backgroundColor")
        check(save_bg == accent, "⑥ 「儲存課表」是 --accent")
        check(foot.locator("button").count() == 3, "⑥ 底部三顆鈕")

        # ⑦ 清單捲動位置保留（F21）
        check(page.locator(".tpl-items.scrollable").count() == 1,
              "⑦ 超過 2 個動作時清單可捲（F21 門檻不回歸）")
        # F98：卡片收合後清單矮很多，3 個動作已經捲不動——補到有足夠捲動空間再驗
        for name in ("肩推", "槓鈴彎舉", "腿推"):
            add_exercise(page, name)
        # 先展開一張把清單撐高，捲動空間才夠（也順帶讓「減一組」那顆看得到）
        page.locator(".tpl-item").first.locator(".tpl-item-name").click()
        page.wait_for_timeout(400)
        room = page.eval_on_selector(".tpl-items", "e => e.scrollHeight - e.clientHeight")
        assert room >= 40, f"捲動空間不足（{room}），這條斷言的前提不成立"
        page.eval_on_selector(
            ".tpl-items",
            "e => { e.scrollTop = 40; e.dispatchEvent(new Event('scroll')); }",
        )
        page.wait_for_timeout(300)
        page.locator(".tpl-item").first.locator(".tpl-item-sets .round-btn").first.click()
        page.wait_for_timeout(700)
        kept = page.eval_on_selector(".tpl-items", "e => e.scrollTop")
        check(kept >= 30, f"⑦ 重繪後捲動位置保留（{kept}）")

        # ⑧ 觸控目標：視覺 38、觸控 44
        visual = page.eval_on_selector(".round-btn", "e => e.getBoundingClientRect().width")
        check(abs(visual - 38) <= 1, f"⑧ 圓鈕視覺維持 38px（實際 {visual:.0f}）")
        touch = page.evaluate(
            """() => {
                 const b = document.querySelector('.round-btn');
                 const r = getComputedStyle(b, '::after');
                 return { w: parseFloat(r.width), h: parseFloat(r.height) };
               }"""
        )
        check(touch["w"] >= 44 and touch["h"] >= 44,
              f"⑧ 觸控區補到 ≥44px（實際 {touch}）")
        check(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"),
              "⑧ 無水平捲動")

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
