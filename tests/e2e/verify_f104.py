"""F104/F140 E2E：浮動視窗收到本機 handle，並直接寫入 LocalStore。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f104.py`

視窗的長相與 SQLite 寫入在原生 Java，Playwright 碰不到；共庫與重開持久化由
F140LocalStoreInstrumentedTest 驗。這支只驗 WebView/overlay 邊界：

  ① 開始休息時把「待記組」（重量／次數／是否自體重）送給原生
  ③ 草稿帶 LocalStore workout/exercise rowid
  ④ 正式碼只有 RestOverlay → LocalStore 寫入，不再有 logset bridge
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


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    reroute_public_host,
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
    wait_home,
)

NOTIFY_FLAG = "liftlog.nativeNotifyEnabled"
OVERLAY_FLAG = "liftlog.restOverlayEnabled"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


FAKE = """
window.__native = { starts: [], handler: null };
const local = {
  exercises: [{ id: 1, name_zh: '深蹲', name_en: 'Squat', muscle_group: '腿', is_bodyweight: 0 }],
  templates: [], workouts: [], sets: [], body_metrics: [], daily_status: [], settings: [],
};
let nextWorkout = 1;
let nextSet = 1;
window.Capacitor = {
  isNativePlatform: () => true,
  getPlatform: () => 'android',
  Plugins: {
    LocalStore: {
      initialize: async () => ({ schemaVersion: 2, seededExercises: 1, pendingMutations: 0 }),
      snapshot: async () => structuredClone(local),
      createWorkout: async (o) => {
        const row = { id: nextWorkout++, date: o.date, template_id: o.templateId ?? null,
          note: o.note ?? null, created_at: new Date().toISOString(), ended_at: null };
        local.workouts.push(row);
        return structuredClone(row);
      },
      addSet: async (o) => {
        const row = { id: nextSet, client_uuid: o.clientUuid, workout_id: o.workoutId,
          exercise_id: o.exerciseId, set_number: o.setNumber ?? nextSet++,
          weight_kg: o.weightKg, reps: o.reps, rpe: o.rpe ?? null,
          rest_seconds: o.restSeconds ?? null };
        local.sets.push(row);
        return structuredClone(row);
      },
      status: async () => ({ schemaVersion: 2, pendingMutations: 0 }),
    },
    LocalNotifications: {
      schedule: async () => ({}), cancel: async () => ({}),
      checkPermissions: async () => ({ display: 'granted' }),
      requestPermissions: async () => ({ display: 'granted' }),
      areEnabled: async () => ({ value: true }),
      listChannels: async () => ({ channels: [
        { id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 },
      ] }),
    },
    RestTimer: {
      available: async () => ({ available: true }),
      start: async (o) => { window.__native.starts.push(o); return {}; },
      stop: async () => ({}), pause: async () => ({}), resume: async () => ({}),
      overlayPermitted: async () => ({ granted: true }),
      requestOverlayPermission: async () => {},
      setRestCardVisible: async () => ({}),
      addListener: async (name, cb) => {
        if (name === 'restControl') window.__native.handler = cb;
        return { remove: () => {} };
      },
    },
    NotifyStatus: { openSettings: async () => {} },
  },
};
"""


def open_app(browser, base: str):
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    page.add_init_script(FAKE)
    reroute_public_host(page, base)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input, .home-head", timeout=10_000)
    setup_and_home(page)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    page.evaluate(f"() => localStorage.setItem('{OVERLAY_FLAG}', '1')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return ctx, page


def into_rest(page) -> None:
    wait_home(page)
    start_from_home(page)
    page.wait_for_timeout(1200)
    page.locator(".exercise-item").first.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(400)
    page.locator(".log-btn").first.click()
    page.wait_for_selector(".rest-card", timeout=8000)
    page.wait_for_timeout(800)


def native(page) -> dict:
    return page.evaluate("() => window.__native")


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f104-"))
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

        # ── ① 開始休息時把待記組送下去 ──────────────────────────
        ctx, page = open_app(browser, base)
        into_rest(page)
        starts = native(page)["starts"]
        check(len(starts) >= 1, f"前提：休息交給了原生前景服務（{len(starts)} 次）")
        first = starts[-1]
        check(
            isinstance(first.get("weight"), (int, float))
            and isinstance(first.get("reps"), (int, float)),
            f"① start 帶了待記組的重量與次數（{first}）",
        )
        check("bodyweight" in first, f"① 帶了是否自體重（供視窗顯示「自體重」）（{first}）")
        check(
            isinstance(first.get("hint"), str) and first["hint"] != "",
            f"① F89 ③ 不回歸：動作提示仍照送（{first.get('hint')!r}）",
        )

        check(first.get("workoutId", 0) > 0 and first.get("exerciseId", 0) > 0,
              f"③ start 帶 LocalStore workout/exercise rowid（{first}）")
        ctx.close()

        repo = Path(__file__).resolve().parents[2]
        overlay = (
            repo / "android/app/src/main/java/com/ryanleeyi/liftlog/RestOverlay.java"
        ).read_text(encoding="utf-8")
        plugin = (
            repo / "android/app/src/main/java/com/ryanleeyi/liftlog/RestTimerPlugin.java"
        ).read_text(encoding="utf-8")
        app = (repo / "app/static/js/app.js").read_text(encoding="utf-8")
        check("LocalStore.getInstance(context)" in overlay and "store.addSet(" in overlay,
              "④ overlay 直接寫 LocalStore")
        check('"logset"' not in plugin and 'action === "logset"' not in app,
              "④ 舊 logset bridge 已移除")

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
