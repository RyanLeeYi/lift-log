package com.ryanleeyi.liftlog;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
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
    /** F127：純計時 UI 狀態，與 F140 LocalStore domain 資料分開。 */
    private static final String STATE_PREFS = "liftlog_rest_state";
    private static final String KEY_STOPPED_AT = "stopped_at";
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
     * F103 ③：停止之後的「再開始」——從目前顯示的秒數重新倒數。
     *
     * <p>⚠ **F116 之後這條路已經沒有 UI 入口**：浮動視窗改成兩態，
     * 「停止」直接回就緒態、「完成這組」跟著回來，那顆鈕已拿掉。
     * 服務端與前端的處理都留著（verify_f103 仍在驗），但現在只有測試叫得到。
     * 下一個碰到這裡的人：要麼給它新的入口，要麼連同測試一起刪。
     */
    public static final String ACTION_RESTART = "com.ryanleeyi.liftlog.REST_RESTART";
    /** F131 ①：背景記完一組後當場開新的一輪（秒數回到這輪原本的 targetSeconds）。 */
    public static final String ACTION_NEXT_ROUND = "com.ryanleeyi.liftlog.REST_NEXT_ROUND";
    /** F104 ①：待記組——這輪休息結束後要記的那一組。服務不解讀，只是搬給 overlay。 */
    public static final String EXTRA_WEIGHT = "weight";
    public static final String EXTRA_REPS = "reps";
    /** 待記組是次數型還是時間型——決定 EXTRA_REPS 那個數字最終寫進哪個欄位。 */
    public static final String EXTRA_MODE = "mode";
    public static final String EXTRA_BODYWEIGHT = "bodyweight";
    /** F125 ③：補送時驗證歸屬用——這一組要記在哪個動作、第幾組。服務不解讀，只搬給 overlay。 */
    public static final String EXTRA_EXERCISE_ID = "exerciseId";
    public static final String EXTRA_SET_NUMBER = "setNumber";
    /** F125 ③：補送最關鍵的驗證——這一組屬於哪一場訓練。跨場寫入是唯一真正糟的失敗。 */
    public static final String EXTRA_WORKOUT_ID = "workoutId";
    /**
     * F72 ⑤：通知列上的「停止」動作鈕。
     *
     * <p>與 ACTION_STOP 分開的理由：那條是**前端按了停止之後**送進來的，服務不必再回頭通知前端；
     * 這條是使用者直接在通知列按的，前端還不知道，必須回送 restControl 事件讓畫面跟上。
     */
    public static final String ACTION_STOP_FROM_NOTIFICATION =
        "com.ryanleeyi.liftlog.REST_STOP_FROM_NOTIFICATION";

    /**
     * F123 ④：heads-up 的「回到 app」＝**停止 ＋ 跳回所屬動作的計時頁**。
     *
     * <p>⚠ 語意與浮動視窗上的「回 app 記下一組」**相反**（那顆按 F103 ① 明訂不結束這輪）。
     * 兩顆鈕各自只出現在自己的介面上，路徑刻意不共用：這條走 Activity intent
     * （順便收起通知欄、把 app 帶到最前），由 MainActivity 收下後才停這輪。
     */
    public static final String EXTRA_BACK_TO_APP = "com.ryanleeyi.liftlog.BACK_TO_APP";

    /**
     * F126 ②：**倒數中**那則通知的「回到 app」＝**只導頁，不停倒數**。
     *
     * <p>⚠ 與 {@link #EXTRA_BACK_TO_APP} 同名不同義——那顆（時間到的 heads-up）會停這輪。
     * 兩者刻意分成兩個 extra：共用一條路徑的話，改其中一邊的行為必然波及另一邊，
     * 而它們正好是相反的語意。
     */
    public static final String EXTRA_FOCUS_REST = "com.ryanleeyi.liftlog.FOCUS_REST";

    private static final String CHANNEL_ID = "rest-timer";
    /**
     * F123 ⑤：「時間到」專用的高重要度頻道。
     *
     * <p>倒數那則**必須**留在 LOW 頻道——同一個頻道就等於每秒更新秒數都從上方彈一次。
     * 頻道重要度建立後就由使用者掌控（系統不允許程式調高），所以只能另開一個，不能改舊的。
     */
    private static final String ALARM_CHANNEL_ID = "rest-alarm";
    private static final int NOTIFICATION_ID = 2001; // 與 F62 的 1001 分開，兩者不會互相取代
    /** F123 ③：heads-up 是**另一則**通知，不是把 2001 改頻道——已貼出的通知換不了頻道。 */
    private static final int ALARM_NOTIFICATION_ID = 2003;

    private CountDownTimer timer;
    private int remainingSeconds; // 目前剩餘秒數——暫停時要記住，繼續時從這裡接續
    private boolean paused;
    /** F72 ①②：歸零之後的階段——服務繼續活著、秒數往負的走、鬧鐘一直響。 */
    private boolean overtime;
    /** F100：這輪原本設定的秒數——停止後要歸回這個值，不是歸 0。 */
    private int targetSeconds;
    /** F100：已停止但視窗還在（不倒數、不響、暫停不可按）。 */
    private boolean halted;
    /**
     * F104-A：這輪休息還在不在（給 MainActivity 判斷要不要讓 WebView 保持可執行）。
     *
     * <p>static 是刻意的：判斷點在 Activity 的生命週期回呼裡，那時拿不到服務實例。
     * 只在 onCreate／onDestroy 兩處寫，語意單純。
     */
    private static volatile boolean sessionActive;

    /**
     * F123 ③：這一輪正在響鈴（歸零之後）。
     *
     * <p>static 的理由與 sessionActive 相同：換手的觸發點在 RestOverlay 的旗標變動處，
     * 那裡拿不到服務實例。只在 onFinish／停止路徑寫。
     */
    private static volatile boolean alarming;
    /** F123 ③：heads-up 上要顯示「動作名 · 第 N 組」，來源與浮動視窗同一個 EXTRA_HINT。 */
    private static volatile String alarmHint = "";

    /**
     * F131：這一輪已經休息幾秒（給原生寫入路徑填 `rest_seconds`）。
     *
     * <p>過去這個值只存在於前端（`state.pendingRestSeconds`），因為寫入一律由 JS 執行。
     * F131 讓原生自己寫，不在這裡補上就等於讓 F129 剛保住的欄位回歸成 null。
     *
     * <p><b>由 tick 累加，不從 targetSeconds - remaining 推算</b>（codex review P1）：
     * ±15s 會同時改動 remainingSeconds 與 targetSeconds 的關係，推算法會把已休息秒數
     * 重設或多算 15 秒，而那個值會被寫進 `rest_seconds`——訓練資料直接錯。
     * 累加同時解決暫停：暫停時 timer 已取消、tick 不跑，秒數自然不動。
     */
    private static volatile int elapsedSeconds;

    /** F131：這一輪開始的時刻（epoch ms）。前端回前景時據此接手同一輪，不從「現在」重數。 */
    private static volatile long roundStartedAt;

    /** F131：這一輪已休息的秒數；沒有進行中的輪次時回 -1（呼叫端據此不送 rest_seconds）。 */
    static int elapsedSeconds() {
        return sessionActive ? elapsedSeconds : -1;
    }

    /** F104-A：休息輪是否進行中。Activity 用它決定要不要保持 WebView 可執行。 */
    static boolean isSessionActive() {
        return sessionActive;
    }
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
            // F125 ⑤：這輪被**使用者明確結束**（✕、停止、結束訓練）→ 待記組作廢。
            // ⚠ 刻意只掛在這條路，**不放 onDestroy()**：系統低記憶體回收服務時也會走那裡，
            // 而那正是最需要保住待記組的時刻，清掉等於把這條 feature 的存在理由刪掉。
            //
            // F140：組在按下完成時已交易式寫入 LocalStore；停止只處理計時 UI。
            // F127 ①②：把「這輪被明確結束」寫成跨行程都看得到的事實。
            // Activity 已被銷毀時上面那個 emit("stop") 會靜靜地掉，前端的休息快照留在
            // localStorage，下次開 app 就被 resumeRestAfterRestore() 重建成一輪殭屍倒數。
            markStopped(this);
            sessionActive = false; // F104-A：這輪結束了
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
            RestTimerPlugin.emit("halt", targetSeconds);
            return START_NOT_STICKY;
        }

        if (ACTION_NEXT_ROUND.equals(action)) {
            // F131 ①：那一組已經落地（至少已進 outbox，不會再被弄丟）→ 當場開新的一輪。
            // 與 ACTION_RESTART 的差別：那條是「停止態的再開始」，從剩餘秒數接續；
            // 這條是**新的一輪**，回到這輪原本設定的秒數（F100 ② 的語意：調整值不外溢）。
            stopAlarm();
            halted = false;
            paused = false;
            overtime = false;
            remainingSeconds = targetSeconds;
            elapsedSeconds = 0;
            roundStartedAt = System.currentTimeMillis();
            startTimer(targetSeconds);
            notifyUpdate(buildNotification(targetSeconds, false));
            RestOverlay.setHalted(this, false, targetSeconds);
            RestOverlay.advanceDraftSetNumber(); // 新的一輪＝下一組，組號 +1
            // 前端要據此接手這一輪，而不是自己再開一輪（兩個各數各的是 F128 ④ 點名的坑）。
            // ⚠ 帶**開始時刻**而不只是秒數（codex review P1）：WebView 在背景是凍住的，
            // 這個事件可能 30 秒後才被處理；只給秒數的話前端會從「現在」重數，兩邊當場分叉。
            RestTimerPlugin.emitNextRound(targetSeconds, roundStartedAt);
            return START_NOT_STICKY;
        }

        if (ACTION_RESTART.equals(action)) {
            // ③ 從**目前顯示的秒數**重新倒數。停止態的 ±15s 調的就是這個值，
            // 所以「調完再開始」才有意義（F100 ② 把 ±15s 留在停止態，就是為了這個）。
            if (!halted) return START_NOT_STICKY; // 沒停止就沒有「再開始」可言
            halted = false;
            paused = false;
            overtime = false;
            startTimer(remainingSeconds);
            notifyUpdate(buildNotification(remainingSeconds, false));
            RestOverlay.setHalted(this, false, remainingSeconds);
            // ⑤ 秒數一起送——前端要據此把自己那份倒數對上來，而且**不得**回送任何原生指令
            // （回送會再啟動一次服務，同一輪被啟動兩次、秒數互相覆蓋）
            RestTimerPlugin.emit("restart", remainingSeconds);
            return START_NOT_STICKY;
        }

        if (ACTION_PAUSE.equals(action)) {
            if (halted) return START_NOT_STICKY; // ② 沒有在跑的倒數可暫停
            // 只停計時器，服務與通知都留著——使用者要看得到「暫停中，剩餘 X」
            // 超時中暫停要記得自己是超時：stopTimer() 會清 overtime，但此時
            // remainingSeconds 存的是「已超時幾秒」，resume 拿它當剩餘秒數開新倒數
            // 就會與 REST 卡片分岔（F89 真機驗收抓到的 P1）。
            boolean wasOvertime = overtime;
            stopTimer();
            overtime = wasOvertime;
            paused = true;
            RestOverlay.setPaused(this, true);
            notifyUpdate(buildNotification(remainingSeconds, overtime));
            return START_NOT_STICKY;
        }

        if (ACTION_RESUME.equals(action)) {
            paused = false;
            RestOverlay.setPaused(this, false);
            if (overtime) {
                // 從凍結的超時秒數接續往上數；鬧鐘不重響（使用者已在操作視窗）
                startOvertimeTicker();
            } else {
                startTimer(remainingSeconds); // ②：從剩餘秒數接續，不重頭算
            }
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
            // F103 ⑥：帶上調完的剩餘秒數。前端在此之前**根本沒有處理**這兩個事件，
            // 所以在視窗調完秒數回到 app，卡片的倒數與通知列是對不上的。
            RestTimerPlugin.emit(delta > 0 ? "plus15" : "minus15", remainingSeconds);
            return START_NOT_STICKY;
        }

        int seconds = intent == null ? 0 : intent.getIntExtra(EXTRA_SECONDS, 0);
        if (seconds <= 0) {
            stopSelf();
            return START_NOT_STICKY;
        }

        ensureChannel();
        sessionActive = true; // F104-A：這輪開始了
        // F123 ③：heads-up 的文案來源與浮動視窗同一個 hint，這輪開始時就抓下來
        alarmHint = intent.getStringExtra(EXTRA_HINT) == null
            ? "" : intent.getStringExtra(EXTRA_HINT);
        paused = false;
        halted = false; // F100：新的一輪；上一輪停在哪裡跟這輪無關
        remainingSeconds = seconds;
        elapsedSeconds = 0; // F131：新的一輪，休息秒數重新算
        roundStartedAt = System.currentTimeMillis();
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
            // F104 ①：待記組跟著這輪一起帶下去（沒帶就是 -1，overlay 那邊整塊不顯示）
            RestOverlay.setDraft(
                this,
                intent.getDoubleExtra(EXTRA_WEIGHT, -1),
                intent.getIntExtra(EXTRA_REPS, -1),
                intent.getBooleanExtra(EXTRA_BODYWEIGHT, false),
                intent.getIntExtra(EXTRA_EXERCISE_ID, -1),
                intent.getIntExtra(EXTRA_SET_NUMBER, -1),
                intent.getIntExtra(EXTRA_WORKOUT_ID, -1),
                intent.getStringExtra(EXTRA_MODE));
        }
        startTimer(seconds);
        // 不用 START_STICKY：休息被系統中斷後自己復活沒有意義（剩餘秒數已經不對了），
        // 而 ④「app 被殺掉不留殘影」也要求它安靜地消失
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        sessionActive = false; // F104-A：服務沒了就不再撐著 WebView
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
                elapsedSeconds += 1; // F131：累加，不由 targetSeconds - remaining 推算（±15s 會算錯）
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
                // F123 ③：響鈴開始——警示介面依當下位置換手（app 內非計時頁才跳 heads-up）。
                // 順序在 startAlarm() 之後：那裡會先把 alarming 清成 false。
                alarming = true;
                refreshAlarmSurface(RestTimerService.this);
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
                elapsedSeconds += 1; // F131：歸零後仍在休息，照樣累加
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
        // F123 ③：heads-up 掛在這裡而不是各個呼叫點——「每一條離場路徑都要呼叫」這個既有紀律
        // 已經涵蓋停止／暫停／服務被回收三條路，跟著它走就不會有哪一條漏掉而留下孤兒通知。
        alarming = false;
        cancelAlarmHeadsUp(this);
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
        } else if (!halted) {
            // F126 ①：**倒數中**（含暫停，⑤）也要能停、能回計時頁。
            // F123 之後 app 內看不到浮動視窗，這則通知是那時唯一的操作介面。
            // 已停止（halted）不加：那個狀態沒有倒數可停，而回 app 的入口在 contentIntent 上。
            Intent stopIntent = new Intent(this, RestTimerService.class)
                .setAction(ACTION_STOP_FROM_NOTIFICATION);
            PendingIntent stopPending = PendingIntent.getService(
                this, 1, stopIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            builder.addAction(android.R.drawable.ic_lock_idle_alarm, "停止", stopPending);

            // F126 ②③：這顆**只導頁，不停倒數**——與時間到那顆同名但相反。
            // 所以走的是另一個 extra（EXTRA_FOCUS_REST），不得與 EXTRA_BACK_TO_APP 共用。
            if (launch != null) {
                Intent focusIntent = getPackageManager().getLaunchIntentForPackage(getPackageName());
                if (focusIntent != null) {
                    focusIntent.putExtra(EXTRA_FOCUS_REST, true);
                    focusIntent.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
                    PendingIntent focusPending = PendingIntent.getActivity(
                        this, 4, focusIntent,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                    builder.addAction(android.R.drawable.ic_menu_revert, "回到 app", focusPending);
                }
            }
        }
        return builder.build();
    }

    /**
     * F123 ③：把「時間到」的警示介面換到該在的那一個。
     *
     * <p>三個介面（app 內卡片、通知列 heads-up、浮動視窗）任何時刻只有一個在講「時間到」。
     * 這裡只決定 heads-up 的去留，另外兩個各自由 F73 與 RestOverlay.shouldShow() 管。
     * 重複呼叫安全——切前景／切頁時會被呼叫多次。
     *
     * <p>static 且吃 Context：呼叫端是 RestOverlay 的旗標變動處，那裡沒有服務實例。
     */
    static void refreshAlarmSurface(Context context) {
        if (context == null) return;
        if (alarming && RestOverlay.headsUpWanted()) {
            postAlarmHeadsUp(context);
        } else {
            cancelAlarmHeadsUp(context);
        }
    }

    private static void postAlarmHeadsUp(Context context) {
        ensureAlarmChannel(context);
        // 關閉＝這輪結束（④）。沿用既有的 STOP_FROM_NOTIFICATION：它已經負責停鈴、
        // 收前景服務並回送事件給前端，不必再開一條會走偏的新路。
        Intent closeIntent = new Intent(context, RestTimerService.class)
            .setAction(ACTION_STOP_FROM_NOTIFICATION);
        PendingIntent closePending = PendingIntent.getService(
            context, 2, closeIntent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        // 回到 app＝停止 ＋ 導頁（④）。走 Activity intent 而不是 service intent：
        // 這樣系統會順手收起通知欄並把 app 帶到最前，停止與導頁則由 MainActivity 執行。
        Intent backIntent = context.getPackageManager()
            .getLaunchIntentForPackage(context.getPackageName());
        PendingIntent backPending = null;
        if (backIntent != null) {
            backIntent.putExtra(EXTRA_BACK_TO_APP, true);
            backIntent.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
            backPending = PendingIntent.getActivity(
                context, 3, backIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        }

        NotificationCompat.Builder builder =
            new NotificationCompat.Builder(context, ALARM_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                .setContentTitle("休息時間到")
                .setContentText(alarmHint.isEmpty() ? "回到 app 記下一組" : alarmHint)
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setPriority(NotificationCompat.PRIORITY_HIGH) // Android 7 以下靠這個才會彈
                // ⚠ 一定要 true：超時每秒都會重貼這則通知，false 會讓它每秒重新彈一次
                .setOnlyAlertOnce(true)
                .setOngoing(false) // 滑得掉；滑掉不停鈴（F72 ③「響到你理它為止」不變）
                .setAutoCancel(false)
                .addAction(android.R.drawable.ic_lock_idle_alarm, "關閉", closePending);
        if (backPending != null) {
            builder.addAction(android.R.drawable.ic_menu_revert, "回到 app", backPending);
            builder.setContentIntent(backPending); // 點通知本體＝跟「回到 app」同一件事
        }
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager != null) manager.notify(ALARM_NOTIFICATION_ID, builder.build());
    }

    private static void cancelAlarmHeadsUp(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager != null) manager.cancel(ALARM_NOTIFICATION_ID);
    }

    private static void ensureAlarmChannel(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null || manager.getNotificationChannel(ALARM_CHANNEL_ID) != null) return;
        NotificationChannel channel = new NotificationChannel(
            ALARM_CHANNEL_ID, "休息時間到", NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription("休息倒數歸零時從畫面上方跳出提醒");
        channel.setShowBadge(false);
        // 聲音由 MediaPlayer 以 USAGE_ALARM 播（F72 ③），通知本身不再發一次音
        channel.setSound(null, null);
        manager.createNotificationChannel(channel);
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

    static void start(
        Context context, int seconds, boolean overlay, String hint,
        double weight, int reps, boolean bodyweight, int exerciseId, int setNumber,
        int workoutId, String mode
    ) {
        Intent intent = new Intent(context, RestTimerService.class)
            .setAction(ACTION_START)
            .putExtra(EXTRA_SECONDS, seconds)
            .putExtra(EXTRA_OVERLAY, overlay)
            .putExtra(EXTRA_HINT, hint == null ? "" : hint)
            .putExtra(EXTRA_WEIGHT, weight)
            .putExtra(EXTRA_REPS, reps)
            .putExtra(EXTRA_MODE, mode == null ? "reps" : mode)
            .putExtra(EXTRA_BODYWEIGHT, bodyweight)
            .putExtra(EXTRA_EXERCISE_ID, exerciseId)
            .putExtra(EXTRA_SET_NUMBER, setNumber)
            .putExtra(EXTRA_WORKOUT_ID, workoutId);
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

    /** F131 ①：背景記完一組 → 當場開新的一輪。 */
    static void nextRound(Context context) {
        context.startService(
            new Intent(context, RestTimerService.class).setAction(ACTION_NEXT_ROUND));
    }

    /** F103 ③：停止之後的再開始。浮動視窗的「再開始」鈕走這條。 */
    static void restart(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_RESTART));
    }

    static void pause(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_PAUSE));
    }

    static void resume(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_RESUME));
    }

    /**
     * F127 ②④：記下「有人明確結束了這輪」的時刻。
     *
     * <p>存的是時間戳而不是布林旗標，因為 ④ 要求能分辨兩件事：
     * <ul>
     *   <li>有人按了停止 → 留下一個**比那輪 startedAt 還新**的時間戳</li>
     *   <li>行程被系統殺掉 → 什麼都沒留下，F66 照舊還原</li>
     * </ul>
     *
     * <p>用時間戳還順帶解決了「舊標記污染新一輪」：新的休息開始得比標記晚，
     * 比大小自然就過關，不必在開新一輪時記得去清它。
     *
     * <p>⚠ 不可以改成「服務不在了就當這輪結束」——那正是 ④ 禁止的判準，
     * 會把 F66（app 與服務一起被回收後還原休息）整個殺掉。
     */
    static void markStopped(Context context) {
        statePrefs(context).edit().putLong(KEY_STOPPED_AT, System.currentTimeMillis()).apply();
    }

    /** F127 ②：前端開機時取件用。沒有標記回 0（＝從沒被明確結束過）。 */
    static long stoppedAt(Context context) {
        return statePrefs(context).getLong(KEY_STOPPED_AT, 0L);
    }

    private static SharedPreferences statePrefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(STATE_PREFS, Context.MODE_PRIVATE);
    }

    static void stop(Context context) {
        context.startService(new Intent(context, RestTimerService.class).setAction(ACTION_STOP));
    }
}
