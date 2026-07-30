"""F71 E2E：休息倒數的暫停與停止（①②③④⑤⑥⑧⑩ 的可驗面）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f71.py`

走真實 UI 流程，並回頭打 API 查**寫進資料庫**的 rest_seconds——③ 改的是會進訓練資料的欄位，
不能只驗畫面。⑦（WebView 被回收時從浮動視窗操作）與原生兩邊的即時同步只能在裝置上驗（⑨）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    REPO,
    TOKEN,
    e2e_tmp,
    free_port,
    setup_and_home,
    start_from_home,  # noqa: E402
    start_server,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def api(base: str, path: str):
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {TOKEN}"})
    return json.load(urllib.request.urlopen(req))


FAKE_PLUGIN = """
() => {
  window.__f71 = { calls: [], listeners: {} };
  window.Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => 'android',
    Plugins: {
      LocalNotifications: {
        checkPermissions: async () => ({ display: 'granted' }),
        requestPermissions: async () => ({ display: 'granted' }),
        areEnabled: async () => ({ value: true }),
        checkExactNotificationSetting: async () => ({ exact_alarm: 'granted' }),
        schedule: async () => {}, cancel: async () => {},
      },
      NotifyStatus: { openSettings: async () => {} },
      RestTimer: {
        available: async () => ({ available: true }),
        start: async (o) => { window.__f71.calls.push(['start', o]); },
        stop: async () => { window.__f71.calls.push(['stop']); },
        pause: async () => { window.__f71.calls.push(['pause']); },
        resume: async () => { window.__f71.calls.push(['resume']); },
        overlayPermitted: async () => ({ granted: true }),
        requestOverlayPermission: async () => {},
        setRestCardVisible: async (o) => { window.__f71.calls.push(['card', o.visible]); },
        addListener: (name, cb) => {
          window.__f71.listeners[name] = cb;
          return { remove: () => {} };
        },
      },
    },
  };
}
"""

JAVA_DIR = REPO / "android/app/src/main/java/com/ryanleeyi/liftlog"


def source_checks() -> None:
    plugin = (JAVA_DIR / "RestTimerPlugin.java").read_text(encoding="utf-8")
    check("notifyListeners" in plugin, "⑥ 原生→前端走事件（notifyListeners）")
    for m in ("pause", "resume"):
        check(f"public void {m}(PluginCall" in plugin, f"① 前端→原生有 {m} 橋")

    svc = (JAVA_DIR / "RestTimerService.java").read_text(encoding="utf-8")
    check("ACTION_PAUSE" in svc and "ACTION_RESUME" in svc, "② 服務支援暫停／繼續")

    overlay = (JAVA_DIR / "RestOverlay.java").read_text(encoding="utf-8")
    check("paused" in overlay, "① 浮動視窗知道暫停狀態（兩邊顯示要一致）")
    # ⑩：收起狀態只到「回頭看到 app 內的倒數」為止
    check("restCardVisible" in overlay and "dismissed = false" in overlay,
          "⑩ 卡片可見時解除收起狀態（之後再離開就會再出現）")

    rest_notify = (REPO / "app/static/js/rest-notify.js").read_text(encoding="utf-8")
    check("pauseRestNotify" in rest_notify and "resumeRestNotify" in rest_notify,
          "① 統一入口有暫停／繼續（web 版走 no-op，不長第二套 if）")


PUBLIC_HOST = "https://lift-log.my-super-dev-server.work"


def native(page, base: str):
    """app 版：假 plugin ＋ 把打向公開站的 API 導回本機（同 verify_f67 的做法，別碰正式站）。"""
    page.add_init_script(FAKE_PLUGIN.strip().join(["(", ")()"]))

    def reroute(route):
        req = route.request
        allow = {"access-control-allow-origin": base, "access-control-allow-headers": "*"}
        if req.method == "OPTIONS":
            route.fulfill(status=200, headers={**allow, "access-control-allow-methods": "*"})
            return
        resp = page.context.request.fetch(
            req.url.replace(PUBLIC_HOST, base),
            method=req.method,
            headers=req.headers,
            data=req.post_data,
        )
        route.fulfill(response=resp, headers={**resp.headers, **allow})

    page.route(f"{PUBLIC_HOST}/**", reroute)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    return page


def rest_state(page) -> dict:
    return page.evaluate(
        "async () => {"
        "  const s = await import('/js/state.js');"
        "  return { elapsed: s.restElapsedSeconds(), remaining: s.restRemainingSeconds(),"
        "           paused: s.restPaused(), started: s.state.restStartedAt !== null };"
        "}"
    )


def start_free_workout(page) -> None:
    start_from_home(page)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(600)
    page.locator("button").filter(has_text="深蹲").first.click()
    page.wait_for_timeout(600)


def main() -> int:
    port = free_port()
    db = e2e_tmp() / f"liftlog_f71_e2e_{port}.db"
    release = e2e_tmp() / f"liftlog_f71_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        source_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # ---- app 版：暫停不計時、停止結束休息、事件雙向 ----
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base)
            setup_and_home(page)
            start_free_workout(page)
            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(900)

            check(page.locator(".rest-controls").get_by_role("button", name="暫停").count() == 1,
                  "① 計時頁有暫停鈕")
            check(page.locator(".rest-controls").get_by_role("button", name="停止").count() == 1,
                  "① 計時頁有停止鈕")

            page.wait_for_timeout(2200)
            before = rest_state(page)["elapsed"]
            page.locator(".rest-controls").get_by_role("button", name="暫停").click()
            page.wait_for_timeout(300)
            r = rest_state(page)
            check(r["paused"] is True, "② 暫停狀態成立")
            check(any(c[0] == "pause" for c in page.evaluate("() => window.__f71.calls")),
                  "① 暫停有同步到原生（通知列與浮動視窗才會一致）")
            check(page.locator(".rest-controls").get_by_role("button", name="繼續").count() == 1,
                  "② 暫停後按鈕變成「繼續」")

            page.wait_for_timeout(2500)  # 暫停期間：這 2.5 秒不該被計入
            r2 = rest_state(page)
            check(r2["elapsed"] == before or abs(r2["elapsed"] - before) <= 1,
                  f"③ 暫停期間計時凍結（暫停前 {before}s → 等 2.5s 後 {r2['elapsed']}s）")
            check(r2["remaining"] == rest_state(page)["remaining"], "② 剩餘秒數同樣凍結")

            page.locator(".rest-controls").get_by_role("button", name="繼續").click()
            page.wait_for_timeout(1500)
            r3 = rest_state(page)
            check(r3["paused"] is False, "② 繼續後回到計時中")
            check(r3["elapsed"] >= before + 1, f"② 從剩餘秒數接續（{r3['elapsed']}s）")
            check(r3["elapsed"] < before + 4,
                  f"③ 接續後仍不含暫停的 2.5 秒（{r3['elapsed']}s，含暫停會 >4s）")

            elapsed_at_stop = rest_state(page)["elapsed"]
            page.locator(".rest-controls").get_by_role("button", name="停止").click()
            page.wait_for_timeout(500)
            r4 = rest_state(page)
            check(r4["started"] is False, "④ 停止＝結束這段休息")
            check(page.get_by_role("button", name="完成這組").count() == 1,
                  "④ 按鈕回到「完成這組」")
            check(any(c[0] == "stop" for c in page.evaluate("() => window.__f71.calls")),
                  "④ 停止有同步到原生（通知與浮動視窗一起收掉）")

            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(1200)
            sets = []
            for w in api(base, "/api/workouts"):
                sets = api(base, f"/api/workouts/{w['id']}")["sets"]
                if sets:
                    break
            second = [s for s in sets if s["set_number"] == 2]
            got = second[0]["rest_seconds"] if second else None
            check(got is not None, f"④ 停止後記的那組有寫入 rest_seconds（{got}）")
            check(got is not None and abs(got - elapsed_at_stop) <= 2,
                  f"③ rest_seconds 不含暫停期間（記錄 {got}s vs 計時中累計 {elapsed_at_stop}s）")

            # ⑥ 原生→前端：浮動視窗按暫停時，前端要跟著變（走事件，不是輪詢）
            page.locator(".rest-controls").get_by_role("button", name="停止").click()
            page.wait_for_timeout(300)
            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(900)
            page.evaluate("() => window.__f71.listeners['restControl']({ action: 'pause' })")
            page.wait_for_timeout(400)
            check(rest_state(page)["paused"] is True,
                  "⑥ 原生端（浮動視窗）按暫停 → 前端跟著暫停")
            page.evaluate("() => window.__f71.listeners['restControl']({ action: 'stop' })")
            page.wait_for_timeout(400)
            check(rest_state(page)["started"] is False,
                  "⑥ 原生端按停止 → 前端休息也結束")
            ctx.close()

            # ---- ⑧ web 版：一樣有暫停／停止，只是沒有原生那半 ----
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            start_free_workout(page)
            page.get_by_role("button", name="完成這組").click()
            page.wait_for_timeout(900)
            check(
                page.locator(".rest-controls").get_by_role("button", name="暫停").count() == 1,
                "⑧ web 版也有暫停鈕",
            )
            page.locator(".rest-controls").get_by_role("button", name="暫停").click()
            page.wait_for_timeout(300)
            check(rest_state(page)["paused"] is True, "⑧ web 版暫停可用（純前端計時）")
            page.locator(".rest-controls").get_by_role("button", name="停止").click()
            page.wait_for_timeout(300)
            check(rest_state(page)["started"] is False, "⑧ web 版停止可用")
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
