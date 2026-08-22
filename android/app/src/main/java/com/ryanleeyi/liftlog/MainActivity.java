package com.ryanleeyi.liftlog;

import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.webkit.WebView;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // F62：自寫 plugin，回答「系統層是否允許本 app 發通知」——
        // Capacitor 的 checkPermissions 在 Android 12 以下答不了這件事（見 NotifyStatusPlugin）
        registerPlugin(NotifyStatusPlugin.class);
        // F67：自我更新（查版本、下載 APK、喚起系統安裝器）
        registerPlugin(AppUpdatePlugin.class);
        // F63：休息倒數前景服務（通知列常駐顯示剩餘秒數）
        registerPlugin(RestTimerPlugin.class);
        // F139：Android domain 資料與同步 outbox 的唯一原生 SQLite bridge。
        registerPlugin(LocalStorePlugin.class);
        // F141：Google Credential Manager 與 Keystore-backed rotating session bridge。
        registerPlugin(AuthSessionPlugin.class);
        registerPlugin(SyncPlugin.class);
        SyncScheduler.initialize(getApplication());
        // F69 ②：浮動視窗要知道 app 在不在前景。用 Activity 生命週期而非 WebView 的
        // visibilitychange——後者在 app 進背景後會被節流，正是最需要它的那一刻最不可靠
        AppForegroundTracker.register(getApplication());
        super.onCreate(savedInstanceState);
        keepRendererWarm();
        // F124 ⑥：延後派送到位後，onCreate 也走同一組 handler。
        //
        // 先前這裡**刻意不**處理（2026-08-03 Codex review P2）：onCreate 跑在 WebView 載完、
        // 前端 subscribeRestControl() 之前，emit() 不暫存事件 → focus 與 stop 會被丟掉，
        // 而原生這半已經停了 → 前端從 F66 的快照還原出一輪「原生已經不存在」的休息。
        // 現在 emit() 一律 retainUntilConsumed（①），而前端把訂閱時機移到還原之後（④），
        // 這兩個事件會在快照還原完成之後、依 focus→stop 的原順序送達。
        handleBackToApp(getIntent());
        handleFocusRest(getIntent());
    }

    /**
     * F123 ④：heads-up 的「回到 app」＝**停止這輪 ＋ 跳回所屬動作的計時頁**。
     *
     * <p>launchMode 是 singleTask，而 heads-up 只在 app 前景時存在（F123 ③），
     * 所以多數情況走到這裡時 Activity 是活著的；F124 ⑥ 起 onCreate 也掛（冷啟動那一瞬）。
     *
     * <p>⚠ 與浮動視窗上的「回 app 記下一組」**不是**同一件事——那顆不結束這輪（F103 ①）。
     * 這裡刻意不呼叫那條路徑，而是組合兩個既有事件：**先 focus 導頁、再 stop**。
     *
     * <p>⚠ 順序反過來會靜默失效（2026-08-03 真機抓到）：`stopRestTimer()` 在**真的結束**這輪時
     * 會把 `state.restExerciseId` 清成 null（只有浮動視窗那條 `keepForegroundService` 的停止才保留），
     * 而 `focusRestExercise()` 正是靠它決定要去哪一頁——先 stop 的話 focus 直接 early-return，
     * 結果是「停了但沒跳頁」。
     */
    private void handleBackToApp(Intent intent) {
        if (intent == null || !intent.getBooleanExtra(RestTimerService.EXTRA_BACK_TO_APP, false)) {
            return;
        }
        intent.removeExtra(RestTimerService.EXTRA_BACK_TO_APP); // 只作用一次，不要在重建時重播
        RestTimerService.stop(this);
        RestTimerPlugin.emit("focus"); // 先導頁——它要讀 restExerciseId
        RestTimerPlugin.emit("stop"); // 再結束這輪（會把 restExerciseId 清掉）
    }

    /**
     * F126 ①②③：**倒數中**那則通知的「回到 app」——只導頁，**這輪繼續跑**。
     *
     * <p>與 {@link #handleBackToApp} 是相反的語意，所以是兩條路徑、兩個 extra。
     * 這裡**只**送 focus：不碰服務、不送 stop。F103 ① 明訂導頁不是結束這輪的入口。
     *
     * <p>F124 ⑥ 起與 handleBackToApp 一樣兩邊都掛。原本只掛 onNewIntent 時，
     * 「Activity 已被銷毀、服務還活著」的冷啟動會只把 app 拉到前景卻沒導到計時頁。
     */
    private void handleFocusRest(Intent intent) {
        if (intent == null || !intent.getBooleanExtra(RestTimerService.EXTRA_FOCUS_REST, false)) {
            return;
        }
        intent.removeExtra(RestTimerService.EXTRA_FOCUS_REST);
        RestTimerPlugin.emit("focus");
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleBackToApp(intent);
        handleFocusRest(intent);
    }

    /**
     * F104-A：休息進行中時**不讓 WebView 停下來**。
     *
     * <p>問題：浮動視窗按「完成這組」時 app 在背景，事件送得到 JS，但整條鏈（寫入 → 回報 →
     * 開新的一輪）要等使用者回到前景才執行——2026-08-01 真機量到新一輪的起算時間就是回前景那一刻。
     * 視窗因此在 3 秒門檻觸發時顯示「沒記到」，儘管那組其實記進去了。
     *
     * <p>⚠ 先前的誤判：量到 app 行程在背景仍是 oom_adj 200（perceptible ＋ 前景服務）就推論
     * 「WebView 會活著」。**行程活著 ≠ renderer 沒被暫停**，那是兩件事。
     *
     * <p>做法：Activity 進背景後，若這輪休息還在跑（{@link RestTimerService#isSessionActive()}），
     * 就把 WebView 與 JS 計時器叫回來。只在休息期間這麼做——那是前景服務本來就在跑、
     * 電力預算已經付出去的一段時間；沒有休息時照常讓系統凍結它。
     */
    @Override
    public void onPause() {
        super.onPause(); // Capacitor 在這裡處理 bridge 的暫停
        resumeWebViewIfResting();
    }

    @Override
    public void onStop() {
        super.onStop();
        resumeWebViewIfResting();
    }

    private void resumeWebViewIfResting() {
        if (!RestTimerService.isSessionActive()) return;
        WebView webView = getBridge() == null ? null : getBridge().getWebView();
        if (webView == null) return;
        // onResume() 解除本 WebView 的暫停；resumeTimers() 是**行程層**的開關，
        // 兩個都要——只叫其中一個，JS 計時器仍然停著。
        webView.onResume();
        webView.resumeTimers();
    }

    /**
     * F104-A：不要在 WebView 看不見時把 renderer 降級。
     *
     * <p>預設 `waivedWhenNotVisible = true`——畫面看不到就把 renderer 的優先度讓掉，
     * 記憶體一緊就是第一個被回收的。休息期間我們需要它活著才能就地記錄。
     */
    private void keepRendererWarm() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        WebView webView = getBridge() == null ? null : getBridge().getWebView();
        if (webView == null) return;
        webView.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false);
    }
}
