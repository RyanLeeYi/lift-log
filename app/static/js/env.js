// F61 執行環境偵測：同一份前端碼同時服務 web 與 Capacitor 原生殼。
//
// web 版：由 FastAPI 直接供檔，API 走相對路徑（同源，行為與 F60 之前完全一致）。
// app 版：資產打包在 APK 內，WebView 的 origin 是 https://localhost，
//         相對路徑會打到不存在的本機伺服器 —— 必須把 API 指回公開站（需後端 CORS，見 main.py）。
//
// F93 ⑤：app 版有兩個 flavor，各自連不同的站。
// `SITE` 這一行由 `scripts/build-apk.ps1` 在建置前改寫，建置後再從 APK 內解出來核對——
// 改寫失敗卻照樣出貨的話，你會拿到一顆「檔名寫 dev、實際連正式站」的 APK，
// 而它會安靜地把測試資料寫進真實紀錄裡。所以那支腳本會驗過才收工。
//
// ⚠ 換網域改這裡的兩個常數；**不要**改 SITE 那一行的格式（腳本用正則對它）。

const API_BASE_BY_SITE = {
  prod: "https://lift-log.my-super-dev-server.work",
  dev: "https://lift-log-dev.my-super-dev-server.work",
};

const SITE = "prod"; // build-apk.ps1 會改寫這一行

// Capacitor 由原生層注入 window.Capacitor；web 版永遠沒有這個物件。
export function isNativeApp() {
  return Boolean(globalThis.Capacitor?.isNativePlatform?.());
}

/** 這顆 APK 打包時綁定的站別（web 版無意義）。給建置驗證與診斷用。 */
export function nativeSite() {
  return SITE;
}

// 前綴給 fetch 用：web 版回空字串（維持相對路徑），app 版回該 flavor 綁定的站。
export function apiBase() {
  if (!isNativeApp()) return "";
  return API_BASE_BY_SITE[SITE] ?? API_BASE_BY_SITE.prod;
}
