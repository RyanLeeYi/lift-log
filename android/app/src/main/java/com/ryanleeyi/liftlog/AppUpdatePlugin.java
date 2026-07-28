package com.ryanleeyi.liftlog;

import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * F67：sideload 版的自我更新——查自己的版號、下載新 APK、喚起系統安裝器。
 *
 * <p>下載放在原生層而不是 JS：APK 有數 MB，走 JS 會被迫 base64 進出 bridge（體積膨脹 4/3、
 * 整包進記憶體），而且拿不到串流進度。這裡直接寫檔並回報 bytes，JS 只負責畫進度。
 */
@CapacitorPlugin(name = "AppUpdate")
public class AppUpdatePlugin extends Plugin {

    private static final String UPDATE_DIR = "updates";

    /** 自己的 versionCode——F67 ① 讓它由 APP_VERSION 推導，所以可直接與伺服器版本比大小。 */
    @PluginMethod
    public void currentVersion(PluginCall call) {
        JSObject result = new JSObject();
        try {
            long code = getContext()
                .getPackageManager()
                .getPackageInfo(getContext().getPackageName(), 0)
                .getLongVersionCode();
            result.put("versionCode", code);
        } catch (Exception e) {
            call.reject("讀不到目前版本：" + e.getMessage());
            return;
        }
        call.resolve(result);
    }

    /** Android 8+ 需要使用者逐 app 允許「安裝未知應用程式」，宣告權限不等於拿到。 */
    @PluginMethod
    public void canInstall(PluginCall call) {
        boolean allowed = Build.VERSION.SDK_INT < Build.VERSION_CODES.O
            || getContext().getPackageManager().canRequestPackageInstalls();
        JSObject result = new JSObject();
        result.put("allowed", allowed);
        call.resolve(result);
    }

    /** ⑤：未授權時直接把人送到該去的設定頁，不只丟一句文案。 */
    @PluginMethod
    public void openInstallSettings(PluginCall call) {
        Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
            .setData(Uri.parse("package:" + getContext().getPackageName()))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getContext().startActivity(intent);
        call.resolve();
    }

    /**
     * 下載 APK 到私有目錄。⑥：失敗一律刪掉半截檔案，不留下會被誤當成完整版的殘骸。
     */
    @PluginMethod
    public void download(PluginCall call) {
        String url = call.getString("url");
        String token = call.getString("token");
        if (url == null || token == null) {
            call.reject("download 需要 url 與 token");
            return;
        }
        File target = null;
        HttpURLConnection conn = null;
        try {
            File dir = new File(getContext().getExternalFilesDir(null), UPDATE_DIR);
            if (!dir.exists() && !dir.mkdirs()) {
                call.reject("建立下載目錄失敗");
                return;
            }
            // 舊的下載檔一律清掉：留著只會佔空間，且升級後就沒用了
            File[] stale = dir.listFiles();
            if (stale != null) {
                for (File f : stale) {
                    f.delete();
                }
            }
            target = new File(dir, "lift-log-update.apk");

            conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setRequestProperty("Authorization", "Bearer " + token);
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(60000);
            int status = conn.getResponseCode();
            if (status != 200) {
                call.reject("下載失敗（HTTP " + status + "）");
                return;
            }
            long total = conn.getContentLengthLong();

            try (InputStream in = conn.getInputStream();
                 FileOutputStream out = new FileOutputStream(target)) {
                byte[] buffer = new byte[16 * 1024];
                long written = 0;
                int read;
                while ((read = in.read(buffer)) != -1) {
                    out.write(buffer, 0, read);
                    written += read;
                    JSObject progress = new JSObject();
                    progress.put("written", written);
                    progress.put("total", total);
                    notifyListeners("downloadProgress", progress);
                }
                out.getFD().sync(); // 交給安裝器前確定真的落地
                if (total > 0 && written != total) {
                    throw new IllegalStateException("下載不完整：" + written + "/" + total);
                }
            }

            JSObject result = new JSObject();
            result.put("path", target.getAbsolutePath());
            call.resolve(result);
        } catch (Exception e) {
            if (target != null) {
                target.delete(); // ⑥：半截檔案不留
            }
            call.reject("下載失敗：" + e.getMessage());
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    /** 喚起系統安裝器。簽章不符、版本較舊等由系統自己擋並顯示原因。 */
    @PluginMethod
    public void install(PluginCall call) {
        String path = call.getString("path");
        if (path == null) {
            call.reject("install 需要 path");
            return;
        }
        File apk = new File(path);
        if (!apk.exists()) {
            call.reject("找不到下載的檔案，請重新下載");
            return;
        }
        try {
            Uri uri = FileProvider.getUriForFile(
                getContext(), getContext().getPackageName() + ".fileprovider", apk);
            Intent intent = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            call.resolve();
        } catch (Exception e) {
            call.reject("開啟安裝程式失敗：" + e.getMessage());
        }
    }
}
