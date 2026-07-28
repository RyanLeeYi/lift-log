"""F64 E2E：浮動視窗倒數 overlay（②③⑥⑦ 的前端面 + ①④ 的原生靜態約束）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f64.py`

⚠ 界線（延續 F62／F63 的教訓：假物件只會複製實作者的誤解）——這支驗的是
「前端在對的時機呼叫了對的東西」與原生原始碼的靜態約束。真正的行為：
- ① overlay 浮在其他 app 之上、秒數會跳
- ⑤ 可拖曳、可點擊關閉
- ⑤-b Samsung 的 OEM 限制
只能在裝置上驗，acceptance 也是這樣寫的。
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, free_port, start_server  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


FAKE_PLUGIN = """
(overlayGranted) => {
  window.__f64 = { starts: [], stops: 0, overlayRequests: 0, localScheduled: [] };
  window.__f64.granted = overlayGranted;
  window.Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => 'android',
    Plugins: {
      LocalNotifications: {
        checkPermissions: async () => ({ display: 'granted' }),
        requestPermissions: async () => ({ display: 'granted' }),
        areEnabled: async () => ({ value: true }),
        checkExactNotificationSetting: async () => ({ exact_alarm: 'granted' }),
        schedule: async (opts) => { window.__f64.localScheduled.push(opts); },
        cancel: async () => {},
      },
      NotifyStatus: { openSettings: async () => {} },
      RestTimer: {
        available: async () => ({ available: true }),
        start: async (opts) => { window.__f64.starts.push(opts); },
        stop: async () => { window.__f64.stops += 1; },
        overlayPermitted: async () => ({ granted: window.__f64.granted }),
        requestOverlayPermission: async () => { window.__f64.overlayRequests += 1; },
      },
    },
  };
}
"""

JAVA_DIR = REPO / "android/app/src/main/java/com/ryanleeyi/liftlog"


def manifest_and_source_checks() -> None:
    """①④ 的前提都在原生層，這裡驗靜態約束。"""
    manifest = (REPO / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    check("android.permission.SYSTEM_ALERT_WINDOW" in manifest, "① 宣告 SYSTEM_ALERT_WINDOW")

    overlay_path = JAVA_DIR / "RestOverlay.java"
    check(overlay_path.exists(), "① RestOverlay.java 存在")
    overlay = overlay_path.read_text(encoding="utf-8") if overlay_path.exists() else ""
    check("TYPE_APPLICATION_OVERLAY" in overlay, "① 用 TYPE_APPLICATION_OVERLAY 浮在其他 app 之上")
    check("updateViewLayout" in overlay and "OnTouchListener" in overlay,
          "⑤ 可拖曳（OnTouchListener + updateViewLayout）")
    check("removeViewImmediate" in overlay or "removeView" in overlay, "④ 有移除 view 的路徑")
    # ④／F63 ③ 的教訓：倒數自然歸零後服務已 stopSelf，之後的 ACTION_STOP 會建立**新實例**。
    # view 的握把若放在實例欄位，新實例就關不掉舊 view → overlay 永久殘留。
    check(re.search(r"private\s+static\s+\w*\s*View\s+view", overlay) is not None,
          "④ view 握把是 static（新服務實例也關得掉，比照 F63 ③）")
    # Codex review P2（2026-07-28）：按 ✕ 之後改休息秒數會重下 ACTION_START，
    # 沒有這個旗標 overlay 就自己復活，吃掉使用者剛表達的意圖。
    check("dismissed" in overlay and "if (dismissed) return" in overlay,
          "③ 手動關掉後同一輪休息不會自己復活（改秒數重啟服務也一樣）")
    check("dismissed = false" in overlay,
          "③ 下一輪休息會重新顯示（服務停止／歸零時清掉 dismissed）")

    svc = (JAVA_DIR / "RestTimerService.java").read_text(encoding="utf-8")
    check("EXTRA_OVERLAY" in svc, "② overlay 是否顯示由呼叫端決定（EXTRA_OVERLAY）")
    check("RestOverlay.update" in svc,
          "① 秒數由原生 CountDownTimer 推送（onTick → RestOverlay.update），不由 WebView 驅動")
    marker = "ACTION_STOP.equals(action)"
    stop_branch = svc.split(marker)[1].split("}")[0] if marker in svc else ""
    check("RestOverlay.hide" in stop_branch, "④ ACTION_STOP 移除 overlay")
    destroy = svc.split("public void onDestroy()")[1].split("}")[0] if "onDestroy" in svc else ""
    check("RestOverlay.hide" in destroy, "④ onDestroy 也移除 overlay（兩條路徑都要，比照 F63 ③）")

    plugin = (JAVA_DIR / "RestTimerPlugin.java").read_text(encoding="utf-8")
    check("overlayPermitted" in plugin, "② 前端查得到 overlay 授權狀態")
    check("ACTION_MANAGE_OVERLAY_PERMISSION" in plugin, "② 未授權時導到系統設定頁")

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    check("SYSTEM_ALERT_WINDOW" in readme or "浮動" in readme, "⑥ README 記載 overlay 的已知限制")


def native(page, base: str, overlay_granted: bool):
    page.add_init_script(
        FAKE_PLUGIN.strip().join(["(", f")({str(overlay_granted).lower()})"]))
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    return page


def prime(page) -> None:
    """休息提醒先開起來——overlay 是它的附加顯示，不是獨立開關。"""
    page.evaluate(
        "async () => {"
        "  const rn = await import('/js/rest-notify.js');"
        "  localStorage.setItem('liftlog.nativeNotifyEnabled', '1');"
        "  await rn.refreshRestNotifyState();"
        "}"
    )


def toggle_overlay(page) -> dict:
    return page.evaluate(
        "async () => {"
        "  const rn = await import('/js/rest-notify.js');"
        "  const res = await rn.enableRestOverlay();"
        "  return { res, enabled: rn.restOverlayEnabled(), probe: window.__f64 };"
        "}"
    )


def start_rest(page) -> dict:
    return page.evaluate(
        "async () => {"
        "  const rn = await import('/js/rest-notify.js');"
        "  rn.scheduleRestNotify(90);"
        "  await new Promise(r => setTimeout(r, 400));"
        "  return window.__f64;"
        "}"
    )


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f64_e2e_{port}.db"
    release = REPO / f"liftlog_f64_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        manifest_and_source_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # A. 已授權 → 開得起來，休息開始時帶 overlay:true
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, overlay_granted=True)
            prime(page)
            t = toggle_overlay(page)
            check(t["res"].get("ok") is True, f"② 已授權時開啟成功（{t['res']}）")
            check(t["enabled"] is True, "② 開關狀態為開")
            r = start_rest(page)
            check(len(r["starts"]) == 1 and r["starts"][0].get("overlay") is True,
                  f"① 休息開始時要求顯示 overlay（{r['starts']}）")
            ctx.close()

            # B. 未授權 → 導到系統設定頁，開關不留假的「開」，且倒數照樣走 F63
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, overlay_granted=False)
            prime(page)
            t = toggle_overlay(page)
            check(t["res"].get("ok") is False, "② 未授權時不謊報成功")
            check(t["probe"]["overlayRequests"] == 1, "② 未授權時導到系統設定頁")
            check(t["enabled"] is False, "② 未授權時開關維持關（不顯示假的「開」）")
            r = start_rest(page)
            check(len(r["starts"]) == 1 and r["starts"][0].get("overlay") is False,
                  "② 拒絕授權時退回 F63 的通知列倒數（前景服務照常啟動，只是不畫 overlay）")
            check(r["starts"][0].get("seconds") == 90, "② 退回時秒數不受影響")
            check(len(r["localScheduled"]) == 0, "⑦ 不影響 F63 ⑥ 的分工（沒有多排一則本機通知）")
            ctx.close()

            # C. overlay 關著（預設）→ F63 行為與 F64 之前完全一致
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, overlay_granted=True)
            prime(page)
            enabled = page.evaluate(
                "async () => (await import('/js/rest-notify.js')).restOverlayEnabled()")
            check(enabled is False, "⑦ overlay 預設關閉（不主動要求高風險權限）")
            r = start_rest(page)
            check(r["starts"][0].get("overlay") is False, "⑦ 關著時不畫 overlay")
            ctx.close()

            # D. web 版完全不受影響
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            check(page.evaluate("() => typeof window.Capacitor") == "undefined",
                  "⑦ web 版沒有 Capacitor bridge")
            check(page.evaluate(
                "async () => (await import('/js/rest-notify.js')).restOverlaySupported()") is False,
                "⑦ web 版不顯示浮動計時開關")
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
