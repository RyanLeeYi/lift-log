// F31 Web Push：休息結束通知。開關存 localStorage；訂閱經 pushManager，
// 休息排程/取消交後端（in-process 排程器）。排程/取消一律 best-effort，失敗不擾訓練。

import { api } from "./api.js";
import { isNativeApp } from "./env.js";

const PUSH_FLAG = "liftlog.pushEnabled";

// F61：app 版一律回 false。原生殼不註冊 SW，`navigator.serviceWorker.ready` 會**永遠不 resolve**，
// enablePush 會卡死在那一行而不是報錯。休息通知由 F62 的本機通知接手（README 已知限制）。
export function pushSupported() {
  return (
    !isNativeApp() &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function pushEnabled() {
  return (
    localStorage.getItem(PUSH_FLAG) === "1" &&
    pushSupported() &&
    Notification.permission === "granted"
  );
}

// VAPID 公鑰（base64url）轉 applicationServerKey 需要的 Uint8Array
function urlBase64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) arr[i] = raw.charCodeAt(i);
  return arr;
}

// 開啟通知：要權限 → 取 VAPID 公鑰 → 訂閱 → 送後端。回傳 {ok, reason?}
export async function enablePush() {
  if (!pushSupported()) return { ok: false, reason: "此瀏覽器不支援通知（iPhone 需先把 app 加到主畫面）" };
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return { ok: false, reason: "沒有通知權限——請到瀏覽器設定允許" };
  const info = await api.pushPublicKey();
  if (!info.enabled || !info.key) return { ok: false, reason: "伺服器尚未設定推播" };
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(info.key),
  });
  await api.pushSubscribe(sub.toJSON());
  localStorage.setItem(PUSH_FLAG, "1");
  return { ok: true };
}

export async function disablePush() {
  localStorage.removeItem(PUSH_FLAG);
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) await sub.unsubscribe();
  } catch {
    /* 取消訂閱失敗無妨：本機旗標已關，不再排程 */
  }
}

// 排程/取消序列化：各自 fire-and-forget 在慢網下可能亂序（cancel 先到、schedule 後到 → 誤推）。
// 串成一條 promise 鏈、依呼叫順序逐一送達，後端就照正確順序處理（Codex P2）。
let _pushChain = Promise.resolve();

function _enqueue(run) {
  _pushChain = _pushChain.then(run, run); // 前一個失敗也繼續下一個
  return _pushChain;
}

// 休息開始：排定 seconds 後推「休息結束」。未開通知＝no-op。
export function scheduleRestPush(seconds) {
  if (!pushEnabled()) return;
  _enqueue(() => api.scheduleRest(seconds).catch(() => {}));
}

// 提早繼續/換動作/收工/改秒數：取消未觸發的休息通知。
export function cancelRestPush() {
  if (!pushEnabled()) return;
  _enqueue(() => api.cancelRest().catch(() => {}));
}
