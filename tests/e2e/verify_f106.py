"""F106 E2E：設定頁的兩顆開關改成真 switch（軌道＋鈕），出路移到可點副標。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f106.py`

這條的來源是 F89 ⑥ 的規格落差：凍結條文寫的是 switch 的「軌道」與「鈕」，但設定頁自 F81
起是藥丸按鈕、沒有這兩個零件。Ryan 2026-07-31 選擇改實作而不是改條文。

⚠ 驗的是**渲染結果**不是 class（F78 起的規矩）：軌道與鈕的顏色量 getComputedStyle，
鈕真的有沒有移動量 bounding_box 前後比對。只驗 class 的話，「掛了 class 但 CSS 沒生效」
全綠——F73 的停止鈕警示色就是這樣假綠了好幾條 feature。

⚠ ③ 的行為改動要配反面斷言：副標可點**且點了不會切換開關**。少了後半條，
「副標點下去順便把開關關掉」也會全綠，而那正是把出路搬出來要避免的事。
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
    open_settings,
    reroute_public_host,
    safe_port,
    setup_and_home,
    start_server,
)

NOTIFY_FLAG = "liftlog.nativeNotifyEnabled"
OVERLAY_FLAG = "liftlog.restOverlayEnabled"

# app.css :root 的 token，rgb 形式方便直接跟 computed style 比
TEXT_FAINT = "rgb(110, 99, 87)"  # #6E6357
CARD_HI = "rgb(59, 52, 44)"  # #3B342C
ACCENT = "rgb(217, 178, 95)"  # #D9B25F

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def fake_plugins(granted: bool, exact: bool = True) -> str:
    """假 Capacitor：通知全開（兩列才會出現），overlay 授權與精確鬧鐘由參數決定。"""
    js_granted = "true" if granted else "false"
    js_exact = "true" if exact else "false"
    return f"""
window.__overlay = {{ requested: 0 }};
window.__exact = {{ requested: 0 }};
window.Capacitor = {{
  isNativePlatform: () => true,
  getPlatform: () => 'android',
  Plugins: {{
    LocalNotifications: {{
      schedule: async () => ({{}}),
      cancel: async () => ({{}}),
      checkPermissions: async () => ({{ display: 'granted' }}),
      requestPermissions: async () => ({{ display: 'granted' }}),
      areEnabled: async () => ({{ value: true }}),
      checkExactNotificationSetting: async () =>
        ({{ exact_alarm: {js_exact} ? 'granted' : 'denied' }}),
      changeExactNotificationSetting: async () => {{ window.__exact.requested += 1; }},
      listChannels: async () => ({{ channels: [
        {{ id: 'default', importance: 3 }}, {{ id: 'rest-timer', importance: 2 }},
      ] }}),
    }},
    RestTimer: {{
      start: async () => ({{ started: true }}),
      stop: async () => ({{}}),
      pause: async () => ({{}}),
      resume: async () => ({{}}),
      overlayPermitted: async () => ({{ granted: {js_granted} }}),
      requestOverlayPermission: async () => {{ window.__overlay.requested += 1; }},
      setRestCardVisible: async () => ({{}}),
      addListener: async () => ({{ remove: () => {{}} }}),
    }},
    NotifyStatus: {{ openSettings: async () => {{}} }},
  }},
}};
"""


def row(page, label: str):
    """一整列（switch ＋ 可能有的副標）。"""
    return page.locator(".switch-row", has_text=label).first


def sw(page, label: str):
    """列裡面那顆 switch 本體。"""
    return row(page, label).locator("[role=switch]").first


def open_app(
    browser,
    base: str,
    *,
    granted: bool = True,
    overlay_on: bool = False,
    exact: bool = True,
    reduced_motion: str = "no-preference",
):
    ctx = browser.new_context(viewport=PHONE, reduced_motion=reduced_motion)
    page = ctx.new_page()
    page.add_init_script(fake_plugins(granted, exact))
    reroute_public_host(page, base)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    # F107：「可能延遲」要**兩個**條件——精確鬧鐘被關，且前景服務實際接不了手過。
    # 這支要驗的是副標這個載體，所以把紀錄直接種進去，不去跑一輪休息。
    if not exact:
        page.evaluate("() => localStorage.setItem('liftlog.fgFallbackSeen', '1')")
    if overlay_on:
        page.evaluate(f"() => localStorage.setItem('{OVERLAY_FLAG}', '1')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    open_settings(page)
    page.wait_for_timeout(600)
    return ctx, page


def knob_offset(page, label: str) -> float:
    """鈕的左緣相對軌道左緣的距離——量「有沒有真的移動」，不看 class。"""
    r = row(page, label)
    track = r.locator(".switch-track").first.bounding_box()
    knob = r.locator(".switch-knob").first.bounding_box()
    return knob["x"] - track["x"]


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f106-"))
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

        # ── ① 兩顆都是 switch ────────────────────────────────────
        ctx, page = open_app(browser, base, granted=True, overlay_on=False)
        check(
            sw(page, "休息提醒").count() == 1,
            "① 休息提醒是 role=switch",
        )
        check(
            sw(page, "浮動計時").count() == 1,
            "① 浮動計時是 role=switch",
        )
        check(
            page.locator(".push-toggle").count() == 0,
            "① 反面：藥丸按鈕（.push-toggle）已經沒有殘留——只改一顆的實作要在這裡掛掉",
        )
        # ⑥ 無障礙
        check(
            sw(page, "休息提醒").get_attribute("aria-checked") == "true",
            "⑥ 休息提醒開著 → aria-checked=true",
        )
        check(
            sw(page, "浮動計時").get_attribute("aria-checked") == "false",
            "⑥ 浮動計時關著 → aria-checked=false",
        )

        # ── ② OFF 的顏色：軌道 --card-hi、鈕 --text-faint ────────
        off = row(page, "浮動計時")
        track_bg = off.locator(".switch-track").first.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        knob_bg = off.locator(".switch-knob").first.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        check(track_bg == CARD_HI, f"② OFF 軌道 --card-hi（實際 {track_bg}）")
        check(knob_bg == TEXT_FAINT, f"② OFF 鈕 --text-faint（實際 {knob_bg}）")

        # ── ② ON 的顏色：軌道 --accent ───────────────────────────
        on_track_bg = (
            row(page, "休息提醒")
            .locator(".switch-track")
            .first.evaluate("el => getComputedStyle(el).backgroundColor")
        )
        check(on_track_bg == ACCENT, f"② ON 軌道 --accent（實際 {on_track_bg}）")
        check(
            on_track_bg != track_bg,
            "② 反面：ON 與 OFF 的軌道顏色不同（同色＝看不出開關狀態）",
        )

        # ── ⑨ 鈕真的有移動（量位置，不看 class） ─────────────────
        off_x = knob_offset(page, "浮動計時")
        on_x = knob_offset(page, "休息提醒")
        check(
            on_x > off_x + 4,
            f"⑨ ON 的鈕比 OFF 的鈕更靠右（OFF {off_x:.0f}px → ON {on_x:.0f}px）",
        )

        # 撥動同一顆，位置要跟著變（跨列比對可能被寬度差異矇混）
        before = knob_offset(page, "浮動計時")
        sw(page, "浮動計時").click()
        page.wait_for_timeout(600)
        after = knob_offset(page, "浮動計時")
        check(
            after > before + 4,
            f"⑨ 同一顆撥開之後鈕往右移（{before:.0f}px → {after:.0f}px）",
        )
        check(
            sw(page, "浮動計時").get_attribute("aria-checked") == "true",
            "⑥ 撥開之後 aria-checked 跟著變 true",
        )

        # ── ⑤ 觸控目標 ──────────────────────────────────────────
        box = sw(page, "浮動計時").bounding_box()
        check(box["height"] >= 44, f"⑤ switch 命中區高 ≥44px（實際 {box['height']:.0f}px）")
        check(box["width"] >= 44, f"⑤ switch 命中區寬 ≥44px（實際 {box['width']:.0f}px）")

        # ── ⑦ 動畫 ≤200ms ───────────────────────────────────────
        dur = (
            row(page, "浮動計時")
            .locator(".switch-knob")
            .first.evaluate("el => getComputedStyle(el).transitionDuration")
        )
        secs = max(float(x.replace("s", "")) for x in dur.split(",")) if dur else 0.0
        check(0 < secs <= 0.2, f"⑦ 鈕的位移動畫 >0 且 ≤200ms（實際 {dur}）")
        ctx.close()

        # ⑦ reduced-motion 下不做位移
        ctx, page = open_app(browser, base, reduced_motion="reduce")
        dur = (
            row(page, "浮動計時")
            .locator(".switch-knob")
            .first.evaluate("el => getComputedStyle(el).transitionDuration")
        )
        secs = max(float(x.replace("s", "")) for x in dur.split(",")) if dur else 0.0
        check(secs == 0.0, f"⑦ prefers-reduced-motion 下不做位移動畫（實際 {dur}）")
        # 反面：不做動畫不代表不換色——狀態還是要看得出來
        check(
            sw(page, "休息提醒").get_attribute("aria-checked") == "true",
            "⑦ 反面：reduced-motion 下開關狀態照常正確",
        )
        ctx.close()

        # ── ③④ 未授權態：副標是獨立的可點目標 ────────────────────
        ctx, page = open_app(browser, base, granted=False, overlay_on=False)
        r = row(page, "浮動計時")
        sub = r.locator(".switch-sub").first
        check(sub.count() == 1, "③ 未授權時有副標列")
        check(
            "需系統授權 · 點此前往設定" in sub.inner_text(),
            f"③ 副標文案（實際 {sub.inner_text()!r}）",
        )
        check(
            sw(page, "浮動計時").get_attribute("aria-checked") == "false",
            "④ 未授權 → switch 維持 OFF",
        )

        sub_box = sub.bounding_box()
        sw_box = sw(page, "浮動計時").bounding_box()
        check(
            sub_box["height"] >= 44,
            f"⑤ 副標命中區高 ≥44px（實際 {sub_box['height']:.0f}px）",
        )
        gap = sub_box["y"] - (sw_box["y"] + sw_box["height"])
        check(gap >= 8, f"⑤ switch 與副標間距 ≥8px（實際 {gap:.0f}px）")

        # ③ 點副標＝去系統授權頁，**且不切換開關**
        sub.click()
        page.wait_for_timeout(800)
        check(
            page.evaluate("() => window.__overlay.requested") >= 1,
            "③ 點副標送往系統「顯示在其他應用程式上層」頁",
        )
        check(
            sw(page, "浮動計時").get_attribute("aria-checked") == "false",
            "③ 反面：點副標**不會**切換開關（順手關掉開關的實作要在這裡掛掉）",
        )

        # ④ 直接撥 switch 也要送去授權頁，且維持 OFF
        before = page.evaluate("() => window.__overlay.requested")
        sw(page, "浮動計時").click()
        page.wait_for_timeout(800)
        check(
            page.evaluate("() => window.__overlay.requested") > before,
            "④ 未授權時撥向 ON → 送去系統授權頁",
        )
        check(
            sw(page, "浮動計時").get_attribute("aria-checked") == "false",
            "④ 反面：授權沒拿到就不得顯示成「開」（假的成功比失敗更糟）",
        )
        ctx.close()

        # ── ⑧ F62 ③ 不回歸：精確鬧鐘被關 → 休息提醒也有可點副標 ──
        ctx, page = open_app(browser, base, exact=False)
        r = row(page, "休息提醒")
        sub = r.locator(".switch-sub").first
        check(sub.count() == 1, "⑧ F62 ③ 不回歸：精確鬧鐘被關時休息提醒有副標")
        check(
            "點此修正" in sub.inner_text(),
            f"⑧ 副標帶出路（實際 {sub.inner_text()!r}）",
        )
        check(
            sw(page, "休息提醒").get_attribute("aria-checked") == "true",
            "⑧ 精確鬧鐘被關**不影響**開關本身是開著的（只是可能延遲，不擋功能）",
        )
        sub.click()
        page.wait_for_timeout(800)
        check(
            page.evaluate("() => window.__exact.requested") >= 1,
            "⑧ 點副標開系統「鬧鐘與提醒」授權頁",
        )
        check(
            sw(page, "休息提醒").get_attribute("aria-checked") == "true",
            "⑧ 反面：點副標不得把休息提醒關掉",
        )
        ctx.close()

        # ── ⑧ 精確鬧鐘正常時不掛副標（反面） ─────────────────────
        ctx, page = open_app(browser, base, exact=True)
        check(
            row(page, "休息提醒").locator(".switch-sub").count() == 0,
            "⑧ 反面：精確鬧鐘正常時休息提醒沒有副標（永遠顯示副標的實作要在這裡掛掉）",
        )
        ctx.close()

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
