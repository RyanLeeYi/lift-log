// F62 app 版休息通知：用 Capacitor LocalNotifications 在**手機端**排程，不經伺服器。
// 相對 F31 Web Push 的增益就在這裡——伺服器不可達（關機、沒網路）時通知照樣響。
//
// 為什麼要 cache 狀態：權限查詢是非同步的，但 render() 是同步的。啟動時與每次切換後
// refresh 一次，UI 讀 cache。cache 只影響顯示，排程一律以當下實際呼叫結果為準。

const REST_ID = 1001; // 固定 id：同一次休息只會有一則，取消時不必記錄 id
const FLAG = "liftlog.nativeNotifyEnabled";
// F107：前景服務接不了手的紀錄。持久化是刻意的——它描述的是「這台裝置的狀況」，
// 不是這次 session 的狀況，重開 app 之後那個風險還在。
const FALLBACK_FLAG = "liftlog.fgFallbackSeen";

let cache = { granted: false, exact: false, channelOff: false };

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

// F65：Android 的通知開關有兩層——app 層（areEnabled）與 channel 層。
// 使用者被吵到時最直覺的動作是長按通知選「關閉這類通知」，那只會把 channel 的
// importance 設成 IMPORTANCE_NONE(0)，app 層仍是允許的。只看 areEnabled 的話，
// 開關會顯示「開」而提醒永遠不出現——F62 review 指出的靜默失敗。
const IMPORTANCE_NONE = 0;
// F95：休息提醒實際上會出現在**兩個** channel 的其中一個，兩個都要看。
// - `rest-timer`：F63 前景服務自己建的（RestTimerService，顯示名「休息倒數」）。
//   平常就是這一則——使用者被吵到時長按的也是它。
// - `default`：Capacitor LocalNotifications 的預設 channel（我們排通知時沒指定 channelId）。
//   只有前景服務啟不動時才走到。
//
// 任一個被關就顯示「關」是刻意的保守：JS 這一側無法預知這次休息會走哪一條
// （startForegroundRest 成不成功要到當下才知道），寧可多提醒一次，
// 也不要讓使用者以為提醒是開著的。
const REST_CHANNEL_IDS = ["rest-timer", "default"];

/**
 * 這一類通知是不是被單獨關掉了。
 *
 * ⚠ 「查不到」**不等於**「被關掉」，這裡刻意與 systemNotificationsEnabled() 的
 * 保守方向相反。理由不是「channel 還沒建立」——Capacitor 的 default channel 在
 * plugin load 時就無條件建好了，API 26+ 一定查得到（review 查證）。真正的理由是
 * **這道只是額外的一層限制**：`listChannels` 不存在或拋錯（API 25 以下根本沒有
 * channel 概念）時，該由 areEnabled() 這個 app 層的事實來源說了算，不該因為問不到
 * 附加條件就把功能擋死。
 *
 * ⚠ 這裡只看 default channel。F63 前景服務那則倒數通知掛在自己的 `rest-timer`
 * channel（RestTimerService.java），**不在這道判定裡**——見 F95。
 */
async function restChannelMuted() {
  const api = plugin();
  if (!api?.listChannels) return false;
  try {
    const res = await api.listChannels();
    const channels = res?.channels ?? [];
    return REST_CHANNEL_IDS.some((id) => {
      const channel = channels.find((c) => c?.id === id);
      // 不存在就跳過：`rest-timer` 要到前景服務第一次啟動才建立，全新裝置上本來就沒有。
      return channel ? channel.importance === IMPORTANCE_NONE : false;
    });
  } catch {
    return false; // 舊版／不支援：退回 areEnabled 的判定
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

/**
 * F107：這次休息是不是交給前景服務了——把結果記下來，當作「要不要警告可能延遲」的依據。
 *
 * <p>接手成功就把紀錄清掉：裝置狀況會變（使用者把 app 加進電池白名單、換了 OEM 韌體），
 * 一次失敗不該永久掛著警告。
 */
export function noteForegroundTakeover(taken) {
  if (taken) localStorage.removeItem(FALLBACK_FLAG);
  else localStorage.setItem(FALLBACK_FLAG, "1");
}

function foregroundFallbackSeen() {
  return localStorage.getItem(FALLBACK_FLAG) === "1";
}

/**
 * 通知本身允許、但「精確鬧鐘」被關 → 倒數**可能**會被系統延後。UI 用它提示，不擋功能。
 *
 * <p>F107：光看權限會誤報。自 F63 起休息倒數的主要路徑是原生前景服務（自己跑
 * CountDownTimer），**完全不碰鬧鐘排程**；精確鬧鐘只在前景服務啟不動時的退路
 * （scheduleNativeRest）才用得到。所以要兩個條件都成立才警告。
 *
 * <p>為什麼用「觀測到的失敗」而不是預判：Android 沒有「我等一下起不起得來前景服務」
 * 的查詢 API，OEM 省電策略也查不到。硬猜的條件會變成另一個方向的誤報。
 *
 * <p>代價（Ryan 2026-07-31 接受）：**第一次**遇到前景服務起不來時沒有預先警告。
 * 換掉的是「多數人一直看到假警告」——假警告看久了就沒人看，真的那次也會被忽略。
 */
export function nativeExactAlarmOff() {
  return cache.granted && !cache.exact && foregroundFallbackSeen();
}

// 啟動時與每次切換後呼叫。查不到就當作沒授權（保守），不讓 UI 顯示假的「開」。
export async function refreshNativeNotifyState() {
  // F64：overlay 授權會在 app 外被改（使用者跳去設定頁開／關），與通知同一時機重查。
  // F62 review 的教訓：回到前景不重查就會顯示過期狀態，變成靜默失敗。
  await refreshOverlayGranted();
  const api = plugin();
  if (!api) {
    cache = { granted: false, exact: false, channelOff: false };
    return cache;
  }
  let exact = true; // 查不到就不報警——Android 11 以下沒有這個設定
  // 唯一事實來源：系統當下是否允許本 app 發通知（見上方 systemNotificationsEnabled 的說明）
  const appAllowed = await systemNotificationsEnabled();
  // F65 ②：channel 被單獨關掉時通知同樣不會出現，所以它與 areEnabled 一起構成 granted。
  // channelOff 另外留著——UI 要能講出是「這類通知」被關，而不是籠統說「通知被關閉」。
  const channelOff = appAllowed ? await restChannelMuted() : false;
  const granted = appAllowed && !channelOff;
  try {
    // Android 12+ 專有；舊版會拋錯，視同不受限
    const setting = await api.checkExactNotificationSetting();
    if (setting?.exact_alarm) exact = setting.exact_alarm === "granted";
  } catch {
    /* 舊版沒有此 API：維持 exact = true */
  }
  cache = { granted, exact, channelOff };
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
    // F65 ①：兩層要分開講。「整個 app 的通知被關」與「這類通知被單獨關掉」在設定頁裡
    // 是不同的兩個開關，講錯的話使用者會在正確的頁面上找不到該開的東西。
    return {
      ok: false,
      // ⚠ 不要在文案裡寫死類別名稱。default channel 在系統設定裡顯示為 Capacitor 寫死的
      // 「Default」，而 F63 前景服務那則叫「休息倒數」——講一個對不上的名字，等於讓人
      // 在正確的頁面上找不到該開的東西（正是 ① 要避免的）。只指路，不報名字。
      reason: cache.channelOff
        ? "休息提醒的通知類別被單獨關掉了——已開啟設定頁，在通知類別清單裡打開後回來再按一次"
        : "通知被系統關閉——已為你開啟設定頁，打開後回來再按一次",
    };
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

// ---------- F64：浮動計時視窗（overlay） ----------
//
// overlay 不是獨立的計時器，只是同一個前景服務的第二個顯示面（③）：關掉它、沒授權、
// 或使用者根本沒開，通知列的倒數都照樣走完。所以這裡只管「要不要畫」這一個位元。

const OVERLAY_FLAG = "liftlog.restOverlayEnabled";
let overlayGranted = false; // 系統是否允許畫在其他 app 上（授權狀態，非使用者意願）

export function restOverlaySupported() {
  return restTimerPlugin() !== null;
}

// 使用者開了 ＋ 系統允許。缺一都不畫（不顯示假的「開」）。
export function restOverlayEnabled() {
  return localStorage.getItem(OVERLAY_FLAG) === "1" && overlayGranted;
}

// F89 ⑥：把「系統有沒有授權」單獨透出去。
//
// 原本只有 restOverlayEnabled() 一個位元，UI 因此分不出兩種「關」——「使用者自己不要」
// 與「系統沒授權所以畫不了」。前者不需要引導，後者需要（而且要常駐，不是點下去才跳一次
// 錯誤訊息就消失）。授權狀態由 refreshNativeNotifyState() 每次回前景一併重查。
export function restOverlayPermitted() {
  return overlayGranted;
}

async function refreshOverlayGranted() {
  const api = restTimerPlugin();
  if (!api?.overlayPermitted) {
    overlayGranted = false;
    return false;
  }
  try {
    const res = await api.overlayPermitted();
    overlayGranted = Boolean(res?.granted);
  } catch {
    overlayGranted = false; // 查不到就當沒授權（與 F62 的保守判定一致）
  }
  return overlayGranted;
}

// ②：未授權時把人送到系統設定頁，並誠實回報失敗——不留假的「開」。
export async function enableRestOverlay() {
  const api = restTimerPlugin();
  if (!api) return { ok: false, reason: "此環境不支援浮動視窗" };
  if (await refreshOverlayGranted()) {
    localStorage.setItem(OVERLAY_FLAG, "1");
    return { ok: true };
  }
  try {
    await api.requestOverlayPermission();
  } catch {
    return { ok: false, reason: "這台裝置沒有浮動視窗授權頁——休息倒數仍會顯示在通知列" };
  }
  return { ok: false, reason: "請在設定裡允許「顯示在其他應用程式上層」，回來再按一次" };
}

export async function disableRestOverlay() {
  localStorage.removeItem(OVERLAY_FLAG);
}

// F69 ③：回報「現在看不看得到 app 內的 REST 卡片」。
//
// render() 每秒都會跑，同值不重送——每秒打一次 bridge 沒有意義，也讓原生那邊每秒重算顯示。
// 這裡只管「卡片可見性」這一個位元；app 前不前景由原生的 ActivityLifecycleCallbacks 判定。
let lastCardVisible = null;

export function syncRestCardVisible(visible) {
  const api = restTimerPlugin();
  const value = Boolean(visible);
  if (!api?.setRestCardVisible || value === lastCardVisible) return;
  lastCardVisible = value;
  try {
    api.setRestCardVisible({ visible: value })?.catch?.(() => {});
  } catch {
    /* 舊版 APK 沒有這個方法：overlay 退回 F64 的行為（休息期間一直顯示），不致命 */
  }
}

// 回傳 true＝前景服務接手了（呼叫端就不要再排本機通知）
export async function startForegroundRest(seconds, hint = "") {
  const api = restTimerPlugin();
  if (!api || !nativeNotifyEnabled()) return false;
  try {
    const { available } = await api.available();
    if (!available) return false;
    // F89 ③：hint 是「動作名 · 第 N 組」，只給浮動視窗顯示；服務自己不解讀
    await api.start({ seconds, overlay: restOverlayEnabled(), hint });
    foregroundActive = true;
    return true;
  } catch {
    // Android 12+ 背景啟動前景服務可能被擋——安靜退回 F62，不擾訓練
    foregroundActive = false;
    return false;
  }
}

// ---------- F71：暫停／繼續，以及原生端（浮動視窗）按鈕的回傳 ----------

export async function pauseForegroundRest() {
  const api = restTimerPlugin();
  if (!api?.pause) return;
  try {
    await api.pause();
  } catch {
    /* 服務沒在跑：畫面狀態仍以前端為準 */
  }
}

export async function resumeForegroundRest() {
  const api = restTimerPlugin();
  if (!api?.resume) return;
  try {
    await api.resume();
  } catch {
    /* 同上 */
  }
}

// ⑥：原生→前端一律走事件。**不輪詢**——app 在背景時輪詢會被節流，
// 而「人在別的 app 裡按浮動視窗」正是最需要它可靠的那一刻。
export function onNativeRestControl(handler) {
  const api = restTimerPlugin();
  if (!api?.addListener) return;
  try {
    // F103 ⑤：payload 要帶秒數。停止態的 ±15s 全發生在原生層，前端無從得知
    // 「再開始」該從幾秒重跑；只送動作名的話兩邊必然各說各話。
    api.addListener("restControl", (event) =>
      handler(event?.action, typeof event?.seconds === "number" ? event.seconds : null),
    );
  } catch {
    /* 舊版 APK 沒有這個事件：退回只有 app 內控制得動，不致命 */
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
