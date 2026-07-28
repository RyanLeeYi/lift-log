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

// F62（2026-07-28 真機抓到、07-28 review 修正）：真機上出現過「開關顯示開、通知卻被系統丟掉」。
// `checkPermissions()` 的語意分兩段——Android 13 以下走 areNotificationsEnabled()，13+ 走
// POST_NOTIFICATIONS 執行期權限，後者看不到「使用者在系統設定關掉通知」。
// 所以狀態一律以 `areEnabled()`（plugin 既有 API，實作就是 areNotificationsEnabled()）為準。
//
// ⚠ 這裡**不做靜默降級**：查不到就當作沒授權。降級成 checkPermissions 等於把上面那個 bug 放回來，
// 而且畫面上不會有任何跡象（review MEDIUM）。
async function systemNotificationsEnabled() {
  const api = plugin();
  if (!api?.areEnabled) return false;
  try {
    const res = await api.areEnabled();
    return Boolean(res?.value);
  } catch {
    return false;
  }
}

// 自寫 plugin 只負責「開啟本 app 的通知設定頁」——Capacitor 沒有對應 API。
function statusPlugin() {
  return globalThis.Capacitor?.Plugins?.NotifyStatus ?? null;
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

// ③ 的出路：精確鬧鐘被關時，開系統的「鬧鐘與提醒」授權頁（與 ⑤ 同等級的處置，
// 不能只在按鈕上寫「可能延遲」卻不告訴人去哪開）。
export async function requestNativeExactAlarm() {
  const api = plugin();
  if (!api?.changeExactNotificationSetting) return;
  try {
    await api.changeExactNotificationSetting();
  } catch {
    /* 使用者取消或系統不支援：維持現狀，按鈕仍誠實標示「可能延遲」 */
  }
  await refreshNativeNotifyState();
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
  let exact = true; // 查不到就不報警——Android 11 以下沒有這個設定
  // 唯一事實來源：系統當下是否允許本 app 發通知（見上方 systemNotificationsEnabled 的說明）
  const granted = await systemNotificationsEnabled();
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
  // 判定一律看 refresh 後的系統狀態，不看 requestPermissions 的回覆：
  // Android 12 以下不跳授權框，13+ 使用者也可能在設定裡關掉整個 app 的通知
  if (!granted || !cache.granted) {
    // 走到這裡＝系統當下不允許發通知。直接把人送到設定頁，不要只丟一句話
    // （⑤ 的「明確引導、不靜默失敗」）
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

// ---------- F63：前景服務倒數（通知列常駐） ----------
//
// ⑥ 的分工：前景服務可用時由它負責整段休息（含歸零時把同一則通知改成「休息結束」），
// **此時不排 F62 的本機通知**——一次休息只有一則通知行為。啟不動就退回 F62。
//
// 為什麼倒數放原生：JS 計時器在 app 進背景後會被系統節流，通知列的秒數會不準或停住。

function restTimerPlugin() {
  return globalThis.Capacitor?.Plugins?.RestTimer ?? null;
}

let foregroundActive = false; // 這次休息是否已交給前景服務

export function restTimerActive() {
  return foregroundActive;
}

// 回傳 true＝前景服務接手了（呼叫端就不要再排本機通知）
export async function startForegroundRest(seconds) {
  const api = restTimerPlugin();
  if (!api || !nativeNotifyEnabled()) return false;
  try {
    const { available } = await api.available();
    if (!available) return false;
    await api.start({ seconds });
    foregroundActive = true;
    return true;
  } catch {
    // Android 12+ 背景啟動前景服務可能被擋——安靜退回 F62，不擾訓練
    foregroundActive = false;
    return false;
  }
}

export async function stopForegroundRest() {
  const api = restTimerPlugin();
  foregroundActive = false;
  if (!api) return;
  try {
    await api.stop();
  } catch {
    /* 沒在跑就停不掉，無妨 */
  }
}
