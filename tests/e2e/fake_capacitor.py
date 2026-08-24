"""假 Capacitor plugin 的共用組裝入口（非產品碼；F167）。

背景：tests/e2e/ 下原本有 17 支腳本各自手刻一份 window.Capacitor.Plugins stub
（fake_plugins() / FAKE 樣板），上游 plugin 介面一變就要改 17 處，且各副本已有
細微漂移。這裡收斂成一個入口：`build_fake_capacitor()` 組出完整的
`window.Capacitor = {...}` 賦值語句，直接餵給 `page.add_init_script()`。

AuthSession／LocalStore／AppUpdate／Sync／LocalNotifications／RestTimer／
NotifyStatus 七個鍵各自獨立傳入一段「方法本體」文字（外層的 `Key: { ... }`
由這裡代勞包起來）；某鍵傳 None 就整把從 Plugins 省略。channel 清單、
LocalNotifications、RestTimer、NotifyStatus 額外提供 DEFAULT_* 預設本體，
取自現行多數腳本共用的那份（源自 F67/F103/F104/F108/F89 一系的寫法），
腳本可原樣沿用或傳自己的字串整段覆寫。

只給測試碼用，不含任何 app/ 產品邏輯。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 預設 stub
# ---------------------------------------------------------------------------

DEFAULT_CHANNELS = "[{ id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 }]"

DEFAULT_LOCAL_NOTIFICATIONS = """
      schedule: async () => ({}),
      cancel: async () => ({}),
      checkPermissions: async () => ({ display: 'granted' }),
      requestPermissions: async () => ({ display: 'granted' }),
      areEnabled: async () => ({ value: true }),
      listChannels: async () => ({ channels: [
        { id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 },
      ] }),
"""

DEFAULT_REST_TIMER = """
      available: async () => ({ available: true }),
      start: async () => ({}),
      stop: async () => ({}),
      pause: async () => ({}),
      resume: async () => ({}),
      overlayPermitted: async () => ({ granted: true }),
      requestOverlayPermission: async () => {},
      setRestCardVisible: async () => ({}),
      addListener: async () => ({ remove: () => {} }),
"""

DEFAULT_NOTIFY_STATUS = """
      openSettings: async () => {},
"""

# LocalStore 家族：AuthSession/LocalStore/Sync 常一起出現（開機還原路徑），
# LocalStore 的方法本體閉包捕捉 preamble 裡的 local/nextWorkout/nextSet。
DEFAULT_LOCAL_STORE_PREAMBLE = """
const local = {
  exercises: [{ id: 1, name_zh: '深蹲', name_en: 'Squat', muscle_group: '腿', is_bodyweight: 0 }],
  templates: [], workouts: [], sets: [], body_metrics: [], daily_status: [], settings: [],
};
let nextWorkout = 1;
let nextSet = 1;
"""

DEFAULT_LOCAL_STORE = """
      initialize: async () => ({ schemaVersion: 2, seededExercises: 1, pendingMutations: 0 }),
      snapshot: async () => structuredClone(local),
      createWorkout: async (o) => {
        const row = { id: nextWorkout++, date: o.date, template_id: o.templateId ?? null,
          note: o.note ?? null, created_at: new Date().toISOString(), ended_at: null };
        local.workouts.push(row);
        return structuredClone(row);
      },
      addSet: async (o) => {
        const row = { id: nextSet++, client_uuid: o.clientUuid, workout_id: o.workoutId,
          exercise_id: o.exerciseId, set_number: o.setNumber ?? nextSet - 1,
          weight_kg: o.weightKg, reps: o.reps, rpe: o.rpe ?? null,
          rest_seconds: o.restSeconds ?? null };
        local.sets.push(row);
        return structuredClone(row);
      },
      status: async () => ({ schemaVersion: 2, pendingMutations: 0 }),
"""


# ---------------------------------------------------------------------------
# F67 家族：app 內自我更新 ＋ 開機還原（AuthSession/LocalStore/AppUpdate/Sync）。
# 這份是 IIFE 樣板（不是 build_fake_capacitor() 的「方法本體」片段）——historical，
# verify_f61.py／verify_f110.py 仍以 `FAKE_PLUGIN.strip().join(["(", f"){args}"])`
# 的方式自行組 IIFE 呼叫，這裡原樣保留字串內容，只搬家不改內容。
# ---------------------------------------------------------------------------

# canInstall 由 window.__canInstall 控制，才能同時驗「已授權」與「未授權」兩條路。
FAKE_PLUGIN = """
(currentVersion, canInstall) => {
  window.__au = { downloads: [], installs: [], openedSettings: 0 };
  window.__canInstall = canInstall;
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
      // F141：舊 feature 的 native 模擬代表「已登入過的裝置」；登入本身由 verify_f141 驗。
      AuthSession: {
        loadSession: async () => ({ deviceId: '11111111-1111-4111-8111-111111111111',
          deviceName: 'Test Pixel', accessToken: 'f141-access', refreshToken: 'f141-refresh',
          accessExpiresAt: Date.now() + 600000 }),
      },
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
          const row = { id: nextSet++, client_uuid: o.clientUuid, workout_id: o.workoutId,
            exercise_id: o.exerciseId, set_number: o.setNumber ?? nextSet - 1,
            weight_kg: o.weightKg, reps: o.reps, rpe: o.rpe ?? null,
            rest_seconds: o.restSeconds ?? null };
          local.sets.push(row);
          return structuredClone(row);
        },
        putSetting: async (o) => {
          const row = { key: o.key, value: o.value };
          local.settings = local.settings.filter((item) => item.key !== o.key);
          local.settings.push(row);
          return structuredClone(row);
        },
        status: async () => ({ schemaVersion: 2, pendingMutations: 0 }),
      },
      AppUpdate: {
        currentVersion: async () => ({ versionCode: currentVersion }),
        canInstall: async () => ({ allowed: window.__canInstall }),
        openInstallSettings: async () => { window.__au.openedSettings += 1; },
        addListener: async (name, cb) => { window.__cb = cb; return { remove: () => {} }; },
        download: async (opts) => {
          window.__au.downloads.push(opts);
          window.__cb && window.__cb({ written: 5, total: 10 });
          return { path: '/data/updates/lift-log-update.apk' };
        },
        install: async (opts) => { window.__au.installs.push(opts); },
      },
      // F131 起開機會呼叫 initializeNativeSync()／readNativeSyncStatus()——沒有這顆
      // 外掛會拋錯，害 nativeBootstrapRequired 卡死在「正在準備本機資料」而永遠到不了首頁
      // （F61/F81/F110 三支腳本 2026-08-13 之前就是卡在這裡，見 handoff）。
      Sync: {
        initialize: async () => ({ state: 'synced', pending: 0, failed: 0, cursor: 0,
          lastSyncedAt: Date.now(), errorCode: null, nextSyncAt: 0,
          bootstrapComplete: true, conflicts: 0 }),
        status: async () => ({ state: 'synced', pending: 0, failed: 0, cursor: 0,
          lastSyncedAt: Date.now(), errorCode: null, nextSyncAt: 0,
          bootstrapComplete: true, conflicts: 0 }),
        syncNow: async () => ({ state: 'synced', pending: 0, failed: 0, cursor: 0,
          lastSyncedAt: Date.now(), errorCode: null, nextSyncAt: 0,
          bootstrapComplete: true, conflicts: 0 }),
      },
    },
  };
}
"""


def build_fake_capacitor(
    *,
    platform: str = "android",
    preamble: str = "",
    auth_session: str | None = None,
    local_store: str | None = None,
    app_update: str | None = None,
    sync: str | None = None,
    local_notifications: str | None = None,
    rest_timer: str | None = None,
    notify_status: str | None = None,
    extra_plugins: str = "",
) -> str:
    """組出可直接傳給 `page.add_init_script()` 的 JS 字串。

    每個 plugin 參數是該鍵「方法本體」的 JS 文字（不含外層 `Key: { ... }`，
    這裡代勞包起來）；傳 `None` 就整把鍵從 `Plugins` 省略。`preamble` 放在
    `window.Capacitor` 賦值之前（追蹤用的 `window.__xxx`、LocalStore 用的
    `local`/`nextWorkout`/`nextSet` 等）。`extra_plugins` 供需要在 Plugins
    物件裡加自訂鍵（非上述七個標準鍵）時使用，原樣接在標準鍵之後。
    """
    named = (
        ("AuthSession", auth_session),
        ("LocalStore", local_store),
        ("AppUpdate", app_update),
        ("Sync", sync),
        ("LocalNotifications", local_notifications),
        ("RestTimer", rest_timer),
        ("NotifyStatus", notify_status),
    )
    body = "".join(f"    {name}: {{{text}}},\n" for name, text in named if text is not None)
    return f"""
{preamble}
window.Capacitor = {{
  isNativePlatform: () => true,
  getPlatform: () => '{platform}',
  Plugins: {{
{body}{extra_plugins}
  }},
}};
"""


def demo() -> None:
    """最小自我檢查：組出的文字要是合法可執行的 JS（用 Node 語法層面驗不到，
    這裡只驗 Python 端的字串組裝邏輯——鍵的有無、preamble 位置）。"""
    script = build_fake_capacitor(
        preamble="const x = 1;",
        local_notifications=DEFAULT_LOCAL_NOTIFICATIONS,
        rest_timer=DEFAULT_REST_TIMER,
        notify_status=DEFAULT_NOTIFY_STATUS,
    )
    assert "const x = 1;" in script
    assert "LocalNotifications: {" in script
    assert "RestTimer: {" in script
    assert "NotifyStatus: {" in script
    assert "AuthSession" not in script
    assert "LocalStore" not in script
    assert "Sync" not in script

    with_store = build_fake_capacitor(
        preamble=DEFAULT_LOCAL_STORE_PREAMBLE,
        local_store=DEFAULT_LOCAL_STORE,
    )
    assert "LocalStore: {" in with_store
    assert "RestTimer" not in with_store
    print("PASS  fake_capacitor.demo()")


if __name__ == "__main__":
    demo()
