"""F89 ⑥ E2E：浮動計時設定列的**三態**（開／關／未授權）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f89.py`

F89 的主體是原生 Java（圓環、兩態視窗、拖曳、動效），Playwright 碰不到，那些條文
（①–⑤⑦⑧⑨）一律真機驗。**只有 ⑥ 的設定列住在 WebView 裡**，這支就只驗那一條。

⚠ 每個狀態都配一條反面斷言：只驗「未授權時有副標」的話，「永遠顯示副標」的實作也全綠——
那正是這個缺口本來的樣子（原本只有開／關兩態，未授權被混進「關」裡看不出來）。

顏色驗的是 `getComputedStyle` 的結果，不是 class 名稱（F78 起的規矩：class 對不代表畫出來對）。
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
    open_settings,
    reroute_public_host,
    safe_port,
    setup_and_home,
    start_server,
)

NOTIFY_FLAG = "liftlog.nativeNotifyEnabled"
OVERLAY_FLAG = "liftlog.restOverlayEnabled"

# app.css :root 的 token（--text-faint / --card-hi），rgb 形式方便跟 computed style 直接比
TEXT_FAINT = "rgb(110, 99, 87)"  # #6E6357
CARD_HI = "rgb(59, 52, 44)"  # #3B342C

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def fake_plugins(granted: bool) -> str:
    """假 Capacitor：通知全開（設定列才會出現），overlay 授權由參數決定。"""
    js_granted = "true" if granted else "false"
    return f"""
window.__overlay = {{ requested: 0 }};
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


def overlay_toggle(page):
    """設定畫面上「浮動計時」那一列（休息提醒是同 class 的第一列）。"""
    return page.locator(".switch-row", has_text="浮動計時").first


def overlay_state(page) -> str:
    """F106 起狀態由 switch 表達，不寫在文字裡——沿用舊的字串形式讓斷言語意不變。"""
    sw = overlay_toggle(page).locator("[role=switch]").first
    return f"浮動計時：{'開' if sw.get_attribute('aria-checked') == 'true' else '關'}"


def open_app(browser, base: str, *, granted: bool, overlay_on: bool):
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    page.add_init_script(fake_plugins(granted))
    reroute_public_host(page, base)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    if overlay_on:
        page.evaluate(f"() => localStorage.setItem('{OVERLAY_FLAG}', '1')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    open_settings(page)
    page.wait_for_timeout(600)
    return ctx, page


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f89-"))
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

        # ── 態 1：已授權、使用者自己關著 ──「關」，而且**沒有**引導副標
        ctx, page = open_app(browser, base, granted=True, overlay_on=False)
        row = overlay_toggle(page)
        check(row.count() == 1, "設定畫面有「浮動計時」這一列")
        check(
            overlay_state(page) == "浮動計時：關",
            f"態1 已授權未開 → switch 在 OFF（{overlay_state(page)}）",
        )
        check(
            row.locator(".switch-sub").count() == 0,
            "態1 反面：使用者自己關的不掛副標——沒授權問題就不要喊授權",
        )
        check(
            "需系統授權" not in row.inner_text(),
            "態1 反面：沒有引導副標（永遠顯示副標的實作要在這裡掛掉）",
        )
        ctx.close()

        # ── 態 2：已授權且開著 ──「開」
        ctx, page = open_app(browser, base, granted=True, overlay_on=True)
        row = overlay_toggle(page)
        check(
            overlay_state(page) == "浮動計時：開",
            f"態2 已授權且開啟 → switch 在 ON（{overlay_state(page)}）",
        )
        check("需系統授權" not in row.inner_text(), "態2 反面：開著時沒有引導副標")
        ctx.close()

        # ── 態 3：系統未授權 ── 維持 OFF 外觀 ＋ 常駐副標
        ctx, page = open_app(browser, base, granted=False, overlay_on=False)
        row = overlay_toggle(page)
        text = row.inner_text()
        check(overlay_state(page) == "浮動計時：關", f"⑥ 未授權 → 開關維持 OFF（{text!r}）")
        check(
            "需系統授權 · 點此前往設定" in text,
            f"⑥ 常駐副標「需系統授權 · 點此前往設定」（{text!r}）",
        )
        # F106 之後「軌道」與「鈕」是真的存在的零件，這條終於能照凍結條文的字面驗
        # （先前是藥丸按鈕，只能對應成「按鈕底＝軌道、文字＝鈕」）。
        knob = row.locator(".switch-knob").first.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        track = row.locator(".switch-track").first.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        check(knob == TEXT_FAINT, f"⑥ 鈕用 --text-faint（實際 {knob}）")
        check(track == CARD_HI, f"⑥ 軌道維持 --card-hi（實際 {track}）")
        # 反面：未授權時不能長得像「開」
        check(
            row.locator("[role=switch].on").count() == 0,
            "⑥ 反面：未授權時不得顯示成開——假的「開」正是 F64 ② 要防的事",
        )
        # F74 觸控目標：多一行副標也不能把高度壓掉
        box = row.bounding_box()
        check(
            box["height"] >= 44,
            f"F74 不回歸：未授權態的列高 ≥44px（實際 {box['height']:.0f}px）",
        )

        # ⑥ 點下去要送到系統授權頁（F106 ③ 起出路在副標那一行，不是整列）
        row.locator(".switch-sub").first.click()
        page.wait_for_timeout(900)
        requested = page.evaluate("() => window.__overlay.requested")
        check(requested >= 1, f"⑥ 點擊送往系統「顯示在其他應用程式上層」頁（實際 {requested} 次）")
        # 未授權時按了也不能翻成「開」（假的成功比失敗更糟）
        check(
            overlay_state(page) == "浮動計時：關",
            "⑥ 反面：授權沒拿到就不能翻成「開」",
        )
        ctx.close()

        # 未授權 ＋ 使用者旗標還留著（曾經開過、後來被系統收回授權）：一樣是未授權態
        ctx, page = open_app(browser, base, granted=False, overlay_on=True)
        text = overlay_toggle(page).inner_text()
        check(
            overlay_state(page) == "浮動計時：關" and "需系統授權" in text,
            f"邊界：旗標還在但授權被收回 → 仍是未授權態，不是「開」（{text!r}）",
        )
        ctx.close()

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
