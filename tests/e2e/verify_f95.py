"""F95 E2E：前景服務的 rest-timer channel 被單獨關閉時也要擋下（①–⑤）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f95.py`

**與 F65 的差別**：F65 只看 Capacitor 的 `default` channel，但 F63 之後使用者實際
看到、也實際會去長按的那則倒數通知掛在前景服務自己的 `rest-timer`（RestTimerService，
顯示名「休息倒數」）。default 那條只是前景服務啟不動時的退路——平常根本走不到。

⚠ 所以這支腳本的假 plugin **一定要有 RestTimer**。F65 的 verify_f65.py 沒有它，
測到的一律是退路那條，那正是這個缺口能躲過整輪測試的原因。
（F62 的教訓：假物件會複製實作者的誤解。這次的誤解是「假物件缺了某個 plugin」。）

⚠ 每組情境都配一條反面，否則「永遠顯示關」的實作也會全綠。
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
    TOKEN,
    open_settings,
    reroute_public_host,
    safe_port,
    start_server,
    wait_home,
)

NOTIFY_FLAG = "liftlog.nativeNotifyEnabled"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def fake_plugins(channels_js: str) -> str:
    """假 LocalNotifications（含 listChannels）＋ RestTimer ＋ NotifyStatus。

    RestTimer 存在才會走到 F63 的前景服務路徑——這正是 F65 漏掉的那條。
    """
    token = TOKEN
    auth_session = f"""
      loadSession: async () => ({{
        // 用伺服器認得的那把 token 當 access token：本機 e2e server 走 legacy Bearer，
        // 隨便給一個字串會 401，app 會判定登入失效並把畫面踢回 setup。
        accessToken: '{token}',
        refreshToken: 'test-refresh',
        accessExpiresAt: Date.now() + 900000,
        deviceId: '11111111-1111-4111-8111-111111111111',
      }}),
      saveSession: async () => ({{}}),
      clearSession: async () => ({{}}),
    """
    local_store = """
      initialize: async () => ({ schemaVersion: 3, seededExercises: 0 }),
      snapshot: async () => __snapshot,
      status: async () => ({ pendingMutations: 0 }),
    """
    sync = """
      initialize: async () => ({
        state: 'synced', pending: 0, failed: 0, cursor: 1,
        lastSyncedAt: 1000, bootstrapComplete: true,
      }),
      status: async () => ({
        state: 'synced', pending: 0, failed: 0, cursor: 1,
        lastSyncedAt: 1000, bootstrapComplete: true,
      }),
      syncNow: async () => ({
        state: 'synced', pending: 0, failed: 0, cursor: 1,
        lastSyncedAt: 1000, bootstrapComplete: true,
      }),
    """
    local_notifications = f"""
      schedule: async () => ({{}}),
      cancel: async () => ({{}}),
      checkPermissions: async () => ({{ display: 'granted' }}),
      requestPermissions: async () => ({{ display: 'granted' }}),
      areEnabled: async () => ({{ value: true }}),
      listChannels: async () => (window.__channels || {channels_js}),
    """
    rest_timer = """
      start: async () => ({ started: true }),
      stop: async () => ({}),
      pause: async () => ({}),
      resume: async () => ({}),
      overlayPermitted: async () => ({ granted: false }),
      setCardVisible: async () => ({}),
      addListener: async () => ({ remove: () => {} }),
    """
    notify_status = "openSettings: async () => { window.__notifyStatus.openedSettings += 1; },"
    # F149 之後 app 版的開機路徑是「Google session -> LocalStore -> Sync bootstrap」，
    # 不再有 token 輸入框。假 plugin 少了這三個就永遠停在登入畫面，整支腳本連設定頁都到不了。
    preamble = """
window.__notifyStatus = { openedSettings: 0 };
const __snapshot = {
  exercises: [], templates: [], workouts: [], sets: [],
  body_metrics: [], daily_status: [], settings: [],
};
"""
    return build_fake_capacitor(
        preamble=preamble,
        auth_session=auth_session,
        local_store=local_store,
        sync=sync,
        local_notifications=local_notifications,
        rest_timer=rest_timer,
        notify_status=notify_status,
    )


BOTH_OK = "{ channels: [{ id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 }] }"
TIMER_MUTED = (
    "{ channels: [{ id: 'default', importance: 3 }, { id: 'rest-timer', importance: 0 }] }"
)
DEFAULT_MUTED = (
    "{ channels: [{ id: 'default', importance: 0 }, { id: 'rest-timer', importance: 2 }] }"
)
TIMER_ABSENT = "{ channels: [{ id: 'default', importance: 3 }] }"
# F166（2026-08-24 Ryan 拍板選 (b)）：開關「關」的判定只看 `rest-alarm`
# （歸零那則「休息時間到」——真正會漏掉的提醒）；rest-timer／default 是資訊不是提醒。
# ALL_OK 是 ④ 的反面——三個都正常時必須顯示「開」，否則新條件只是把開關焊死。
ALL_OK = (
    "{ channels: [{ id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 },"
    " { id: 'rest-alarm', importance: 4 }] }"
)
ALARM_MUTED = (
    "{ channels: [{ id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 },"
    " { id: 'rest-alarm', importance: 0 }] }"
)
# ④ 反面：rest-timer 被關但 rest-alarm 正常 → 依 (b) 要顯示「開」
TIMER_MUTED_ALARM_OK = (
    "{ channels: [{ id: 'default', importance: 3 }, { id: 'rest-timer', importance: 0 },"
    " { id: 'rest-alarm', importance: 4 }] }"
)


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


def open_app(browser, base: str, channels_js: str):
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    page.add_init_script(fake_plugins(channels_js))
    reroute_public_host(page, base)
    # 設定頁一進來就列 MCP token，而 legacy Bearer 在那支 endpoint 一律 401（F147 刻意的），
    # 401 會被 guard() 判成登入失效、把畫面踢回 setup——那跟 F95 要驗的東西無關。
    # ⚠ 必須註冊在 reroute_public_host 之後：Playwright 是後註冊的先比對。
    page.route(
        "**/api/mcp-tokens/**",
        lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
    )
    page.goto(base, wait_until="domcontentloaded")
    wait_home(page, timeout=15_000)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    page.reload(wait_until="domcontentloaded")
    wait_home(page, timeout=15_000)
    open_settings(page)
    page.wait_for_timeout(600)
    return ctx, page


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f95-"))
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

        # 反面（前提）：兩個 channel 都正常時要顯示「開」
        ctx, page = open_app(browser, base, BOTH_OK)
        label = toggle_label(page)
        check(
            "休息提醒：開" in label,
            f"前提：default 與 rest-timer 都正常 → 開關顯示「開」（實際：{label}）",
        )
        ctx.close()

        # ③（F166 (b) 改定）：只有 rest-alarm 被關才算「關」——這裡同時驗 ⑤ 的引導
        ctx, page = open_app(browser, base, ALARM_MUTED)
        label = toggle_label(page)
        check(
            "休息提醒：關" in label,
            f"③ rest-alarm importance=0 → 顯示「關」（實際：{label}）",
        )
        # ⑤ 引導：把人送到設定頁，訊息不寫死類別名稱
        page.locator(".switch-row [role=switch]").first.click()
        page.wait_for_timeout(1200)
        opened = page.evaluate("() => window.__notifyStatus.openedSettings")
        check(opened >= 1, f"⑤ 點開關會開啟系統通知設定頁（實際 {opened} 次）")
        msg = page.locator(".error-banner").first.inner_text() if page.locator(
            ".error-banner"
        ).count() else ""
        check(
            "這類" in msg or "類別" in msg,
            f"⑤ 訊息指出是「通知類別」被單獨關掉（實際：{msg[:40] or '(無)'}）",
        )
        check(
            "Default" not in msg and "休息倒數" not in msg and "休息結束" not in msg,
            "⑤ 訊息不寫死類別名稱——講錯名字會讓人在對的頁面上找不到東西",
        )
        ctx.close()

        # F166 (b)：default／rest-timer 被關**不再**影響開關（只想關倒數常駐的人不該被說成「關」）
        ctx, page = open_app(browser, base, DEFAULT_MUTED)
        check(
            "休息提醒：開" in toggle_label(page),
            "F166 (b)：default importance=0（rest-alarm 未建立）→ 顯示「開」",
        )
        ctx.close()

        ctx, page = open_app(browser, base, TIMER_MUTED_ALARM_OK)
        check(
            "休息提醒：開" in toggle_label(page),
            "F166 ④ 反面：rest-timer importance=0 但 rest-alarm 正常 → 顯示「開」",
        )
        ctx.close()

        # 回前景要重查——而且**在設定畫面上也要重繪**。
        # F81 把開關搬進設定畫面後，原本「只有首頁重繪」的條件剛好蓋不到它：
        # 使用者跑去系統設定關掉這類通知、切回來，開關繼續顯示舊狀態（真機實測抓到）。
        ctx, page = open_app(browser, base, ALL_OK)
        check("休息提醒：開" in toggle_label(page), "前提：一開始顯示「開」（人在設定畫面）")
        page.evaluate(f"() => {{ window.__channels = {ALARM_MUTED}; }}")
        page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_timeout(900)
        check(
            "休息提醒：關" in toggle_label(page),
            f"切回前景後，設定畫面上的開關要跟著更新（實際：{toggle_label(page)}）",
        )
        ctx.close()

        # F166 ④：另外兩個 channel 都正常，只有 rest-alarm 被關 → 仍要顯示「關」。
        # 那則才是「時間到」本身，漏掉它等於讓最該響的提醒靜默失敗。
        ctx, page = open_app(browser, base, ALARM_MUTED)
        label = toggle_label(page)
        check(
            "休息提醒：關" in label,
            f"F166 ④ rest-alarm importance=0（另兩個正常）→ 顯示「關」（實際：{label}）",
        )
        ctx.close()

        # F166 ④ 反面：三個 channel 全部正常時要顯示「開」
        ctx, page = open_app(browser, base, ALL_OK)
        label = toggle_label(page)
        check(
            "休息提醒：開" in label,
            f"F166 ④ 反面：三個 channel 都正常 → 顯示「開」（實際：{label}）",
        )
        ctx.close()

        # 邊界：rest-alarm 還沒建立（服務從未啟動過）不算被關
        ctx, page = open_app(browser, base, TIMER_ABSENT)
        check(
            "休息提醒：開" in toggle_label(page),
            "邊界：rest-alarm 尚未建立（服務沒跑過）不算被關——否則新裝置永遠開不了",
        )
        ctx.close()

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
