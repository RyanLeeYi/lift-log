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
  requestNativeExactAlarm,
  scheduleNativeRest,
  startForegroundRest,
  stopForegroundRest,
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

// ③ 的出路：精確鬧鐘被關時開系統授權頁。web 版無此概念＝no-op。
export async function requestRestNotifyExact() {
  if (native()) await requestNativeExactAlarm();
}

export async function disableRestNotify() {
  return native() ? disableNativeNotify() : disablePush();
}

export function scheduleRestNotify(seconds) {
  if (!native()) {
    scheduleRestPush(seconds);
    return;
  }
  // F63 ⑥：優先交給前景服務（通知列看得到剩幾秒）；它接手就不排 F62 的本機通知，
  // 一次休息只有一則通知行為。啟不動（權限被關、Android 12+ 背景限制）才退回 F62。
  startForegroundRest(seconds).then((taken) => {
    if (!taken) scheduleNativeRest(seconds);
  });
}

export function cancelRestNotify() {
  if (!native()) {
    cancelRestPush();
    return;
  }
  // 兩邊都收：不知道這次是誰接手的（也可能兩者都沒排），一起取消最省心且無害
  stopForegroundRest();
  cancelNativeRest();
}
