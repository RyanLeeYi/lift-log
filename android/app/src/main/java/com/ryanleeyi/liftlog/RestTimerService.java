package com.ryanleeyi.liftlog;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.CountDownTimer;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;

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
    /** F89 ③：浮動視窗要顯示的「動作名 · 第 N 組」。純顯示用，服務自己不解讀。 */
    public static final String EXTRA_HINT = "hint";
    /** F71 ②：暫停與繼續。倒數凍結、通知改成暫停樣式，到點提醒不觸發。 */
    public static final String ACTION_PAUSE = "com.ryanleeyi.liftlog.REST_PAUSE";
    public static final String ACTION_RESUME = "com.ryanleeyi.liftlog.REST_RESUME";
    /** F89 ④：浮動視窗的 ±15s。原生自己調，不能繞前端——人在別的 app 裡時 WebView 被節流。 */
    public static final String ACTION_ADJUST = "com.ryanleeyi.liftlog.REST_ADJUST";

    /**
     * F100：停止鈴聲並歸位，但**服務與視窗都留著**。
     *
     * <p>與 {@link #ACTION_STOP} 的差別是這條不結束這輪——人可能還在別的 app 裡，
     * 需要一條「先安靜下來，等我回去記下一組」的路。真正的結束仍走 ACTION_STOP
     * （浮動視窗的 ✕、記下一組開新的休息、結束訓練）。
     */
    public static final String ACTION_HALT = "com.ryanleeyi.liftlog.REST_HALT";
    /**
     * F72 ⑤：通知列上的「停止」動作鈕。
     *
     * <p>與 ACTION_STOP 分開的理由：那條是**前端按了停止之後**送進來的，服務不必再回頭通知前端；
     * 這條是使用者直接在通知列按的，前端還不知道，必須回送 restControl 事件讓畫面跟上。
     */
    public static final String ACTION_STOP_FROM_NOTIFICATION =
        "com.ryanleeyi.liftlog.REST_STOP_FROM_NOTIFICATION";

    private static final String CHANNEL_ID = "rest-timer";
    private static final int NOTIFICATION_ID = 2001; // 與 F62 的 1001 分開，兩者不會互相取代

    private CountDownTimer timer;
    private int remainingSeconds; // 目前剩餘秒數——暫停時要記住，繼續時從這裡接續
    private boolean paused;
    /** F72 ①②：歸零之後的階段——服務繼續活著、秒數往負的走、鬧鐘一直響。 */
    private boolean overtime;
    /** F100：這輪原本設定的秒數——停止後要歸回這個值，不是歸 0。 */
    private int targetSeconds;
    /** F100：已停止但視窗還在（不倒數、不響、暫停不可按）。 */
    private boolean halted;
    private final Handler overtimeTicker = new Handler(Looper.getMainLooper());
    private MediaPlayer alarmPlayer;

    @Override
    public IBinder onBind(Intent intent) {
        return null; // 不提供繫結：只用 startService/stopService 控制
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        final String action = intent == null ? null : intent.getAction();
        if (ACTION_STOP.equals(action) || ACTION_STOP_FROM_NOTIFICATION.equals(action)) {
            // ⑤：從通知列按的要回送事件讓前端跟上；前端自己按的不必回送（它已經停了）
            if (ACTION_STOP_FROM_NOTIFICATION.equals(action)) RestTimerPlugin.emit("stop");
            stopAlarm(); // ④⑦：三條停止路徑都必須真的把聲音與震動關掉
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

        if (ACTION_HALT.equals(action)) {
            // ① 停鈴、歸回這輪原本設定的秒數（不是 0、也不繼續往上數），視窗留著不再倒數
            stopAlarm();
            stopTimer();
            overtime = false;
            paused = false;
            halted = true;
            remainingSeconds = targetSeconds;
            // ⑤ 前景服務要繼續活著（視窗撐不住就沒得留），但通知列不得留一則還在倒數的假通知
            notifyUpdate(buildNotification(targetSeconds, false));
            RestOverlay.setHalted(this, true, targetSeconds);
            // ⚠ 這裡**不能**送 "stop"：前端收到 stop 會走 cancelRestNotify() →
            // stopForegroundRest() → ACTION_STOP，把服務與視窗一起關掉，
            // 剛好抵銷掉本條要的「視窗留著」（2026-07-31 真機第一版實測就是這樣消失的）。
            // 另開一個事件，前端只停自己那份倒數、不回送任何原生指令。
            RestTimerPlugin.emit("halt");
            return START_NOT_STICKY;
        }

        if (ACTION_PAUSE.equals(action)) {
            if (halted) return START_NOT_STICKY; // ② 沒有在跑的倒數可暫停
            // 只停計時器，服務與通知都留著——使用者要看得到「暫停中，剩餘 X」
            stopTimer();
            paused = true;
            RestOverlay.setPaused(this, true);
            notifyUpdate(buildNotification(remainingSeconds, false));
            return START_NOT_STICKY;
        }

        if (ACTION_RESUME.equals(action)) {
            paused = false;
            RestOverlay.setPaused(this, false);
            startTimer(remainingSeconds); // ②：從剩餘秒數接續，不重頭算
            return START_NOT_STICKY;
        }

        if (intent != null && ACTION_ADJUST.equals(intent.getAction())) {
            // 下限 1 秒：調到 0 或負數等於「立刻超時」，那是停止鈕的語意，不是 −15s 的
            int delta = intent.getIntExtra(EXTRA_SECONDS, 0);
            remainingSeconds = Math.max(1, remainingSeconds + delta);
            // F100 ②：停止後 ±15s 仍可按，但調的是**顯示的秒數**——不重新開始倒數。
            // 要重新倒數就是回 app 記下一組（那會開一輪新的休息）。
            if (!paused && !halted) startTimer(remainingSeconds);
            notifyUpdate(buildNotification(remainingSeconds, false));
            RestOverlay.update(this, remainingSeconds);
            RestTimerPlugin.emit(delta > 0 ? "plus15" : "minus15");
            return START_NOT_STICKY;
        }

        int seconds = intent == null ? 0 : intent.getIntExtra(EXTRA_SECONDS, 0);
        if (seconds <= 0) {
            stopSelf();
            return START_NOT_STICKY;
        }

        ensureChannel();
        paused = false;
        halted = false; // F100：新的一輪；上一輪停在哪裡跟這輪無關
        remainingSeconds = seconds;
        // F100 ②：調整值不外溢到下一輪——targetSeconds 每輪由啟動的 intent 重設，
        // 下一輪的長度仍照課表的參考休息
        targetSeconds = seconds;
        startForegroundCompat(buildNotification(seconds, false));
        // F64 ③：overlay 與通知列倒數並存——這裡只是多開一個顯示面，
        // 沒授權或使用者關掉 overlay 都不影響下面的倒數
        if (intent != null && intent.getBooleanExtra(EXTRA_OVERLAY, false)) {
            // F69：這裡只宣告「這輪休息要顯示 overlay」，真的畫不畫由 RestOverlay 的
            // shouldShow() 決定（app 在前景又看得到 REST 卡片時就先藏著）
            RestOverlay.setActive(this, true, seconds, intent.getStringExtra(EXTRA_HINT));
        }
        startTimer(seconds);
        // 不用 START_STICKY：休息被系統中斷後自己復活沒有意義（剩餘秒數已經不對了），
        // 而 ④「app 被殺掉不留殘影」也要求它安靜地消失
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        stopAlarm(); // ⑦：服務被系統回收時聲音與震動一起收乾淨
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
                remainingSeconds = remaining;
                notifyUpdate(buildNotification(remaining, false));
                // F64 ①：overlay 的秒數也由這裡推——WebView 在背景會被節流，畫不動
                RestOverlay.update(RestTimerService.this, remaining);
            }

            @Override
            public void onFinish() {
                // F72 ①②⑦：歸零**不是結束**——服務繼續活著、秒數往負的走、鬧鐘開始響。
                // F64 ④ 的「歸零後 overlay 自動消失」由 F72 ① 取代；服務停止／app 被殺
                // 時仍要收乾淨，那部分沒變。
                remainingSeconds = 0;
                overtime = true;
                startAlarm();
                startOvertimeTicker();
            }
        }.start();
    }

    private void stopTimer() {
        if (timer != null) {
            timer.cancel();
            timer = null;
        }
        overtime = false;
        overtimeTicker.removeCallbacksAndMessages(null);
    }

    /** F72 ①②：歸零後每秒往上數，通知與 overlay 一起顯示超時值。 */
    private void startOvertimeTicker() {
        overtimeTicker.removeCallbacksAndMessages(null);
        overtimeTicker.post(new Runnable() {
            @Override
            public void run() {
                if (!overtime) return;
                notifyUpdate(buildNotification(remainingSeconds, true));
                RestOverlay.update(RestTimerService.this, -remainingSeconds);
                remainingSeconds += 1;
                overtimeTicker.postDelayed(this, 1000L);
            }
        });
    }

    /**
     * F72 ③：鬧鐘音量循環播放 ＋ 重複震動，**不自動停止**（簽核時明確選擇不設上限）。
     *
     * <p>用 MediaPlayer 而不是通知音：通知的聲音只響一次，而這裡要的是「響到你理它為止」。
     * USAGE_ALARM 讓手機靜音／勿擾時仍聽得到——健身房戴耳機時那是唯一會被聽見的通道。
     */
    private void startAlarm() {
        stopAlarm();
        try {
            Uri uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
            if (uri == null) uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
            alarmPlayer = new MediaPlayer();
            alarmPlayer.setAudioAttributes(new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build());
            alarmPlayer.setDataSource(this, uri);
            alarmPlayer.setLooping(true);
            alarmPlayer.prepare();
            alarmPlayer.start();
        } catch (Exception e) {
            // 沒有鈴聲或裝置不支援：震動仍要照響，不能整個提醒都沒了
            releasePlayer();
        }
        Vibrator vibrator = vibrator();
        if (vibrator != null && vibrator.hasVibrator()) {
            long[] pattern = {0, 600, 400};
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                // repeat=0：從陣列開頭無限重複，直到 cancel()
                vibrator.vibrate(VibrationEffect.createWaveform(pattern, 0));
            } else {
                vibrator.vibrate(pattern, 0);
            }
        }
    }

    /** ④⑦：停聲音與震動。每一條離場路徑都要呼叫——沒有 app 卻一直響是最糟的失敗。 */
    private void stopAlarm() {
        releasePlayer();
        Vibrator vibrator = vibrator();
        if (vibrator != null) vibrator.cancel();
    }

    private void releasePlayer() {
        if (alarmPlayer == null) return;
        try {
            alarmPlayer.stop();
        } catch (Exception e) {
            /* 還沒開始播：直接釋放即可 */
        }
        alarmPlayer.release();
        alarmPlayer = null;
    }

    private Vibrator vibrator() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            VibratorManager manager = getSystemService(VibratorManager.class);
            return manager == null ? null : manager.getDefaultVibrator();
        }
        return (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
    }

    private Notification buildNotification(int remainingSeconds, boolean finished) {
        Intent launch = getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent contentIntent = launch == null ? null : PendingIntent.getActivity(
            this, 0, launch, PendingIntent.FLAG_IMMUTABLE);

        // F100 ⑤：已停止時不得留一則還在倒數的假通知——服務還活著（視窗要靠它撐），
        // 但那一則必須誠實說出「已經停了」，否則使用者以為倒數還在跑。
        String title = finished
            ? "休息結束"
            : halted ? "休息已停止" : (paused ? "休息暫停" : "休息中");
        // F72 ②：歸零後不停在一句話——繼續顯示超時秒數，與 app 內卡片一致
        String text;
        if (finished) {
            text = String.format("時間到！超時 %d:%02d", remainingSeconds / 60, remainingSeconds % 60);
        } else if (halted) {
            text = String.format("已停止・%d:%02d｜點此回 app 記下一組",
                remainingSeconds / 60, remainingSeconds % 60);
        } else {
            text = String.format(paused ? "已暫停・剩餘 %d:%02d" : "剩餘 %d:%02d",
                remainingSeconds / 60, remainingSeconds % 60);
        }

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
            // F72 ⑤：提醒不會自己停，所以通知列一定要有能直接關掉的鈕——
            // 否則使用者非得解鎖開 app 才停得下來
            Intent stopIntent = new Intent(this, RestTimerService.class)
                .setAction(ACTION_STOP_FROM_NOTIFICATION);
            PendingIntent stopPending = PendingIntent.getService(
                this, 1, stopIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            builder.addAction(android.R.drawable.ic_lock_idle_alarm, "停止", stopPending);
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

    // F63 曾用 stopForegroundKeepNotification()（DETACH）在歸零時停服務、留下通知。
    // F72 之後歸零**不再結束服務**（要繼續計時與持續提醒），那個方法沒有呼叫點了，故移除——
    // 留著會讓下一個人以為還有這條路徑。

    static void start(Context context, int seconds, boolean overlay, String hint) {
        Intent intent = new Intent(context, RestTimerService.class)
            .setAction(ACTION_START)
            .putExtra(EXTRA_SECONDS, seconds)
            .putExtra(EXTRA_OVERLAY, overlay)
            .putExtra(EXTRA_HINT, hint == null ? "" : hint);
        context.startForegroundService(intent);
    }

    static void adjust(Context context, int deltaSeconds) {
        Intent intent = new Intent(context, RestTimerService.class)
            .setAction(ACTION_ADJUST)
            .putExtra(EXTRA_SECONDS, deltaSeconds);
        context.startService(intent);
    }

    /** F100：停止鈴聲並歸位，視窗與服務都留著。浮動視窗的停止鈕走這條，不走 stop()。 */
    static void halt(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_HALT));
    }

    static void pause(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_PAUSE));
    }

    static void resume(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_RESUME));
    }

    static void stop(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_STOP));
    }
}
