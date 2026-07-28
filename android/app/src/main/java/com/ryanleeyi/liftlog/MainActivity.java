package com.ryanleeyi.liftlog;

import android.os.Bundle;

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
    }
}
