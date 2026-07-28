"""F69 E2E：浮動計時只在看不到 app 內倒數時顯示（②③④⑥⑦ 的可驗面）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f69.py`

⚠ 界線（F62／F63／F68 的同一課：假物件只會複製實作者的誤解）——這支驗
「前端在畫面切換時送出正確的 REST 卡片可見性」與原生的顯示規則、生命週期來源。
真正的顯示／隱藏轉換（切出 app、回到 app、鎖螢幕）只能在裝置上驗，acceptance ⑧ 也是這樣寫的。
"""

from __future__ import annotations

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
() => {
  window.__f69 = { cardVisible: [], starts: [] };
  window.Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => 'android',
    Plugins: {
      LocalNotifications: {
        checkPermissions: async () => ({ display: 'granted' }),
        requestPermissions: async () => ({ display: 'granted' }),
        areEnabled: async () => ({ value: true }),
        checkExactNotificationSetting: async () => ({ exact_alarm: 'granted' }),
        schedule: async () => {},
        cancel: async () => {},
      },
      NotifyStatus: { openSettings: async () => {} },
      RestTimer: {
        available: async () => ({ available: true }),
        start: async (o) => { window.__f69.starts.push(o); },
        stop: async () => {},
        overlayPermitted: async () => ({ granted: true }),
        requestOverlayPermission: async () => {},
        setRestCardVisible: async (o) => { window.__f69.cardVisible.push(o.visible); },
      },
    },
  };
}
"""

JAVA_DIR = REPO / "android/app/src/main/java/com/ryanleeyi/liftlog"


def source_checks() -> None:
    overlay = (JAVA_DIR / "RestOverlay.java").read_text(encoding="utf-8")
    tracker_path = JAVA_DIR / "AppForegroundTracker.java"
    check(tracker_path.exists(), "② AppForegroundTracker.java 存在")
    tracker = tracker_path.read_text(encoding="utf-8") if tracker_path.exists() else ""
    check("ActivityLifecycleCallbacks" in tracker,
          "② app 前景與否來自 ActivityLifecycleCallbacks（不是 WebView 的 visibilitychange）")
    check("onActivityResumed" in tracker and "onActivityPaused" in tracker,
          "② resumed／paused 兩個轉換都接")

    main_activity = (JAVA_DIR / "MainActivity.java").read_text(encoding="utf-8")
    # 註冊分兩半：MainActivity 呼叫 register()，實際的 registerActivityLifecycleCallbacks
    # 在 tracker 內。兩半都要在，只驗一半會漏掉「宣告了但沒接上」。
    check("AppForegroundTracker.register" in main_activity,
          "② MainActivity 有呼叫 tracker 的註冊")
    check("registerActivityLifecycleCallbacks" in tracker,
          "② tracker 真的掛上 Application 的生命週期回呼（沒掛等於沒有這個機制）")

    check("setAppForeground" in overlay and "setRestCardVisible" in overlay,
          "①③ 兩個輸入都進到 overlay 的顯示判斷")
    # ①④⑥ 的規則本體：只有「前景且看得到卡片」才藏；dismissed 優先於自動顯示。
    check("shouldShow" in overlay, "① 顯示規則收斂成單一判斷（不散在各處）")
    check("dismissed" in overlay, "④ 手動關閉的旗標仍在")
    # 只看程式碼，不看註解——註解裡**刻意**寫著「為什麼不用 visibilitychange」，
    # 那是這個設計最重要的一句話，不該因為關鍵字比對而被迫刪掉。
    def code_only(src: str) -> str:
        return "\n".join(
            ln for ln in src.splitlines()
            if not ln.lstrip().startswith(("//", "*", "/*", "/**"))
        )

    check("visibilitychange" not in code_only(overlay) + code_only(tracker),
          "② 原生層不依賴 WebView 的 visibilitychange")

    plugin = (JAVA_DIR / "RestTimerPlugin.java").read_text(encoding="utf-8")
    check("setRestCardVisible" in plugin, "③ 前端有橋可以回報 REST 卡片可見性")
    # 2026-07-28 模擬器實測抓到的 crash：plugin 呼叫跑在 CapacitorPlugins 執行緒，
    # 從那裡建立的 view 之後被 main thread 的 onTick 更新 → CalledFromWrongThreadException。
    # view 操作一律要回 main thread，這是這個 feature 最容易再犯的錯。
    check("Looper.getMainLooper()" in overlay,
          "③ overlay 的所有進入點都繞回 main thread（plugin 執行緒不能碰 view）")

    svc = (JAVA_DIR / "RestTimerService.java").read_text(encoding="utf-8")
    for marker, label in (
        ("ACTION_STOP.equals(action)", "⑤ ACTION_STOP"),
        ("public void onDestroy()", "⑤ onDestroy"),
    ):
        branch = svc.split(marker)[1].split("}")[0] if marker in svc else ""
        check("RestOverlay.hide" in branch or "RestOverlay.setActive" in branch,
              f"{label} 仍會收掉 overlay（F64 ④ 未被 F69 破壞）")


def native(page, base: str):
    page.add_init_script(FAKE_PLUGIN.strip().join(["(", ")()"]))
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    return page


def drive(page, script: str):
    return page.evaluate(script)


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f69_e2e_{port}.db"
    release = REPO / f"liftlog_f69_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        source_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()

            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base)
            r = drive(page, """
              async () => {
                const rn = await import('/js/rest-notify.js');
                localStorage.setItem('liftlog.nativeNotifyEnabled', '1');
                localStorage.setItem('liftlog.restOverlayEnabled', '1');
                await rn.refreshRestNotifyState();
                const out = {};
                // 開機第一次 render() 就會送一次 false（首頁、沒在休息）——那是正確行為，
                // 從基準點之後才是這次要驗的轉換。
                out.boot = window.__f69.cardVisible.slice();
                const base = window.__f69.cardVisible.length;
                const since = () => window.__f69.cardVisible.slice(base);
                // 休息中、停在 logger → 看得到 REST 卡片
                rn.syncRestCardVisible(true);
                await new Promise(r => setTimeout(r, 150));
                out.onLogger = since();
                // 切到別的畫面（課表等）→ 看不到卡片
                rn.syncRestCardVisible(false);
                await new Promise(r => setTimeout(r, 150));
                out.offLogger = since();
                // 回到 logger
                rn.syncRestCardVisible(true);
                await new Promise(r => setTimeout(r, 150));
                out.backOnLogger = since();
                // 同一個值重複送不該一直打橋（render 每秒都會跑）
                rn.syncRestCardVisible(true);
                rn.syncRestCardVisible(true);
                await new Promise(r => setTimeout(r, 150));
                out.afterRepeat = since();
                return out;
              }
            """)
            check(r["boot"] == [False],
                  f"⑥ 開機時就先同步一次（沒在休息＝不可見），不留未定狀態（{r['boot']}）")
            check(r["onLogger"] == [True], f"③ 停在 logger＝卡片可見（{r['onLogger']}）")
            check(r["offLogger"] == [True, False],
                  f"① 切到別的畫面＝卡片不可見（{r['offLogger']}）")
            check(r["backOnLogger"] == [True, False, True], "① 回到 logger 又變可見")
            check(r["afterRepeat"] == r["backOnLogger"],
                  f"③ 同值不重複打橋（render 每秒跑一次，不能每次都送）（{r['afterRepeat']}）")
            ctx.close()

            # ⑥ 的前端面：休息中在 logger 上，畫面本身要真的有 REST 卡片可看
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base)
            r = drive(page, """
              async () => {
                const rn = await import('/js/rest-notify.js');
                return { supported: rn.restOverlaySupported(),
                         hasSync: typeof rn.syncRestCardVisible === 'function' };
              }
            """)
            check(r["hasSync"] is True, "③ 統一入口 rest-notify 有 syncRestCardVisible")
            ctx.close()

            # ⑦ web 版：沒有 Capacitor，同步呼叫必須是 no-op（不得拋錯）
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            r = drive(page, """
              async () => {
                const rn = await import('/js/rest-notify.js');
                let threw = false;
                try { rn.syncRestCardVisible(false); rn.syncRestCardVisible(true); }
                catch { threw = true; }
                return { threw, cap: typeof window.Capacitor };
              }
            """)
            check(r["cap"] == "undefined", "⑦ web 版沒有 Capacitor bridge")
            check(r["threw"] is False, "⑦ web 版呼叫同步函式是 no-op（不拋錯）")
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
