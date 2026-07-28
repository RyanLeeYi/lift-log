package com.ryanleeyi.liftlog;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // F62：自寫 plugin，回答「系統層是否允許本 app 發通知」——
        // Capacitor 的 checkPermissions 在 Android 12 以下答不了這件事（見 NotifyStatusPlugin）
        registerPlugin(NotifyStatusPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
