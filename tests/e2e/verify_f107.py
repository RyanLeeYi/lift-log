"""F107 E2E：「可能延遲」只在真的會延遲時才警告。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f107.py`

現況是誤報：只要精確鬧鐘權限被關就警告。但自 F63 起休息倒數的主要路徑是**原生前景服務**
（自己跑 CountDownTimer），完全不碰鬧鐘排程；精確鬧鐘只在前景服務啟不動時的退路才用得到。

⚠ 這條的判斷依據是**觀測結果**（前景服務實際接不了手），不是預判——Android 沒有
「我等一下起不起得來前景服務」的查詢 API。所以測試分兩層：
  1. 三種組合的**渲染結果**（權限開／權限關無紀錄／權限關有紀錄）
  2. **紀錄本身怎麼來的**：真的跑一輪休息，讓假 plugin 回報接手失敗／成功，看紀錄有沒有跟著變

第 2 層不能省。只驗第 1 層的話，「紀錄永遠寫不進去」的實作會全綠（副標從此再也不出現，
等於把 F62 ③ 的出路整條刪掉），而那是比誤報更糟的結果。
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


from fake_capacitor import build_fake_capacitor  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    open_settings,
    reroute_public_host,
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
    wait_home,
)

NOTIFY_FLAG = "liftlog.nativeNotifyEnabled"
FALLBACK_FLAG = "liftlog.fgFallbackSeen"  # F107：前景服務接不了手的紀錄

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def fake_plugins(exact: bool, fg_takes: bool) -> str:
    """假 Capacitor。

    `fg_takes` 是本條的關鍵旋鈕：前景服務接不接得了手。
    `start` 拋錯＝啟不動（Android 12+ 背景啟動限制、OEM 省電策略…），這正是
    `startForegroundRest()` 裡那個 catch 要處理的情境；倒數於是退回 F62 的本機通知，
    也才輪得到精確鬧鐘影響準時度。

    ⚠ `available()` 一定要有——`startForegroundRest()` 先問它再 start，
    假物件缺了它會在那一步就 catch 掉，看起來像「接不了手」但其實連問都沒問到
    （F95 的「假物件缺了某個 plugin」是同一族的假綠）。
    """
    js_exact = "true" if exact else "false"
    js_started = "true" if fg_takes else "false"
    local_notifications = f"""
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
    """
    rest_timer = f"""
      available: async () => ({{ available: true }}),
      start: async () => {{
        window.__fg.starts += 1;
        if (!{js_started}) throw new Error('foreground service blocked');
        return {{}};
      }},
      stop: async () => ({{}}),
      pause: async () => ({{}}),
      resume: async () => ({{}}),
      overlayPermitted: async () => ({{ granted: true }}),
      requestOverlayPermission: async () => {{}},
      setRestCardVisible: async () => ({{}}),
      addListener: async () => ({{ remove: () => {{}} }}),
    """
    return build_fake_capacitor(
        preamble="window.__exact = { requested: 0 };\nwindow.__fg = { starts: 0 };",
        local_notifications=local_notifications,
        rest_timer=rest_timer,
        notify_status="openSettings: async () => {},",
    )


def notify_row(page):
    return page.locator(".switch-row", has_text="休息提醒").first


def sub_text(page) -> str:
    sub = notify_row(page).locator(".switch-sub")
    return sub.first.inner_text().strip() if sub.count() else ""


def open_app(browser, base: str, *, exact: bool, fg_takes: bool = True, fallback_seen=None):
    """`fallback_seen=None` 代表不動那個紀錄（用實際跑出來的）。"""
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    page.add_init_script(fake_plugins(exact, fg_takes))
    reroute_public_host(page, base)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    if fallback_seen is True:
        page.evaluate(f"() => localStorage.setItem('{FALLBACK_FLAG}', '1')")
    elif fallback_seen is False:
        page.evaluate(f"() => localStorage.removeItem('{FALLBACK_FLAG}')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return ctx, page


def rest_once(page) -> None:
    """真的跑一輪休息：記一組就會排提醒，那時才問得到前景服務接不接得了手。"""
    wait_home(page)
    start_from_home(page)
    page.wait_for_timeout(1200)
    page.locator(".exercise-item").first.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(400)
    page.locator(".log-btn").first.click()
    page.wait_for_timeout(1500)  # 等 startForegroundRest 的 promise 回來


def back_to_settings(page) -> None:
    """從 logger 回首頁再進設定（齒輪只在首頁）。"""
    page.locator(".logger-back").first.click()
    page.wait_for_timeout(700)
    page.get_by_role("button", name="回首頁").first.click()
    page.wait_for_timeout(900)
    open_settings(page)
    page.wait_for_timeout(600)


def fallback_flag(page) -> str | None:
    return page.evaluate(f"() => localStorage.getItem('{FALLBACK_FLAG}')")


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f107-"))
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

        # ── 組合 1：精確鬧鐘正常 ＋ 有失敗紀錄 → 不警告 ──────────
        # 反面用的：權限沒被關就沒有「可能延遲」這回事，紀錄再多也一樣
        ctx, page = open_app(browser, base, exact=True, fallback_seen=True)
        wait_home(page)
        open_settings(page)
        page.wait_for_timeout(600)
        check(
            sub_text(page) == "",
            f"② 精確鬧鐘正常 → 不警告（即使有失敗紀錄；實際 {sub_text(page)!r}）",
        )
        ctx.close()

        # ── 組合 2：精確鬧鐘被關 ＋ 沒有失敗紀錄 → 不警告（樂觀） ─
        # 這條就是本 feature 要消滅的誤報：F63 起主路徑是前景服務，根本不碰鬧鐘排程
        ctx, page = open_app(browser, base, exact=False, fallback_seen=False)
        wait_home(page)
        open_settings(page)
        page.wait_for_timeout(600)
        check(
            sub_text(page) == "",
            f"① 精確鬧鐘被關但前景服務沒出過事 → **不警告**（實際 {sub_text(page)!r}）",
        )
        # 反面：不警告不等於把開關弄壞
        check(
            notify_row(page).locator("[role=switch]").first.get_attribute("aria-checked")
            == "true",
            "① 反面：不警告時開關本身照常是開著的",
        )
        ctx.close()

        # ── 組合 3：精確鬧鐘被關 ＋ 有失敗紀錄 → 警告 ────────────
        ctx, page = open_app(browser, base, exact=False, fallback_seen=True)
        wait_home(page)
        open_settings(page)
        page.wait_for_timeout(600)
        check(
            "可能延遲" in sub_text(page),
            f"② 兩個條件都成立 → 警告（實際 {sub_text(page)!r}）",
        )
        check(
            "點此修正" in sub_text(page),
            f"⑥ F62 ③ 不回歸：警告要帶出路（實際 {sub_text(page)!r}）",
        )
        # ⑥ 出路真的走得通（F106 ③ 起在副標上）
        notify_row(page).locator(".switch-sub").first.click()
        page.wait_for_timeout(800)
        check(
            page.evaluate("() => window.__exact.requested") >= 1,
            "⑥ 點副標開系統「鬧鐘與提醒」授權頁",
        )
        ctx.close()

        # ── ③ 紀錄怎麼來的：前景服務接不了手 → 寫進紀錄 ──────────
        # 只驗上面三組的話，「紀錄永遠寫不進去」的實作會全綠，而那等於把出路整條刪掉
        ctx, page = open_app(browser, base, exact=False, fg_takes=False, fallback_seen=False)
        check(fallback_flag(page) is None, "③ 前提：一開始沒有失敗紀錄")
        rest_once(page)
        check(
            page.evaluate("() => window.__fg.starts") >= 1,
            "③ 前提：記一組真的有去問前景服務接不接得了手",
        )
        check(
            fallback_flag(page) == "1",
            f"③ 前景服務回報接不了手 → 寫下紀錄（實際 {fallback_flag(page)!r}）",
        )
        back_to_settings(page)
        check(
            "可能延遲" in sub_text(page),
            f"③ 紀錄寫下之後，設定頁就會警告了（實際 {sub_text(page)!r}）",
        )
        ctx.close()

        # ── ③ 紀錄會清掉：接手成功一次就不該再掛著警告 ───────────
        ctx, page = open_app(browser, base, exact=False, fg_takes=True, fallback_seen=True)
        check(fallback_flag(page) == "1", "③ 前提：帶著上次的失敗紀錄開 app")
        rest_once(page)
        check(
            fallback_flag(page) is None,
            f"③ 前景服務接手成功 → 清掉紀錄（實際 {fallback_flag(page)!r}）",
        )
        back_to_settings(page)
        check(
            sub_text(page) == "",
            f"③ 清掉之後警告跟著消失——一次失敗不該永久掛著（實際 {sub_text(page)!r}）",
        )
        ctx.close()

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
