"""F110 E2E：「回 app 記下一組」要跳到那輪休息所屬動作的計時頁。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f110.py`

Ryan 2026-07-31：「如果是在 app 裡面，那回 app 記錄應該是要跳回那組動作的訓練頁面。」
在此之前那顆鈕只做 `getLaunchIntentForPackage` ＋ SINGLE_TOP 把 app 拉到前景，
**不指定要停在哪一頁**——WebView 停在哪就是哪。F108（休息綁定發起它的動作）之後這個
落差更明顯：休息屬於 A，你人在 B 的計時頁，按下去還是留在 B。

拉起 app 那一半是原生的事（Playwright 碰不到），這支只驗**導頁**這一半——
也就是前端收到 focus 事件之後做了什麼。

⚠ 要守住的反面：**導頁不得結束這輪休息**。F103 ① 明訂這顆鈕不是結束的入口，
而導頁如果不小心走到 finish()／stopRestTimer() 就會把它收掉，畫面上還看不太出來。
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
    FAKE_PLUGIN,
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


# F146 起 native setup 畫面沒有 token input（只有「使用 Google 登入」），且 F131 起
# 開機會走 restoreNativeSession() → initializeNativeSync()——缺 AuthSession／LocalStore／
# Sync 外掛會拋錯，卡在登入畫面或「正在準備本機資料」，永遠等不到這支腳本原本要驗的
# 計時頁流程。改成先跑 verify_f67 共用的假 plugin（登入＋本機資料庫），
# 再疊加這支腳本自己的 LocalNotifications／RestTimer／NotifyStatus——
# 兩段合成一支 init script 才能保證同步執行順序（window.Capacitor 一定先存在）。
EXTRA_PLUGINS = """
window.__native = { visible: [], handler: null, stops: 0 };
window.__emit = (action, seconds) => {
  const h = window.__native.handler;
  if (!h) return false;
  h(seconds === undefined ? { action } : { action, seconds });
  return true;
};
// F67 假 LocalStore 只種了一顆動作——這支腳本要在兩個動作之間切換（②），補第二顆。
// 包一層而不是整個重寫 LocalStore：createWorkout／addSet 等既有邏輯照舊可用。
const __baseSnapshot = window.Capacitor.Plugins.LocalStore.snapshot;
window.Capacitor.Plugins.LocalStore.snapshot = async () => {
  const data = await __baseSnapshot();
  return { ...data, exercises: [...data.exercises,
    { id: 2, name_zh: '臥推', name_en: 'Bench Press', muscle_group: '胸', is_bodyweight: 0 }] };
};
Object.assign(window.Capacitor.Plugins, {
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
    start: async () => ({}),
    stop: async () => { window.__native.stops += 1; return {}; },
    pause: async () => ({}), resume: async () => ({}),
    overlayPermitted: async () => ({ granted: true }),
    requestOverlayPermission: async () => {},
    setRestCardVisible: async (o) => {
      window.__native.visible.push(Boolean(o && o.visible));
      return {};
    },
    addListener: async (name, cb) => {
      if (name === 'restControl') window.__native.handler = cb;
      return { remove: () => {} };
    },
  },
  NotifyStatus: { openSettings: async () => {} },
});
"""


def open_app(browser, base: str):
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    plugin_script = FAKE_PLUGIN.strip().join(["(", ")(64, true);"])
    page.add_init_script(plugin_script + "\n" + EXTRA_PLUGINS)
    reroute_public_host(page, base)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input, .home-head", timeout=10_000)
    setup_and_home(page)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    page.evaluate(f"() => localStorage.setItem('{OVERLAY_FLAG}', '1')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return ctx, page


def enter_exercise(page, index: int) -> str:
    item = page.locator(".exercise-item").nth(index)
    name = item.inner_text().strip().split("\n")[0]
    item.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(500)
    return name


def logger_title(page) -> str:
    head = page.locator(".exercise-head-name h2")
    return head.first.inner_text().strip() if head.count() else "(不在計時頁)"


def emit(page, action: str) -> None:
    page.evaluate(f"() => window.__emit({action!r})")
    page.wait_for_timeout(1200)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f110-"))
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

        # ── ②：人在別的動作的計時頁 → 跳回所屬動作 ──────────────
        ctx, page = open_app(browser, base)
        wait_home(page)
        start_from_home(page)
        page.wait_for_timeout(1200)
        name_a = enter_exercise(page, 0)
        page.locator(".log-btn").first.click()
        page.wait_for_selector(".rest-card", timeout=8000)
        page.wait_for_timeout(700)

        page.locator(".logger-back").first.click()
        page.wait_for_timeout(700)
        name_b = enter_exercise(page, 1)
        check(logger_title(page) == name_b, f"前提：人在別的動作的計時頁（{logger_title(page)}）")
        check(page.locator(".rest-card").count() == 0, "前提：那一頁沒有休息卡（F108 ③）")

        stops_before = page.evaluate("() => window.__native.stops")
        emit(page, "focus")
        check(
            logger_title(page) == name_a,
            f"② 收到 focus → 跳到所屬動作的計時頁"
            f"（{name_b} → {logger_title(page)}，期望 {name_a}）",
        )
        check(
            page.locator(".rest-card").count() == 1,
            "③ 到了之後是所屬動作的正常休息態（休息卡在）",
        )
        # ⑤ 反面：這顆鈕不是結束這輪的入口
        check(
            page.evaluate("() => window.__native.stops") == stops_before,
            "⑤ 反面：導頁**不得**結束這輪休息（沒有回送原生停止指令）",
        )
        check(
            page.evaluate("() => window.__native.visible.at(-1)") is True,
            "③ 到了所屬動作的頁面 → 回報卡片可見（視窗會消失，F108 ②）",
        )
        ctx.close()

        # ── ②：人在非計時頁（菜單）→ 一樣要跳過去 ────────────────
        ctx, page = open_app(browser, base)
        wait_home(page)
        start_from_home(page)
        page.wait_for_timeout(1200)
        name_a = enter_exercise(page, 0)
        page.locator(".log-btn").first.click()
        page.wait_for_selector(".rest-card", timeout=8000)
        page.wait_for_timeout(700)
        page.locator(".logger-back").first.click()
        page.wait_for_timeout(800)
        check(page.locator(".logger-foot").count() == 0, "前提：人在菜單（不在計時頁）")
        emit(page, "focus")
        check(
            logger_title(page) == name_a,
            f"② 從菜單也要跳到所屬動作的計時頁（實際 {logger_title(page)}）",
        )
        ctx.close()

        # ── ④ 退路：沒有這輪休息時不要亂跳 ──────────────────────
        ctx, page = open_app(browser, base)
        wait_home(page)
        start_from_home(page)
        page.wait_for_timeout(1200)
        name_a = enter_exercise(page, 0)
        page.locator(".logger-back").first.click()
        page.wait_for_timeout(800)
        before = page.locator(".logger-foot").count()
        emit(page, "focus")
        check(
            page.locator(".logger-foot").count() == before,
            "④ 沒有進行中的休息（restExerciseId 為 null）→ **不跳**，停在原地",
        )
        ctx.close()

        # 已經在所屬動作的頁面：不重跳（重跳會把畫面上的編輯／捲動位置洗掉）
        ctx, page = open_app(browser, base)
        wait_home(page)
        start_from_home(page)
        page.wait_for_timeout(1200)
        name_a = enter_exercise(page, 0)
        page.locator(".log-btn").first.click()
        page.wait_for_selector(".rest-card", timeout=8000)
        page.wait_for_timeout(700)
        rows = page.locator(".done-row").count()
        emit(page, "focus")
        check(
            logger_title(page) == name_a and page.locator(".done-row").count() == rows,
            "④ 已經在所屬動作的頁面 → 不重跳（畫面狀態不被洗掉）",
        )
        check(
            page.locator(".rest-card").count() == 1,
            "⑤ 反面：在原地收到 focus 也不得把休息弄掉",
        )
        ctx.close()

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
