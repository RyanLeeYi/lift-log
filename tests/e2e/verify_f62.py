"""F62 E2E：休息提醒的環境分流（①④⑤⑥⑦）＋ web 版回歸。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f62.py`

app 版以注入 `window.Capacitor.Plugins.LocalNotifications` 的**假 plugin** 驗證：
排程／取消是否打到本機通知、參數對不對、權限被拒時是否有引導。

⚠ 界線：假 plugin 證明的是「前端呼叫對了」，**不是**通知真的會在手機上響。
② 的鎖屏／飛航模式觸發、③ 的準時性，只能在真機驗（acceptance 也是這樣寫的）。
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
TOKEN = "e2e-f62-token"
PHONE = {"width": 390, "height": 844}

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server(port: int, db: Path) -> subprocess.Popen:
    import os

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app_factory", "--factory",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO,
        env={**dict(os.environ), "LIFTLOG_TOKEN": TOKEN, "LIFTLOG_DB": str(db)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("server did not come up")


# 假 plugin：把每次呼叫記進 window.__ln，讓測試斷言參數。
# display 由 window.__perm 控制，才能同時驗「已授權」與「被拒」兩條路。
FAKE_PLUGIN = """
(perm, exact) => {
  window.__ln = { schedule: [], cancel: [], requested: 0 };
  window.Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => 'android',
    Plugins: {
      LocalNotifications: {
        checkPermissions: async () => ({ display: perm }),
        requestPermissions: async () => { window.__ln.requested += 1; return { display: perm }; },
        checkExactNotificationSetting: async () => ({ exact_alarm: exact }),
        schedule: async (opts) => { window.__ln.schedule.push(opts); },
        cancel: async (opts) => { window.__ln.cancel.push(opts); },
      },
    },
  };
}
"""


def manifest_checks() -> None:
    """③⑤ 的前置：權限沒宣告，準時性與授權流程一定不成立。"""
    manifest = (REPO / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    check("android.permission.POST_NOTIFICATIONS" in manifest,
          "⑤ AndroidManifest 宣告 POST_NOTIFICATIONS（Android 13+ 授權用）")
    check("android.permission.SCHEDULE_EXACT_ALARM" in manifest,
          "③ AndroidManifest 宣告 SCHEDULE_EXACT_ALARM（否則系統會延後觸發）")


def source_checks() -> None:
    """⑥ 取消路徑：四個呼叫點都必須走統一入口，不得殘留直接呼叫 push.js。"""
    app_js = (REPO / "app/static/js/app.js").read_text(encoding="utf-8")
    check("scheduleRestPush" not in app_js and "cancelRestPush" not in app_js,
          "⑥ app.js 不再直接呼叫 push.js 的排程／取消")
    check(app_js.count("scheduleRestNotify(") == 2 and app_js.count("cancelRestNotify(") == 2,
          f"⑥ 四個呼叫點都走 rest-notify（schedule {app_js.count('scheduleRestNotify(')} 處／"
          f"cancel {app_js.count('cancelRestNotify(')} 處）")
    # ⑦ F31 的伺服器端排程器不得被刪
    push_api = (REPO / "app/api/push.py").read_text(encoding="utf-8")
    check("rest-timer" in push_api, "⑦ F31 伺服器端休息排程端點仍在（web 版繼續用）")

    sw = (REPO / "app/static/sw.js").read_text(encoding="utf-8")
    state = (REPO / "app/static/js/state.js").read_text(encoding="utf-8")
    cache = re.search(r'CACHE_NAME\s*=\s*"liftlog-shell-(v\d+)"', sw)
    app_v = re.search(r'APP_VERSION\s*=\s*"(v\d+)"', state)
    check(bool(cache and app_v) and cache.group(1) == app_v.group(1),
          f"版號兩處一致（{cache and cache.group(1)}）")
    check('"/js/rest-notify.js"' in sw and '"/js/native-notify.js"' in sw,
          "新增模組已列進 SW SHELL（否則 web 版離線首開缺檔）")


def verify_web(page, base: str) -> None:
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    same = page.evaluate(
        "async () => {"
        "  const rn = await import('/js/rest-notify.js');"
        "  const p = await import('/js/push.js');"
        "  return { rn: rn.restNotifySupported(), push: p.pushSupported(), delayed: rn.restNotifyDelayed() };"
        "}"
    )
    check(same["rn"] == same["push"],
          f"⑦ web 版 restNotifySupported 委派給 F31 pushSupported（皆為 {same['push']}）")
    check(same["delayed"] is False, "⑦ web 版不顯示「可能延遲」提示（那是 app 版專有）")
    check(page.evaluate("() => typeof window.Capacitor") == "undefined",
          "⑦ web 版沒有 Capacitor bridge（分流判定的前提成立）")


def verify_native(page, base: str, perm: str, exact: str) -> dict:
    page.add_init_script(FAKE_PLUGIN.strip().join(["(", f")({perm!r}, {exact!r})"]))
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    return page.evaluate(
        "async () => {"
        "  const rn = await import('/js/rest-notify.js');"
        "  localStorage.removeItem('liftlog.nativeNotifyEnabled');"
        "  await rn.refreshRestNotifyState();"
        "  const supported = rn.restNotifySupported();"
        "  const before = rn.restNotifyEnabled();"
        "  const res = await rn.enableRestNotify();"
        "  const after = rn.restNotifyEnabled();"
        "  const delayed = rn.restNotifyDelayed();"
        "  rn.scheduleRestNotify(60);"
        "  await new Promise(r => setTimeout(r, 150));"
        "  rn.cancelRestNotify();"
        "  await new Promise(r => setTimeout(r, 150));"
        "  return { supported, before, after, res, delayed, ln: window.__ln };"
        "}"
    )


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f62_e2e_{port}.db"
    proc = start_server(port, db)
    base = f"http://127.0.0.1:{port}"
    try:
        manifest_checks()
        source_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()

            ctx = browser.new_context(viewport=PHONE)
            verify_web(ctx.new_page(), base)
            ctx.close()

            # 情境 A：權限已授予、精確鬧鐘正常
            ctx = browser.new_context(viewport=PHONE)
            a = verify_native(ctx.new_page(), base, "granted", "granted")
            ctx.close()
            check(a["supported"] is True, "① app 版 restNotifySupported 為 true（走本機通知）")
            check(a["before"] is False and a["after"] is True,
                  "④ 開關可從關切到開（狀態反映在 restNotifyEnabled）")
            check(a["res"]["ok"] is True, "④ 已授權時 enableRestNotify 回 ok")
            check(a["ln"]["requested"] >= 1, "④ 有實際向系統要通知權限")
            sched = a["ln"]["schedule"]
            check(len(sched) == 1, f"① 排程打到本機通知一次（{len(sched)}）")
            notif = sched[0]["notifications"][0] if sched else {}
            check(notif.get("id") == 1001, f"① 用固定 id 1001（取得 {notif.get('id')}）")
            check(bool(notif.get("schedule", {}).get("at")),
                  "① 排程帶絕對時間 at（手機端排程，不依賴伺服器）")
            check(notif.get("schedule", {}).get("allowWhileIdle") is True,
                  "③ allowWhileIdle=true（Doze 中仍會響）")
            cancels = a["ln"]["cancel"]
            check(any(c["notifications"][0]["id"] == 1001 for c in cancels),
                  f"⑥ 取消打到本機通知且 id 對得上（{len(cancels)} 次）")
            check(a["delayed"] is False, "③ 精確鬧鐘正常時不顯示「可能延遲」")

            # 情境 B：使用者在系統設定關掉通知（Android 12 的「未授權」樣態）
            ctx = browser.new_context(viewport=PHONE)
            b = verify_native(ctx.new_page(), base, "denied", "granted")
            ctx.close()
            check(b["res"]["ok"] is False, "⑤ 通知被關閉時 enableRestNotify 回 ok=false")
            check("設定" in (b["res"].get("reason") or ""),
                  f"⑤ 有明確引導文案，不靜默失敗：{b['res'].get('reason')!r}")
            check(b["after"] is False, "⑤ 被拒後開關不會顯示成「開」")
            check(len(b["ln"]["schedule"]) == 0,
                  "⑤ 未啟用時不排程（no-op，與 F31 一致）")

            # 情境 C：通知允許但精確鬧鐘被關 → 要提示會延遲
            ctx = browser.new_context(viewport=PHONE)
            c = verify_native(ctx.new_page(), base, "granted", "denied")
            ctx.close()
            check(c["delayed"] is True, "③ 精確鬧鐘被關時 restNotifyDelayed 為 true（UI 會標示）")

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

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
