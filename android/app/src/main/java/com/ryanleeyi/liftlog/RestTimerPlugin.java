package com.ryanleeyi.liftlog;

import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

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

    /**
     * F71 ⑥：原生→前端的唯一出口。
     *
     * <p>前端訂閱 `restControl` 事件；浮動視窗按下暫停／繼續／停止時由這裡送出去。
     * 用事件而不是讓前端輪詢——app 在背景時輪詢會被節流，而「人在別的 app 裡按浮動視窗」
     * 正是最需要它可靠的那一刻。
     *
     * <p>前端不在（WebView 已被回收）時 instance 為 null，送不出去也無妨：⑦ 只要求
     * 服務與通知照常反應，畫面狀態等回到 app 再重新產生。
     */
    private static RestTimerPlugin instance;

    static void emit(String action) {
        RestTimerPlugin plugin = instance;
        if (plugin == null) return;
        JSObject data = new JSObject();
        data.put("action", action);
        plugin.notifyListeners("restControl", data);
    }

    @Override
    public void load() {
        instance = this;
    }

    @Override
    protected void handleOnDestroy() {
        if (instance == this) instance = null;
    }

    @PluginMethod
    public void pause(PluginCall call) {
        RestTimerService.pause(getContext());
        call.resolve();
    }

    @PluginMethod
    public void resume(PluginCall call) {
        RestTimerService.resume(getContext());
        call.resolve();
    }

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

    /** F64 ②：overlay 是「特殊權限」，宣告了也要使用者逐 app 手動開，前端據此顯示開關狀態。 */
    @PluginMethod
    public void overlayPermitted(PluginCall call) {
        JSObject result = new JSObject();
        result.put("granted", RestOverlay.permitted(getContext()));
        call.resolve(result);
    }

    /**
     * F64 ②：把使用者送到系統的「顯示在其他應用程式上層」授權頁。
     *
     * <p>不等待結果——這個設定頁沒有回傳值，使用者授權後回到 app 再按一次開關即可
     * （與 F62 通知授權的處置一致：不猜、以下次查詢的實際狀態為準）。
     */
    @PluginMethod
    public void requestOverlayPermission(PluginCall call) {
        try {
            Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:" + getContext().getPackageName()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
        } catch (Exception e) {
            // 少數 ROM 沒有這個設定頁：讓前端知道，文案才不會叫人去一個開不了的地方
            call.reject("開不了浮動視窗授權頁：" + e.getMessage());
            return;
        }
        call.resolve();
    }

    /**
     * F69 ③：前端在切畫面時回報「現在看不看得到 app 內的 REST 卡片」。
     *
     * <p>只有這一件事交給 JS——呼叫時 app 必然在前景、沒有節流。app 前不前景則由原生的
     * ActivityLifecycleCallbacks 判定（見 AppForegroundTracker）。
     */
    @PluginMethod
    public void setRestCardVisible(PluginCall call) {
        RestOverlay.setRestCardVisible(getContext(),
            Boolean.TRUE.equals(call.getBoolean("visible", false)));
        call.resolve();
    }

    @PluginMethod
    public void start(PluginCall call) {
        Integer seconds = call.getInt("seconds");
        if (seconds == null || seconds <= 0) {
            call.reject("start 需要正整數的 seconds");
            return;
        }
        boolean overlay = Boolean.TRUE.equals(call.getBoolean("overlay", false));
        try {
            RestTimerService.start(getContext(), seconds, overlay);
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
