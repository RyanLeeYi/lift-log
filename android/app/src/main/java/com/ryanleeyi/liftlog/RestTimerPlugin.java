package com.ryanleeyi.liftlog;

import android.os.Build;

import androidx.core.app.NotificationManagerCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * F63：前端啟停休息倒數前景服務的橋接。
 *
 * <p>`available()` 是 ⑥ 的分工判準——前端據此決定「這次休息交給前景服務」還是
 * 「退回 F62 的本機通知」，兩者不可同時發生（一次休息只有一則通知行為）。
 */
@CapacitorPlugin(name = "RestTimer")
public class RestTimerPlugin extends Plugin {

    /** 前景服務能不能用：通知被系統關掉時它啟得起來但看不到，等同不可用。 */
    @PluginMethod
    public void available(PluginCall call) {
        boolean notificationsOn = NotificationManagerCompat.from(getContext())
            .areNotificationsEnabled();
        JSObject result = new JSObject();
        // Android 8 之前沒有前景服務通知的強制要求，本專案 minSdk 24 仍可啟動
        result.put("available", notificationsOn && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O);
        call.resolve(result);
    }

    @PluginMethod
    public void start(PluginCall call) {
        Integer seconds = call.getInt("seconds");
        if (seconds == null || seconds <= 0) {
            call.reject("start 需要正整數的 seconds");
            return;
        }
        try {
            RestTimerService.start(getContext(), seconds);
            call.resolve();
        } catch (Exception e) {
            // Android 12+ 對背景啟動前景服務有限制；啟不起來要讓前端知道好退回 F62
            call.reject("啟動前景服務失敗：" + e.getMessage());
        }
    }

    @PluginMethod
    public void stop(PluginCall call) {
        try {
            RestTimerService.stop(getContext());
        } catch (Exception e) {
            /* 服務本來就沒在跑：停不掉不是問題 */
        }
        call.resolve();
    }
}
