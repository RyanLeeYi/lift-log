// F61 執行環境偵測：同一份前端碼同時服務 web 與 Capacitor 原生殼。
//
// web 版：由 FastAPI 直接供檔，API 走相對路徑（同源，行為與 F60 之前完全一致）。
// app 版：資產打包在 APK 內，WebView 的 origin 是 https://localhost，
//         相對路徑會打到不存在的本機伺服器 —— 必須把 API 指回公開站（需後端 CORS，見 main.py）。
//
// ⚠ 這裡是 app 版唯一寫死公開站網址的地方。換網域就改這一行。

const NATIVE_API_BASE = "https://lift-log.my-super-dev-server.work";

// Capacitor 由原生層注入 window.Capacitor；web 版永遠沒有這個物件。
export function isNativeApp() {
  return Boolean(globalThis.Capacitor?.isNativePlatform?.());
}

// 前綴給 fetch 用：web 版回空字串（維持相對路徑），app 版回公開站 origin。
export function apiBase() {
  return isNativeApp() ? NATIVE_API_BASE : "";
}
