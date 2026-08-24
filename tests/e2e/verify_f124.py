"""F124 E2E：原生→前端控制事件的訂閱時機（④）。

跑法：`uv run python tests/e2e/verify_f124.py`

驗的是**順序**，不是事件內容：原生那半在 Activity 重建期間送出的事件由 Capacitor 的
`retainUntilConsumed` 存著（①，Java 側），會在 `addListener` 那一刻整批補送。所以
「什麼時候訂閱」直接決定那些事件落在 F66 快照還原之前還是之後——還原之前收到 `stop`
會撞上 `state.restStartedAt === null` 直接 return，隨後還原又生出一輪殭屍倒數，
`focus` 則因為讀不到 `state.restExerciseId` 而 early-return（「停了但沒跳頁」）。

做法：假 `LocalStore.snapshot`（開機還原路徑的核心）故意慢 800ms，並把每一次呼叫與
`RestTimer.addListener` 記進同一份有序 log。訂閱若還留在 module eval 當下，它會排在
snapshot 完成之前——這正是修好之前的行為，也是這支腳本的紅測試（見檔尾說明）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fake_capacitor import build_fake_capacitor  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    TOKEN,
    reroute_public_host,
    safe_port,
    start_server,
    wait_home,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def fake_plugins() -> str:
    token = TOKEN
    auth_session = f"""
      loadSession: async () => ({{
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
      snapshot: async () => {
        mark('snapshot:start');
        // 開機還原是非同步的。這 800ms 就是「還原還沒做完」那段窗口——
        // module eval 當下註冊的訂閱會落在這裡面。
        await new Promise((r) => setTimeout(r, 800));
        mark('snapshot:done');
        return __snapshot;
      },
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
    local_notifications = """
      schedule: async () => ({}),
      cancel: async () => ({}),
      checkPermissions: async () => ({ display: 'granted' }),
      requestPermissions: async () => ({ display: 'granted' }),
      areEnabled: async () => ({ value: true }),
      listChannels: async () => ({ channels: [
        { id: 'default', importance: 3 },
        { id: 'rest-timer', importance: 2 },
        { id: 'rest-alarm', importance: 4 },
      ] }),
    """
    rest_timer = """
      start: async () => ({ started: true }),
      stop: async () => ({}),
      pause: async () => ({}),
      resume: async () => ({}),
      overlayPermitted: async () => ({ granted: false }),
      setCardVisible: async () => ({}),
      getRestStoppedAt: async () => ({ stoppedAt: 0 }),
      // Capacitor 真正的行為：addListener 當下才把 retained 的事件送出來。
      addListener: async () => {
        mark('addListener');
        return { remove: () => {} };
      },
    """
    return build_fake_capacitor(
        preamble="""
window.__log = [];
const mark = (name) => { window.__log.push(name); };
const __snapshot = {
  exercises: [], templates: [], workouts: [], sets: [],
  body_metrics: [], daily_status: [], settings: [],
};
""",
        auth_session=auth_session,
        local_store=local_store,
        sync=sync,
        local_notifications=local_notifications,
        rest_timer=rest_timer,
        notify_status="openSettings: async () => {},",
    )


def run_checks(base: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.add_init_script(fake_plugins())
        reroute_public_host(page, base)
        page.route(
            "**/api/mcp-tokens/**",
            lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
        )
        page.goto(base, wait_until="domcontentloaded")
        wait_home(page, timeout=15_000)
        page.wait_for_timeout(1500)  # 讓 800ms 的 snapshot 與其後的訂閱都跑完
        log = page.evaluate("() => window.__log")
        print(f"    log = {log}")

        # 前提：開機還原真的跑了。少了這條，下面兩條都會因為「什麼都沒發生」而假綠。
        check("snapshot:done" in log, f"前提：開機還原路徑有跑到（log={log}）")

        # ④ 正面：訂閱仍然會發生——延後註冊不等於不註冊
        check("addListener" in log, "④ restControl 有訂閱到（延後註冊沒有變成不註冊）")

        # ④ 主張：訂閱排在還原完成之後
        ok = (
            "addListener" in log
            and "snapshot:done" in log
            and log.index("addListener") > log.index("snapshot:done")
        )
        check(ok, "④ 訂閱發生在開機還原完成之後（不是 module eval 當下）")

        ctx.close()
        browser.close()


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f124-"))
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


# 紅測試怎麼證：把 app.js 的
#   startupRestore.then(() => subscribeRestControl(handleRestControl));
# 改回 module eval 當下的
#   subscribeRestControl(handleRestControl);
# 第三條必定紅（addListener 會排在 snapshot:done 之前）。

if __name__ == "__main__":
    raise SystemExit(main())
