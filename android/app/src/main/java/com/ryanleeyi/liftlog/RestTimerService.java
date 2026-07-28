package com.ryanleeyi.liftlog;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.CountDownTimer;
import android.os.IBinder;

import androidx.core.app.NotificationCompat;

/**
 * F63：休息倒數的前景服務——通知列常駐顯示剩餘秒數，不開 app 也看得到。
 *
 * <p>倒數在**原生層**跑（CountDownTimer），不靠 WebView 的 JS 計時器：app 一切到背景，
 * JS 計時器就會被系統節流，秒數會不準甚至停住，那這個 feature 就失去意義了。
 *
 * <p>與 F62 的分工（acceptance ⑥）：前景服務啟動時 app 端不再排本機通知，
 * 一次休息只有一則通知行為——歸零時由這則常駐通知**自己**轉成「休息結束」，不另發新的。
 */
public class RestTimerService extends Service {

    public static final String ACTION_START = "com.ryanleeyi.liftlog.REST_START";
    public static final String ACTION_STOP = "com.ryanleeyi.liftlog.REST_STOP";
    public static final String EXTRA_SECONDS = "seconds";
    /** F64：這次休息要不要同時畫浮動視窗。使用者沒開就是 false，行為與 F64 之前完全一致。 */
    public static final String EXTRA_OVERLAY = "overlay";

    private static final String CHANNEL_ID = "rest-timer";
    private static final int NOTIFICATION_ID = 2001; // 與 F62 的 1001 分開，兩者不會互相取代

    private CountDownTimer timer;

    @Override
    public IBinder onBind(Intent intent) {
        return null; // 不提供繫結：只用 startService/stopService 控制
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        final String action = intent == null ? null : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            stopTimer();
            stopForegroundCompat();
            // ③：不能只靠 stopForeground() 的副作用。倒數自然歸零時 onFinish() 已經 stopSelf()，
            // 此時再送 ACTION_STOP 會建立一個**全新的服務實例**——它從沒 startForeground() 過，
            // 對前一個實例貼出的通知毫無作用，「休息結束」就永久殘留在通知列。
            // 直接 cancel 才涵蓋兩種情況（2026-07-28 驗收抓到；提前取消的路徑原本就正常，
            // 所以我自己只測了那一條沒發現）。
            cancelNotification();
            RestOverlay.hide(this); // F64 ④：overlay 不留在螢幕上
            stopSelf();
            return START_NOT_STICKY;
        }

        int seconds = intent == null ? 0 : intent.getIntExtra(EXTRA_SECONDS, 0);
        if (seconds <= 0) {
            stopSelf();
            return START_NOT_STICKY;
        }

        ensureChannel();
        startForegroundCompat(buildNotification(seconds, false));
        // F64 ③：overlay 與通知列倒數並存——這裡只是多開一個顯示面，
        // 沒授權或使用者關掉 overlay 都不影響下面的倒數
        if (intent != null && intent.getBooleanExtra(EXTRA_OVERLAY, false)) {
            RestOverlay.show(this, seconds);
        }
        startTimer(seconds);
        // 不用 START_STICKY：休息被系統中斷後自己復活沒有意義（剩餘秒數已經不對了），
        // 而 ④「app 被殺掉不留殘影」也要求它安靜地消失
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        stopTimer();
        // F64 ④ 的第二條路徑：系統回收服務時也要收掉 overlay。
        // 與 ACTION_STOP 那條各自獨立——F63 ③ 的教訓就是只顧一條路徑會留殘影
        RestOverlay.hide(this);
        super.onDestroy();
    }

    private void startTimer(int seconds) {
        stopTimer();
        timer = new CountDownTimer(seconds * 1000L, 1000L) {
            @Override
            public void onTick(long remainingMs) {
                // 每秒更新同一則通知（相同 id ＝ 就地更新，不會堆疊）
                int remaining = (int) Math.ceil(remainingMs / 1000.0);
                notifyUpdate(buildNotification(remaining, false));
                // F64 ①：overlay 的秒數也由這裡推——WebView 在背景會被節流，畫不動
                RestOverlay.update(remaining);
            }

            @Override
            public void onFinish() {
                // ②：同一則通知轉為「休息結束」，不另發新通知
                notifyUpdate(buildNotification(0, true));
                RestOverlay.hide(RestTimerService.this); // F64 ④：休息結束 overlay 自動消失
                // 服務結束但通知留著讓使用者看得到——detach 而非 remove
                stopForegroundKeepNotification();
                stopSelf();
            }
        }.start();
    }

    private void stopTimer() {
        if (timer != null) {
            timer.cancel();
            timer = null;
        }
    }

    private Notification buildNotification(int remainingSeconds, boolean finished) {
        Intent launch = getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent contentIntent = launch == null ? null : PendingIntent.getActivity(
            this, 0, launch, PendingIntent.FLAG_IMMUTABLE);

        String title = finished ? "休息結束" : "休息中";
        String text = finished
            ? "時間到，繼續下一組！"
            : String.format("剩餘 %d:%02d", remainingSeconds / 60, remainingSeconds % 60);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle(title)
            .setContentText(text)
            .setOnlyAlertOnce(!finished) // 倒數期間不要每秒都叮一聲；結束那一下才提醒
            .setOngoing(!finished) // 倒數中不可滑掉；結束後可以
            .setAutoCancel(finished);
        if (contentIntent != null) {
            builder.setContentIntent(contentIntent);
        }
        if (finished) {
            builder.setVibrate(new long[] {200, 100, 200});
        }
        return builder.build();
    }

    private void ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return;
        NotificationChannel channel = new NotificationChannel(
            CHANNEL_ID, "休息倒數", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("訓練休息時在通知列顯示剩餘秒數");
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
    }

    private void cancelNotification() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.cancel(NOTIFICATION_ID);
    }

    private void notifyUpdate(Notification notification) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.notify(NOTIFICATION_ID, notification);
    }

    private void startForegroundCompat(Notification notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            // Android 14+ 必須指定型別，且要與 manifest 的宣告一致
            startForeground(NOTIFICATION_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    /** 停服務並移除通知（③：不留殘影）。 */
    private void stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(Service.STOP_FOREGROUND_REMOVE);
        } else {
            stopForeground(true);
        }
    }

    /** 停服務但留下「休息結束」那則通知，讓使用者回頭看得到。 */
    private void stopForegroundKeepNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(Service.STOP_FOREGROUND_DETACH);
        } else {
            stopForeground(false);
        }
    }

    static void start(Context context, int seconds, boolean overlay) {
        Intent intent = new Intent(context, RestTimerService.class)
            .setAction(ACTION_START)
            .putExtra(EXTRA_SECONDS, seconds)
            .putExtra(EXTRA_OVERLAY, overlay);
        context.startForegroundService(intent);
    }

    static void stop(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_STOP));
    }
}
