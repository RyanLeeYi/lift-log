"""F65 E2E：通知 channel 被單獨關閉時也要擋下（app 版，①–③）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f65.py`

**要防的情境**：使用者被休息提醒吵到，長按通知選「關閉這類通知」。app 層的
`areEnabled()` 仍然是 true（整個 app 的通知沒被關），但那一類通知的 channel
importance 被設成 IMPORTANCE_NONE(0)，之後排的提醒不會出現——而開關還顯示「開」。
這正是 F62 review 指出的靜默失敗。

⚠ 假 plugin 的界線（F62 的教訓：假物件會複製實作者的誤解）：這裡只證明
「前端有沒有把 channel importance 納入判定」。真機上長按通知關閉那類通知之後
系統回報什麼，仍要 Ryan 實測。

⚠ 每條情境都要有「反面」：只驗「關掉時顯示關」會被「永遠顯示關」的實作騙過去，
所以每組都配一條「正常時要顯示開」。
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
    start_server,
)

NOTIFY_FLAG = "liftlog.nativeNotifyEnabled"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def fake_plugins(*, app_enabled: bool, channels_js: str) -> str:
    """假的 LocalNotifications ＋ NotifyStatus。

    channels_js 是 listChannels() 要回傳的東西（整段 JS 運算式），刻意讓呼叫端
    自己決定——「沒有 channel」「channel importance=0」「listChannels 直接拋錯」
    是三種不同的情況，不能混為一談。
    """
    local_notifications = f"""
      schedule: async () => ({{}}),
      cancel: async () => ({{}}),
      checkPermissions: async () => ({{ display: 'granted' }}),
      requestPermissions: async () => ({{ display: 'granted' }}),
      areEnabled: async () => ({{ value: {str(app_enabled).lower()} }}),
      listChannels: async () => ({channels_js}),
    """
    notify_status = "openSettings: async () => { window.__notifyStatus.openedSettings += 1; },"
    return build_fake_capacitor(
        preamble="window.__notifyStatus = { openedSettings: 0 };",
        local_notifications=local_notifications,
        notify_status=notify_status,
    )


HEALTHY_CHANNELS = "{ channels: [{ id: 'default', importance: 4 }] }"
MUTED_CHANNELS = "{ channels: [{ id: 'default', importance: 0 }] }"
NO_CHANNELS = "{ channels: [] }"
THROWS = "(() => { throw new Error('listChannels not supported'); })()"


def toggle_label(page) -> str:
    """開關的狀態字串。

    F106 起設定頁是 switch，狀態不再寫在文字裡（標籤永遠是「休息提醒」），
    改由 `aria-checked` 表達——那是無障礙樹上的**渲染結果**，不是 class 名稱。
    這裡沿用舊的 `「休息提醒：開／關」` 形式，讓下面每條斷言的語意保持不變。
    """
    loc = page.locator(".switch-row [role=switch]")
    if not loc.count():
        return "(沒有開關)"
    on = loc.first.get_attribute("aria-checked") == "true"
    return f"休息提醒：{'開' if on else '關'}"


def open_app(browser, base: str, *, app_enabled: bool, channels_js: str, flag_on: bool):
    """開一個原生殼情境的分頁，回傳已經停在設定畫面的 page。"""
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    page.add_init_script(fake_plugins(app_enabled=app_enabled, channels_js=channels_js))
    reroute_public_host(page, base)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    if flag_on:
        # 使用者先前已經開過休息提醒——這是本條要處理的前提（開關記著「開」，
        # 但系統那邊被偷偷關掉了）
        page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
    open_settings(page)
    page.wait_for_timeout(600)
    return ctx, page


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f65-"))
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

        # ---------- 反面（前提）：一切正常時開關要顯示「開」 ----------
        ctx, page = open_app(
            browser, base, app_enabled=True, channels_js=HEALTHY_CHANNELS, flag_on=True
        )
        healthy = toggle_label(page)
        check(
            "休息提醒：開" in healthy,
            f"前提：app 通知允許 ＋ channel importance=4 → 開關顯示「開」（實際：{healthy}）",
        )
        ctx.close()

        # ---------- ①② channel 被單獨關閉（importance=0）----------
        ctx, page = open_app(
            browser, base, app_enabled=True, channels_js=MUTED_CHANNELS, flag_on=True
        )
        muted = toggle_label(page)
        check(
            "休息提醒：關" in muted,
            f"①② channel importance=0 → 開關顯示「關」，不是假的「開」（實際：{muted}）",
        )
        check(
            "開" not in muted.replace("關", ""),
            "①② 不得停在「開（可能延遲）」——那是精確鬧鐘的狀態，不是這一種",
        )

        # ① 「給引導」：點下去要把人送到系統設定頁，並說明是哪一種問題
        page.locator(".switch-row [role=switch]").first.click()
        page.wait_for_timeout(1200)
        opened = page.evaluate("() => window.__notifyStatus.openedSettings")
        check(opened >= 1, f"① 點開關會開啟系統通知設定頁（實際開了 {opened} 次）")
        banner = page.locator(".error-banner")
        msg = banner.first.inner_text() if banner.count() else ""
        check(
            banner.count() > 0 and ("這類" in msg or "類別" in msg or "channel" in msg.lower()),
            f"① 訊息要講清楚是「這類通知」被單獨關掉，不是整個 app（實際：{msg[:50] or '(無)'}）",
        )
        ctx.close()

        # ---------- ③ 既有情境不回歸：app 層被關 ----------
        ctx, page = open_app(
            browser, base, app_enabled=False, channels_js=HEALTHY_CHANNELS, flag_on=True
        )
        check(
            "休息提醒：關" in toggle_label(page),
            "③ 回歸：app 層通知被關（areEnabled=false）時仍然顯示「關」",
        )
        ctx.close()

        # ---------- 邊界：channel 還沒建立、或系統不支援 listChannels ----------
        # 第一次發通知前 Android 根本還沒有這個 channel。把「查不到」當成「被關掉」
        # 會讓沒排過通知的新裝置永遠開不起來——那是把功能擋死，不是保護。
        ctx, page = open_app(
            browser, base, app_enabled=True, channels_js=NO_CHANNELS, flag_on=True
        )
        check(
            "休息提醒：開" in toggle_label(page),
            "邊界：channel 尚未建立（清單是空的）不算被關掉——否則新裝置永遠開不了",
        )
        ctx.close()

        ctx, page = open_app(
            browser, base, app_enabled=True, channels_js=THROWS, flag_on=True
        )
        check(
            "休息提醒：開" in toggle_label(page),
            "邊界：listChannels 不支援／拋錯時退回 areEnabled 的判定，不擋掉功能",
        )
        ctx.close()

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
