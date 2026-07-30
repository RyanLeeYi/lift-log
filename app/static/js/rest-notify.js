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
  disableRestOverlay as disableNativeOverlay,
  enableNativeNotify,
  enableRestOverlay as enableNativeOverlay,
  nativeExactAlarmOff,
  nativeNotifyAvailable,
  nativeNotifyEnabled,
  onNativeRestControl,
  pauseForegroundRest,
  refreshNativeNotifyState,
  requestNativeExactAlarm,
  restOverlayEnabled as nativeOverlayEnabled,
  restOverlaySupported as nativeOverlaySupported,
  restTimerActive,
  resumeForegroundRest,
  scheduleNativeRest,
  startForegroundRest,
  stopForegroundRest,
  syncRestCardVisible as syncNativeRestCardVisible,
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

// F64：浮動計時視窗。web 版沒有這個概念（瀏覽器畫不到其他 app 之上），一律回報不支援。
export function restOverlaySupported() {
  return native() ? nativeOverlaySupported() : false;
}

export function restOverlayEnabled() {
  return native() ? nativeOverlayEnabled() : false;
}

export async function enableRestOverlay() {
  return native()
    ? enableNativeOverlay()
    : { ok: false, reason: "瀏覽器版沒有浮動視窗" };
}

export async function disableRestOverlay() {
  if (native()) await disableNativeOverlay();
}

// F72 ③：這次休息是不是交給原生前景服務了——app 版交出去之後 JS 不該再自己震動提醒。
export function restTimerRunning() {
  return native() ? restTimerActive() : false;
}

// F71 ①：暫停／繼續要同步到原生那半（通知列與浮動視窗），web 版沒有那半＝no-op。
export async function pauseRestNotify() {
  if (native()) await pauseForegroundRest();
}

export async function resumeRestNotify() {
  if (native()) await resumeForegroundRest();
}

// F71 ⑥：訂閱原生端（浮動視窗）按下的暫停／繼續／停止。web 版沒有來源＝no-op。
export function subscribeRestControl(handler) {
  if (native()) onNativeRestControl(handler);
}

// F69：畫面切換時回報 REST 卡片是否可見。web 版沒有浮動視窗＝no-op。
export function syncRestCardVisible(visible) {
  if (native()) syncNativeRestCardVisible(visible);
}

export async function disableRestNotify() {
  return native() ? disableNativeNotify() : disablePush();
}

export function scheduleRestNotify(seconds, hint = "") {
  if (!native()) {
    scheduleRestPush(seconds);
    return;
  }
  // F63 ⑥：優先交給前景服務（通知列看得到剩幾秒）；它接手就不排 F62 的本機通知，
  // 一次休息只有一則通知行為。啟不動（權限被關、Android 12+ 背景限制）才退回 F62。
  startForegroundRest(seconds, hint).then((taken) => {
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
