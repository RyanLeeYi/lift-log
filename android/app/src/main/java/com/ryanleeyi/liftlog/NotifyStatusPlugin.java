package com.ryanleeyi.liftlog;

import android.content.Intent;
import android.provider.Settings;

import androidx.core.app.NotificationManagerCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * F62：回答「這個 app 現在真的發得出通知嗎」。
 *
 * <p>存在的理由（2026-07-28 真機抓到）：{@code LocalNotifications.checkPermissions()} 在
 * Android 13 以下**一律回 granted**——因為 POST_NOTIFICATIONS 那個執行期權限在舊版根本不存在。
 * 但使用者仍然可以在系統設定把通知關掉，此時 app 照樣排程、系統照樣把通知丟掉
 * （appops {@code POST_NOTIFICATION: ignore}），使用者收不到也看不到任何提示＝靜默失敗。
 *
 * <p>{@code areNotificationsEnabled()} 才是真正的答案，兩個 Android 版本區間都準。
 */
@CapacitorPlugin(name = "NotifyStatus")
public class NotifyStatusPlugin extends Plugin {

    @PluginMethod
    public void enabled(PluginCall call) {
        boolean on = NotificationManagerCompat.from(getContext()).areNotificationsEnabled();
        JSObject result = new JSObject();
        result.put("enabled", on);
        call.resolve(result);
    }

    /** 開啟本 app 的系統通知設定頁——⑤ 的「明確引導」不能只有一句話，要能走過去。 */
    @PluginMethod
    public void openSettings(PluginCall call) {
        Intent intent = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
        intent.putExtra(Settings.EXTRA_APP_PACKAGE, getContext().getPackageName());
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getContext().startActivity(intent);
        call.resolve();
    }
}
