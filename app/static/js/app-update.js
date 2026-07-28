// F67 app 版自我更新：查伺服器最新版 → 下載 → 喚起系統安裝器。
//
// web 版沒有這回事（部署完自動到位，見 F13/F14/F24），所以整個模組在 web 版是 no-op：
// `checkForUpdate()` 直接回 null，首頁不會出現任何橫幅。

import { api, getToken } from "./api.js";
import { apiBase, isNativeApp } from "./env.js";

function plugin() {
  return globalThis.Capacitor?.Plugins?.AppUpdate ?? null;
}

// {available, versionCode, sizeBytes} 或 null（web 版／查不到／已是最新）。
// ③：查詢失敗一律回 null——沒有更新提示比錯誤的更新提示好，訓練中不該被打擾。
export async function checkForUpdate() {
  const nativeApi = plugin();
  if (!isNativeApp() || !nativeApi) return null;
  try {
    const [{ versionCode }, latest] = await Promise.all([
      nativeApi.currentVersion(),
      api.appLatest(),
    ]);
    if (!latest || latest.version_code <= versionCode) return null;
    return {
      versionCode: latest.version_code,
      versionName: latest.version_name,
      sizeBytes: latest.size_bytes,
      url: latest.url,
    };
  } catch {
    // 伺服器沒有發佈版本（404）、離線、token 失效——都當作「沒有更新」
    return null;
  }
}

// 下載並喚起安裝器。onProgress(0–1) 供 UI 畫進度。
// 回傳 {ok} 或 {ok:false, reason}——⑥ 每種失敗都要有可辨識的訊息。
export async function downloadAndInstall(update, onProgress) {
  const nativeApi = plugin();
  if (!nativeApi) return { ok: false, reason: "此環境不支援自動更新" };

  const { allowed } = await nativeApi.canInstall();
  if (!allowed) {
    // ⑤：直接送到該去的設定頁，與 F62 的通知授權同一套處置
    await nativeApi.openInstallSettings();
    return { ok: false, reason: "需要允許安裝未知應用程式——已開啟設定頁，開啟後回來再試" };
  }

  let listener = null;
  try {
    if (onProgress) {
      listener = await nativeApi.addListener("downloadProgress", ({ written, total }) => {
        if (total > 0) onProgress(written / total);
      });
    }
    const { path } = await nativeApi.download({
      url: new URL(update.url, apiBase() || location.origin).toString(),
      token: getToken(),
    });
    await nativeApi.install({ path });
    return { ok: true };
  } catch (err) {
    return { ok: false, reason: err?.message || "更新失敗，請稍後再試" };
  } finally {
    listener?.remove?.();
  }
}

// F68 ②：使用者對「某個版本」按過稍後再說就別再自動彈。記版號而不是布林——
// 出更新的版本時必須重新提醒，否則按一次就永遠靜音了。
const DISMISS_KEY = "liftlog.updateDismissed";

export function isDismissed(versionCode) {
  return Number(localStorage.getItem(DISMISS_KEY) || 0) >= versionCode;
}

export function dismissUpdate(versionCode) {
  localStorage.setItem(DISMISS_KEY, String(versionCode));
}
