package com.ryanleeyi.liftlog;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.os.Bundle;

import androidx.annotation.NonNull;

/**
 * F69 ②：回答「app 現在是不是在前景」。
 *
 * <p>為什麼不用 WebView 的 <code>visibilitychange</code>：app 一進背景 JS 就被系統節流，
 * 把「該不該顯示浮動視窗」的判斷放在一個隨時會被凍住的地方，等於這個 feature 只在運氣好的時候成立。
 * Activity 的生命週期回呼由系統直接派送，切走的當下必定觸發。
 *
 * <p>用 resumed／paused 而非 started／stopped：使用者拉下通知欄或跳出對話框時 Activity 會 pause
 * 但不會 stop，那些情境使用者也看不到 app 內的倒數，浮動視窗該冒出來。
 */
final class AppForegroundTracker implements Application.ActivityLifecycleCallbacks {

    private final Context appContext;
    private int resumedCount;

    private AppForegroundTracker(Context context) {
        this.appContext = context.getApplicationContext();
    }

    static void register(Application application) {
        application.registerActivityLifecycleCallbacks(new AppForegroundTracker(application));
    }

    @Override
    public void onActivityResumed(@NonNull Activity activity) {
        resumedCount++;
        RestOverlay.setAppForeground(appContext, true);
    }

    @Override
    public void onActivityPaused(@NonNull Activity activity) {
        resumedCount = Math.max(0, resumedCount - 1);
        if (resumedCount == 0) {
            RestOverlay.setAppForeground(appContext, false);
        }
    }

    @Override
    public void onActivityCreated(@NonNull Activity activity, Bundle savedInstanceState) {}

    @Override
    public void onActivityStarted(@NonNull Activity activity) {}

    @Override
    public void onActivityStopped(@NonNull Activity activity) {}

    @Override
    public void onActivitySaveInstanceState(@NonNull Activity activity, @NonNull Bundle outState) {}

    @Override
    public void onActivityDestroyed(@NonNull Activity activity) {}
}
