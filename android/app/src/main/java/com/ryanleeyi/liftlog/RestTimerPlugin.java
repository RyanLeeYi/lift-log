package com.ryanleeyi.liftlog;

import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

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

    /** F104-A 的量測標籤（`adb logcat -s F104probe`）。留在正式碼裡不輸出使用者資料，只有時間戳。 */
    private static final String PROBE = "F104probe";

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
     * F104 ③：浮動視窗按了「記下這組」——把視窗上的數值送給前端。
     *
     * <p>秒數與待記組分開帶：硬擠進同一個欄位會讓每個接收端都要先猜這次是哪一種。
     */
    static void emitLog(double weight, int reps, String uuid) {
        RestTimerPlugin plugin = instance;
        // F104-A 量測：要分辨「事件送不出去」與「事件送出去了但 JS 沒跑」。
        // 前者 instance 為 null（WebView 已被回收），後者 instance 在但 logResult 遲遲不回來。
        Log.i(PROBE, "emitLog t=" + System.currentTimeMillis() + " pluginNull=" + (plugin == null));
        if (plugin == null) return;
        JSObject data = new JSObject();
        data.put("action", "logset");
        data.put("weight", weight);
        data.put("reps", reps);
        // F125 ④：uuid 由原生在**排入的那一刻**生成，這條 bridge 事件與開機補送帶同一個值。
        // 少了它，兩條路會各自產生一筆，伺服器的冪等去重形同虛設。
        if (uuid != null) data.put("uuid", uuid);
        plugin.notifyListeners("restControl", data);
    }

    /**
     * F125 ③：開機時前端主動**取件**（而不是原生推送）。
     *
     * <p>推送在這個時機一定會掉：`notifyListeners` 不暫存，而 app 剛起來時前端的
     * `subscribeRestControl()` 還沒跑。所以補送的方向必須反過來——由前端在啟動流程裡問一次。
     * （同一個坑的一般化版本記在 F124。）
     *
     * <p>取件**不清除**。清除要等前端回報寫入成功（⑤），否則補送失敗就再也沒有第二次機會。
     */
    @PluginMethod
    public void getPendingLog(PluginCall call) {
        JSObject result = new JSObject();
        if (!PendingLog.has(getContext())) {
            result.put("pending", false);
            call.resolve(result);
            return;
        }
        result.put("pending", true);
        result.put("uuid", PendingLog.uuid(getContext()));
        result.put("weight", PendingLog.weight(getContext()));
        result.put("reps", PendingLog.reps(getContext()));
        result.put("bodyweight", PendingLog.bodyweight(getContext()));
        result.put("exerciseId", PendingLog.exerciseId(getContext()));
        result.put("setNumber", PendingLog.setNumber(getContext()));
        result.put("workoutId", PendingLog.workoutId(getContext()));
        call.resolve(result);
    }

    /** F125 ⑤：前端確認那一組已經進資料庫（或已判定不該再補）之後才清。 */
    @PluginMethod
    public void clearPendingLog(PluginCall call) {
        PendingLog.clear(getContext());
        call.resolve();
    }

    /**
     * F104 ⑤：前端回報就地記錄的結果。
     *
     * <p>沒有這個回報，視窗只能猜——而 ⑤ 明訂「不得表現得像成功、不得靜默吞掉」。
     * 逾時（3 秒）沒等到就當作沒記到，由 RestOverlay 那邊的門檻處理。
     */
    @PluginMethod
    public void logResult(PluginCall call) {
        Log.i(PROBE, "logResult t=" + System.currentTimeMillis()
            + " ok=" + Boolean.TRUE.equals(call.getBoolean("ok", false)));
        RestOverlay.onLogResult(getContext(), Boolean.TRUE.equals(call.getBoolean("ok", false)));
        call.resolve();
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
            // F104 ①：待記組沒帶就用 -1／-1，overlay 那邊據此整塊不顯示（舊版前端仍能用）
            RestTimerService.start(
                getContext(), seconds, overlay, call.getString("hint"),
                call.getDouble("weight", -1.0), call.getInt("reps", -1),
                Boolean.TRUE.equals(call.getBoolean("bodyweight", false)),
                // F125 ③：補送時驗證歸屬用；沒帶就是 -1，補送那條路會據此判定不可信而放棄
                call.getInt("exerciseId", -1), call.getInt("setNumber", -1),
                call.getInt("workoutId", -1));
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
