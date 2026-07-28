"""F63 E2E：休息倒數的前景服務（①③⑤⑥⑦ 的前端與設定面）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f63.py`

⚠ 界線（F62 的教訓：假物件會複製實作者的誤解）——這支只驗**前端在對的時機呼叫了對的東西**
與 manifest／原生原始碼的靜態約束。真正的行為：
- ① 通知列每秒更新的秒數
- ② 不開 app 也看得到、歸零後轉「休息結束」
- ④ 省電模式與螢幕關閉下的準時性
全部只能在裝置上驗，acceptance 也是這樣寫的。
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, free_port, start_server  # noqa: E402

TOKEN = "e2e-f63-token"
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


FAKE_PLUGIN = """
(fgAvailable) => {
  window.__f63 = { starts: [], stops: 0, localScheduled: [], localCancels: 0 };
  window.Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => 'android',
    Plugins: {
      LocalNotifications: {
        checkPermissions: async () => ({ display: 'granted' }),
        requestPermissions: async () => ({ display: 'granted' }),
        areEnabled: async () => ({ value: true }),
        checkExactNotificationSetting: async () => ({ exact_alarm: 'granted' }),
        schedule: async (opts) => { window.__f63.localScheduled.push(opts); },
        cancel: async () => { window.__f63.localCancels += 1; },
      },
      NotifyStatus: { openSettings: async () => {} },
      RestTimer: {
        available: async () => ({ available: fgAvailable }),
        start: async (opts) => { window.__f63.starts.push(opts); },
        stop: async () => { window.__f63.stops += 1; },
      },
    },
  };
}
"""


def manifest_and_source_checks() -> None:
    """⑤：權限與服務宣告；③④ 的前提在原生層。"""
    manifest = (REPO / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    check("android.permission.FOREGROUND_SERVICE" in manifest, "⑤ 宣告 FOREGROUND_SERVICE")
    check("android.permission.FOREGROUND_SERVICE_SPECIAL_USE" in manifest,
          "⑤ 宣告 Android 14+ 的 FOREGROUND_SERVICE_SPECIAL_USE")
    check('android:foregroundServiceType="specialUse"' in manifest,
          "⑤ service 標註 foregroundServiceType=specialUse（非 shortService 的 3 分鐘上限）")
    check("PROPERTY_SPECIAL_USE_FGS_SUBTYPE" in manifest, "⑤ 附上 specialUse 的用途說明")
    check(re.search(r'android:name="\.RestTimerService"', manifest) is not None,
          "⑤ RestTimerService 已在 manifest 宣告")

    java_dir = REPO / "android/app/src/main/java/com/ryanleeyi/liftlog"
    svc = (java_dir / "RestTimerService.java").read_text(encoding="utf-8")
    check("CountDownTimer" in svc,
          "① 倒數在原生層跑（CountDownTimer）——JS 計時器切背景會被節流")
    check("FOREGROUND_SERVICE_TYPE_SPECIAL_USE" in svc,
          "⑤ startForeground 的型別與 manifest 一致（不一致 Android 14+ 直接拋錯）")
    check("STOP_FOREGROUND_REMOVE" in svc, "③ 停止時移除通知（不留殘影）")
    check("STOP_FOREGROUND_DETACH" in svc,
          "② 歸零時保留同一則通知改成「休息結束」（detach 而非 remove）")
    check("setOnlyAlertOnce" in svc, "① 倒數期間不每秒叮一聲（只有結束才提醒）")

    main_activity = (java_dir / "MainActivity.java").read_text(encoding="utf-8")
    check("RestTimerPlugin.class" in main_activity, "① RestTimerPlugin 已註冊")


def native(page, base: str, fg_available: bool):
    page.add_init_script(
        FAKE_PLUGIN.strip().join(["(", f")({str(fg_available).lower()})"]))
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    return page


def drive_rest(page) -> dict:
    """走完「開啟提醒 → 排休息 → 取消」，回報兩條路徑各被呼叫幾次。"""
    return page.evaluate(
        "async () => {"
        "  const rn = await import('/js/rest-notify.js');"
        "  localStorage.setItem('liftlog.nativeNotifyEnabled', '1');"
        "  await rn.refreshRestNotifyState();"
        "  rn.scheduleRestNotify(90);"
        "  await new Promise(r => setTimeout(r, 400));"
        "  const afterSchedule = JSON.parse(JSON.stringify(window.__f63));"
        "  rn.cancelRestNotify();"
        "  await new Promise(r => setTimeout(r, 400));"
        "  return { afterSchedule, afterCancel: window.__f63 };"
        "}"
    )


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f63_e2e_{port}.db"
    release = REPO / f"liftlog_f63_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        manifest_and_source_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # ⑥ 前景服務可用 → 由它接手，**不排** F62 的本機通知
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, fg_available=True)
            r = drive_rest(page)
            starts = r["afterSchedule"]["starts"]
            check(len(starts) == 1, f"① 前景服務被啟動一次（{len(starts)}）")
            check(starts and starts[0].get("seconds") == 90,
                  f"① 帶入休息秒數（{starts[0].get('seconds') if starts else None}）")
            check(len(r["afterSchedule"]["localScheduled"]) == 0,
                  "⑥ 前景服務接手時**不排** F62 的本機通知（一次休息只有一則通知行為）")
            check(r["afterCancel"]["stops"] >= 1, "③ 取消時停止前景服務（通知列不留殘影）")
            ctx.close()

            # ⑥ 前景服務不可用 → 退回 F62，行為與 F63 之前一致
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, fg_available=False)
            r = drive_rest(page)
            check(len(r["afterSchedule"]["starts"]) == 0, "⑥ 不可用時不啟動前景服務")
            check(len(r["afterSchedule"]["localScheduled"]) == 1,
                  "⑥ 退回 F62 的本機通知（F62 的路徑保留，不是刪掉）")
            check(r["afterCancel"]["localCancels"] >= 1, "③ 取消時也會收掉本機通知")
            ctx.close()

            # ⑦ web 版完全不受影響：沒有 Capacitor，走 F31 Web Push
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            check(page.evaluate("() => typeof window.Capacitor") == "undefined",
                  "⑦ web 版沒有 Capacitor bridge（不會走到前景服務）")
            ctx.close()

            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for _ in range(20):
            try:
                db.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.25)
        for f in release.iterdir():
            f.unlink()
        release.rmdir()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
