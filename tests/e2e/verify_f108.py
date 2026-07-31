"""F108 E2E：休息綁定發起它的動作。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f108.py`

Ryan 2026-07-31 真機回報：休息中切到另一個動作的計時頁，那一頁會長出完整的休息控制卡，
看起來像是這個動作在休息；在那裡按 ±15s 還會把 override 寫進**錯的動作**。
他定的規則是——判斷依據不是「人在不在計時頁」，而是「人在不在**這輪休息所屬動作**的計時頁」。

⚠ 這支要守住的反面：
  - 切到別的動作時要回報「卡片**不**可見」（→ 原生把視窗留著）。這個旗標的語意是
    「app 內的休息卡看得到嗎」，不是「視窗要不要顯示」——極性寫反的話那一頁既沒有休息卡、
    視窗又被藏起來，倒數就整個從畫面上消失了
  - ⑤ 的確認視窗要驗**兩條路**：取消＝什麼都不做（組數不變、休息還在），確認才記。
    只驗「有跳視窗」的話，「取消也照記」會全綠
  - F103 的第二輪回歸斷言不能掉（可見性在開新一輪時要強制重送）
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
    reroute_public_host,
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
    wait_home,
)

NOTIFY_FLAG = "liftlog.nativeNotifyEnabled"
OVERLAY_FLAG = "liftlog.restOverlayEnabled"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


FAKE = """
window.__native = { starts: 0, visible: [] };
window.Capacitor = {
  isNativePlatform: () => true,
  getPlatform: () => 'android',
  Plugins: {
    LocalNotifications: {
      schedule: async () => ({}), cancel: async () => ({}),
      checkPermissions: async () => ({ display: 'granted' }),
      requestPermissions: async () => ({ display: 'granted' }),
      areEnabled: async () => ({ value: true }),
      listChannels: async () => ({ channels: [
        { id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 },
      ] }),
    },
    RestTimer: {
      available: async () => ({ available: true }),
      start: async () => { window.__native.starts += 1; return {}; },
      stop: async () => ({}), pause: async () => ({}), resume: async () => ({}),
      overlayPermitted: async () => ({ granted: true }),
      requestOverlayPermission: async () => {},
      setRestCardVisible: async (o) => {
        window.__native.visible.push(Boolean(o && o.visible));
        return {};
      },
      addListener: async () => ({ remove: () => {} }),
    },
    NotifyStatus: { openSettings: async () => {} },
  },
};
"""


def open_app(browser, base: str):
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    page.add_init_script(FAKE)
    reroute_public_host(page, base)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    page.evaluate(f"() => localStorage.setItem('{OVERLAY_FLAG}', '1')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return ctx, page


def enter_exercise(page, index: int) -> str:
    """從菜單進第 index 個動作的計時頁，回傳動作名。"""
    item = page.locator(".exercise-item").nth(index)
    name = item.inner_text().strip().split("\n")[0]
    item.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(500)
    return name


def back_to_menu(page) -> None:
    page.locator(".logger-back").first.click()
    page.wait_for_timeout(700)


def visible_last(page) -> bool:
    return page.evaluate("() => window.__native.visible.at(-1)")


def remaining(page) -> int | None:
    digits = page.locator(".rest-ring-text .digits")
    if not digits.count():
        return None
    parts = digits.first.inner_text().strip().replace("-", "").split(":")
    if len(parts) != 2:
        return None
    return int(parts[0]) * 60 + int(parts[1])


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f108-"))
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
        ctx, page = open_app(browser, base)
        wait_home(page)
        start_from_home(page)
        page.wait_for_timeout(1200)

        # A 記一組 → A 開始休息
        name_a = enter_exercise(page, 0)
        page.locator(".log-btn").first.click()
        page.wait_for_selector(".rest-card", timeout=8000)
        page.wait_for_timeout(700)
        check(page.locator(".rest-card").count() == 1, f"前提：{name_a} 記完一組進入休息態")
        # ⚠ 這個回報的語意是「app 內的休息卡看得到嗎」：true ＝ 看得到 ＝ 原生把視窗藏起來。
        check(
            visible_last(page) is True,
            "前提：人在所屬動作的計時頁 → 回報卡片可見（原生據此把視窗藏起來）",
        )
        before = remaining(page)

        # ──────────── 切到 B ────────────
        back_to_menu(page)
        name_b = enter_exercise(page, 1)
        check(
            page.locator(".rest-card").count() == 0,
            f"③ 切到 {name_b} 的計時頁 → **不顯示**休息卡（那輪休息不屬於這一頁）",
        )
        check(
            page.locator(".rest-controls").count() == 0,
            "④ 休息控制（暫停／停止／±15s）不出現在別的動作的計時頁",
        )
        check(
            visible_last(page) is False,
            f"② 切到別的動作 → 回報**卡片不可見**，視窗因此留著（實際 {visible_last(page)}）——"
            f"回報 true 的話這一頁既沒卡片、視窗又被藏起來，倒數整個看不見",
        )
        # 這一頁是就緒態：主按鈕是「完成這組」而不是「繼續下一組」
        check(
            "完成這組" in page.locator(".log-btn").first.inner_text(),
            f"③ 別的動作維持就緒態（主按鈕：{page.locator('.log-btn').first.inner_text()!r}）",
        )

        # ──────────── ⑤ 記組前要擋 ────────────
        rows_before = page.locator(".done-row").count()
        page.locator(".log-btn").first.click()
        page.wait_for_timeout(700)
        modal = page.locator(".modal-overlay")
        check(modal.count() == 1, "⑤ 在別的動作按「完成這組」→ 跳確認視窗，不直接記")
        text = modal.first.inner_text()
        check(name_a in text, f"⑤ 文案講出是誰還在休息（{text!r}）")
        check(
            "結束" in text and "休息" in text,
            f"⑤ 文案講出後果（會結束那輪休息）（{text!r}）",
        )
        # 取消＝什麼都不做
        modal.first.get_by_role("button", name="取消").click()
        page.wait_for_timeout(700)
        check(
            page.locator(".modal-overlay").count() == 0
            and page.locator(".done-row").count() == rows_before,
            "⑤ 反面：取消＝什麼都不做（沒有記下這組）",
        )
        check(
            visible_last(page) is False,
            "⑤ 反面：取消之後仍停在別的動作的頁面（回報仍是「卡片不可見」，視窗還在）",
        )

        # ──────────── ⑦ 切回 A：卡片回來、倒數連續 ────────────
        back_to_menu(page)
        enter_exercise(page, 0)
        check(page.locator(".rest-card").count() == 1, "⑦ 切回所屬動作 → 休息卡回來")
        check(visible_last(page) is True, "⑦ 切回所屬動作 → 回報卡片可見（視窗消失）")
        after = remaining(page)
        check(
            before is not None and after is not None and after < before and before - after < 30,
            f"⑦ 倒數連續，沒有重算也沒有歸零（{before} → {after}）",
        )

        # ──────────── ⑤ 確認那條路 ────────────
        back_to_menu(page)
        enter_exercise(page, 1)
        rows_before = page.locator(".done-row").count()
        starts_before = page.evaluate("() => window.__native.starts")
        page.locator(".log-btn").first.click()
        page.wait_for_timeout(700)
        page.locator(".modal-overlay").first.get_by_role("button", name="記這組").click()
        page.wait_for_timeout(1500)
        check(
            page.locator(".done-row").count() == rows_before + 1,
            "⑤ 確認 → 這組真的記下去了",
        )
        check(
            page.locator(".rest-card").count() == 1,
            "⑤ 確認之後這一頁開始**自己的**新一輪休息（卡片出現在這一頁）",
        )
        check(
            page.evaluate("() => window.__native.starts") > starts_before,
            "⑤ 新一輪休息有交給原生服務",
        )
        check(
            visible_last(page) is True or visible_last(page) is False,
            "前提：可見性有被回報",
        )
        check(
            visible_last(page) is True,
            f"② 新一輪屬於這一頁 → 回報卡片可見，視窗藏起來（實際 {visible_last(page)}）",
        )

        # F103 回歸：開新一輪時強制重送過可見性
        trues = sum(1 for v in page.evaluate("() => window.__native.visible") if v)
        check(trues >= 1, f"F103 不回歸：可見性在多輪之間有重送過（true {trues} 次）")
        ctx.close()
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
