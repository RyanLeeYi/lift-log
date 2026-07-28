// F62 app 版休息通知：用 Capacitor LocalNotifications 在**手機端**排程，不經伺服器。
// 相對 F31 Web Push 的增益就在這裡——伺服器不可達（關機、沒網路）時通知照樣響。
//
// 為什麼要 cache 狀態：權限查詢是非同步的，但 render() 是同步的。啟動時與每次切換後
// refresh 一次，UI 讀 cache。cache 只影響顯示，排程一律以當下實際呼叫結果為準。

const REST_ID = 1001; // 固定 id：同一次休息只會有一則，取消時不必記錄 id
const FLAG = "liftlog.nativeNotifyEnabled";

let cache = { granted: false, exact: false };

function plugin() {
  return globalThis.Capacitor?.Plugins?.LocalNotifications ?? null;
}

// F62 修正（2026-07-28 真機抓到）：`LocalNotifications.checkPermissions()` 在 Android 13 以下
// **一律回 granted**，看不到「使用者在系統設定把通知關掉」。那時 app 照樣排程、系統照樣丟掉
// （appops POST_NOTIFICATION: ignore），開關卻顯示「開」＝⑤ 禁止的靜默失敗。
// NotifyStatusPlugin 直接問 areNotificationsEnabled()，兩個版本區間都準。
function statusPlugin() {
  return globalThis.Capacitor?.Plugins?.NotifyStatus ?? null;
}

// 系統層是否真的允許發通知。沒有自寫 plugin 的舊 APK 回 null（呼叫端退回 checkPermissions）。
async function systemNotificationsEnabled() {
  const api = statusPlugin();
  if (!api) return null;
  try {
    const res = await api.enabled();
    return Boolean(res?.enabled);
  } catch {
    return null;
  }
}

// ⑤ 的「明確引導」不能只有一句話——把使用者送到該去的設定頁。
export async function openNativeNotifySettings() {
  const api = statusPlugin();
  if (!api) return;
  try {
    await api.openSettings();
  } catch {
    /* 開不了設定頁不致命，文案已說明路徑 */
  }
}

export function nativeNotifyAvailable() {
  return plugin() !== null;
}

// 使用者是否開啟 ＋ 系統是否真的允許發通知。兩者缺一都算關閉。
export function nativeNotifyEnabled() {
  return localStorage.getItem(FLAG) === "1" && cache.granted;
}

// 通知本身允許、但「精確鬧鐘」被關 → 倒數會被系統延後。UI 用它提示，不擋功能。
export function nativeExactAlarmOff() {
  return cache.granted && !cache.exact;
}

// 啟動時與每次切換後呼叫。查不到就當作沒授權（保守），不讓 UI 顯示假的「開」。
export async function refreshNativeNotifyState() {
  const api = plugin();
  if (!api) {
    cache = { granted: false, exact: false };
    return cache;
  }
  let granted = false;
  let exact = true; // 查不到就不報警——Android 11 以下沒有這個設定
  try {
    const perm = await api.checkPermissions();
    granted = perm?.display === "granted";
  } catch {
    granted = false;
  }
  // 系統層的通知開關是最終否決權：Android 13+ 兩者會一致，12 以下只有這個問得到真話
  const systemOn = await systemNotificationsEnabled();
  if (systemOn !== null) granted = granted && systemOn;
  try {
    // Android 12+ 專有；舊版會拋錯，視同不受限
    const setting = await api.checkExactNotificationSetting();
    if (setting?.exact_alarm) exact = setting.exact_alarm === "granted";
  } catch {
    /* 舊版沒有此 API：維持 exact = true */
  }
  cache = { granted, exact };
  return cache;
}

// 開啟：要權限 → 記旗標。回傳 {ok, reason?}，與 push.js 的 enablePush 同形狀。
export async function enableNativeNotify() {
  const api = plugin();
  if (!api) return { ok: false, reason: "此環境不支援本機通知" };
  let granted = false;
  try {
    const res = await api.requestPermissions();
    granted = res?.display === "granted";
  } catch {
    granted = false;
  }
  await refreshNativeNotifyState();
  if (!granted || !cache.granted) {
    // Android 12 不會跳授權框，走到這裡代表使用者在系統設定關掉了通知 →
    // 直接把他送到設定頁，不要只丟一句話（⑤ 的「明確引導、不靜默失敗」）
    await openNativeNotifySettings();
    return { ok: false, reason: "通知被系統關閉——已為你開啟設定頁，打開後回來再按一次" };
  }
  localStorage.setItem(FLAG, "1");
  return { ok: true };
}

export async function disableNativeNotify() {
  localStorage.removeItem(FLAG);
  await cancelNativeRest();
}

// 休息開始：seconds 秒後提醒。未開啟＝no-op（與 F31 的 scheduleRestPush 一致）。
export async function scheduleNativeRest(seconds) {
  const api = plugin();
  if (!api || !nativeNotifyEnabled()) return;
  try {
    await api.schedule({
      notifications: [
        {
          id: REST_ID,
          title: "休息結束",
          body: "時間到，繼續下一組！",
          schedule: {
            at: new Date(Date.now() + seconds * 1000),
            allowWhileIdle: true, // Doze 中也要響（每 9 分鐘上限，休息間隔遠短於此）
          },
        },
      ],
    });
  } catch {
    /* 排程失敗不擾訓練——與 F31 的 best-effort 一致 */
  }
}

// 提早繼續／換動作／收工／改秒數 → 取消未觸發的通知。
export async function cancelNativeRest() {
  const api = plugin();
  if (!api) return;
  try {
    await api.cancel({ notifications: [{ id: REST_ID }] });
  } catch {
    /* 沒有待觸發的通知時某些版本會拋錯，無妨 */
  }
}
