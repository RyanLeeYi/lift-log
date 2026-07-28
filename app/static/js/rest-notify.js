// F62 休息提醒的統一入口：app.js 只認這一層，兩種執行環境各走各的實作。
//
//   web  → F31 Web Push（伺服器端排程器 + PushSubscription，未更動）
//   app  → 手機端本機通知（native-notify.js），伺服器不可達時照樣響
//
// 分流只在這個檔案發生。加新環境時改這裡，不要在 app.js 裡長出第二套 if。

import { isNativeApp } from "./env.js";
import {
  cancelNativeRest,
  disableNativeNotify,
  enableNativeNotify,
  nativeExactAlarmOff,
  nativeNotifyAvailable,
  nativeNotifyEnabled,
  refreshNativeNotifyState,
  scheduleNativeRest,
} from "./native-notify.js";
import {
  cancelRestPush,
  disablePush,
  enablePush,
  pushEnabled,
  pushSupported,
  scheduleRestPush,
} from "./push.js";

const native = () => isNativeApp();

export function restNotifySupported() {
  return native() ? nativeNotifyAvailable() : pushSupported();
}

export function restNotifyEnabled() {
  return native() ? nativeNotifyEnabled() : pushEnabled();
}

// 只有 app 版有意義：通知開著但精確鬧鐘被關 → 倒數可能被系統延後。
export function restNotifyDelayed() {
  return native() ? nativeExactAlarmOff() : false;
}

// 啟動時呼叫一次，讓 app 版的開關能顯示正確狀態（web 版是同步判定，不需要）。
export async function refreshRestNotifyState() {
  if (native()) await refreshNativeNotifyState();
}

export async function enableRestNotify() {
  return native() ? enableNativeNotify() : enablePush();
}

export async function disableRestNotify() {
  return native() ? disableNativeNotify() : disablePush();
}

export function scheduleRestNotify(seconds) {
  if (native()) scheduleNativeRest(seconds);
  else scheduleRestPush(seconds);
}

export function cancelRestNotify() {
  if (native()) cancelNativeRest();
  else cancelRestPush();
}
