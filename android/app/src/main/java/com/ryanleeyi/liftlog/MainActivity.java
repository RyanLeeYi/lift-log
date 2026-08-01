package com.ryanleeyi.liftlog;

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
        // F69 ②：浮動視窗要知道 app 在不在前景。用 Activity 生命週期而非 WebView 的
        // visibilitychange——後者在 app 進背景後會被節流，正是最需要它的那一刻最不可靠
        AppForegroundTracker.register(getApplication());
        super.onCreate(savedInstanceState);
        keepRendererWarm();
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
