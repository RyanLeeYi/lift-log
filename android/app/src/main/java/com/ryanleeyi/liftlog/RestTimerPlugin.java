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
        emit(action, -1);
    }

    /**
     * F103 ⑤：帶秒數的版本。
     *
     * <p>停止態的 ±15s 全發生在原生層，前端無從得知「再開始」該從幾秒重跑；
     * 只送動作名的話兩邊必然各說各話（⑤ 點名的實作風險）。負數＝這個動作沒有秒數語意。
     */
    static void emit(String action, int seconds) {
        RestTimerPlugin plugin = instance;
        if (plugin == null) return;
        JSObject data = new JSObject();
        data.put("action", action);
        if (seconds >= 0) data.put("seconds", seconds);
        plugin.notifyListeners("restControl", data);
    }

    /**
     * F127 ②：前端開機時問「有沒有哪一輪是被明確結束的，那是什麼時候」。
     *
     * <p>方向是前端取件：按下停止那一刻 Activity 已經沒了，
     * 推送必掉（F124）。回 0 代表從沒被明確結束過。
     */
    @PluginMethod
    public void getRestStoppedAt(PluginCall call) {
        JSObject result = new JSObject();
        result.put("stoppedAt", RestTimerService.stoppedAt(getContext()));
        call.resolve(result);
    }

    /**
     * F131 ①④：原生在背景開了新的一輪——前端要接手，不是自己再開一輪。
     *
     * <p>帶 {@code startedAt} 而不只是秒數：這個事件可能在 WebView 解凍後才被處理
     * （背景時整條鏈是凍住的），只給秒數的話前端會從「現在」重數，兩邊當場分叉。
     */
    static void emitNextRound(int seconds, long startedAt) {
        RestTimerPlugin plugin = instance;
        if (plugin == null) return;
        JSObject data = new JSObject();
        data.put("action", "nextround");
        data.put("seconds", seconds);
        data.put("startedAt", startedAt);
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
            boolean hasDraft = call.hasOption("weight") || call.hasOption("reps")
                || call.hasOption("exerciseId") || call.hasOption("workoutId");
            Double weight = call.getDouble("weight");
            Integer reps = call.getInt("reps");
            Integer exerciseId = call.getInt("exerciseId");
            Integer setNumber = call.getInt("setNumber");
            Integer workoutId = call.getInt("workoutId");
            if (hasDraft && (weight == null || !Double.isFinite(weight) || weight < 0
                || reps == null || reps <= 0 || exerciseId == null || exerciseId <= 0
                || setNumber == null || setNumber <= 0 || workoutId == null || workoutId <= 0)) {
                call.reject("待記組需要合法的 weight/reps/exerciseId/setNumber/workoutId");
                return;
            }
            // F104 ①：待記組沒帶就用 -1／-1，overlay 那邊據此整塊不顯示（舊版前端仍能用）
            RestTimerService.start(
                getContext(), seconds, overlay, call.getString("hint"),
                weight == null ? -1.0 : weight, reps == null ? -1 : reps,
                Boolean.TRUE.equals(call.getBoolean("bodyweight", false)),
                // F125 ③：補送時驗證歸屬用；沒帶就是 -1，補送那條路會據此判定不可信而放棄
                exerciseId == null ? -1 : exerciseId,
                setNumber == null ? -1 : setNumber,
                workoutId == null ? -1 : workoutId);
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
