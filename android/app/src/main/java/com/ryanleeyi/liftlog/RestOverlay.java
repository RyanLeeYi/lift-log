package com.ryanleeyi.liftlog;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.Looper;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.Interpolator;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * F64 建立、F89 改版：浮在其他 app 之上的休息倒數小視窗。
 *
 * <p>秒數由 {@link RestTimerService} 的原生 CountDownTimer 推進來（F64 ①）——
 * overlay 的使用情境本來就是「你人在別的 app 裡」，那時 WebView 一定在背景、JS 計時器被節流，
 * 所以絕不能讓前端每秒 call 過來畫。同理 F89 ④ 的 ±15s 也走原生（{@code RestTimerService.adjust}），
 * 繞前端會在最需要它的時候失效。
 *
 * <p><b>為什麼握把是 static</b>（F64 ④，F63 ③ 的教訓）：倒數自然歸零後服務已 stopSelf，
 * 之後送進來的 ACTION_STOP 會建立一個**全新的服務實例**。握把若放在實例欄位，新實例手上是 null，
 * 舊的 view 就永遠掛在螢幕上關不掉。window 由 WindowManager 持有、生命週期跟著 process，
 * 所以握把也要跟著 process 走。
 *
 * <p><b>F89 兩態</b>：收合是 76dp 圓（圓環＋秒數），展開是 214dp 卡片（圓環＋四顆控制鈕＋
 * 回 app 主按鈕）。點本體切換，拖曳移動，位置與展開態存 SharedPreferences——設計稿寫
 * localStorage，但這是系統 overlay、不經 WebView，那邊的儲存碰不到。
 */
final class RestOverlay {

    // ---------- 設計 token（與 app.css 的 :root 同源，改一邊要改另一邊） ----------
    private static final int CARD = Color.parseColor("#2E2822");
    private static final int CARD_HI = Color.parseColor("#3B342C");
    private static final int LINE = Color.parseColor("#544A3D");
    private static final int TEXT_DIM = Color.parseColor("#A99C8C");
    private static final int TEXT_MUTE = Color.parseColor("#8F8375");
    private static final int ACCENT = Color.parseColor("#D9B25F");
    private static final int ON_ACCENT = Color.parseColor("#241E14");
    private static final int OVER = Color.parseColor("#C96A4E");

    private static final String PREFS = "liftlog.overlay";
    private static final String KEY_X = "x";
    private static final String KEY_Y = "y";
    private static final String KEY_EXPANDED = "expanded";

    private static View view;
    private static RingView ring;
    private static TextView countdown;
    private static TextView status;
    private static ImageView pauseButton; // F71 ①：暫停／繼續兩態共用同一顆
    private static TextView stopButton; // F73：鬧鐘響著時要轉警示色
    /** F116 ②：±15s 那一列——休息態才出現（就緒態沒有在倒數，加減秒數沒有意義）。 */
    private static View adjustRow;
    /** F104 ①：待記組——這輪休息結束後要記的那一組。weight < 0 ＝ 前端沒送，整塊不顯示。 */
    private static double draftWeight = -1;
    private static int draftReps = -1;
    private static boolean draftBodyweight;
    /** F125 ③：補送時驗證歸屬用——這一組屬於哪個動作、第幾組。-1 ＝ 沒帶（舊版前端）。 */
    private static int draftExerciseId = -1;
    private static int draftSetNumber = -1;
    /** F125 ①：已排入但還沒寫進去（app 在背景按下）。與 logPending 互斥，兩者文案不同。 */
    private static boolean logQueued;
    private static TextView draftLabel;
    private static TextView repsLabel;
    /** F104 ⑤：就地記錄的三種狀態。等待前端回報時鎖住按鈕，避免連按記成兩組。 */
    private static boolean logPending;
    private static boolean logFailed;
    private static TextView logButton;
    private static TextView logStatus;
    /** ⑤ 的 3 秒門檻：逾時沒等到回報就當作沒記到（app 被回收、WebView 無回應）。 */
    private static final long LOG_TIMEOUT_MS = 3000L;
    private static Runnable logTimeout;
    private static TextView mainButton; // F89 ④：回 app 記下一組（超時轉 --over）
    /** F71：暫停狀態。兩邊（app 內卡片與這裡）必須顯示一致，否則使用者不知道該信誰。 */
    private static boolean paused;
    /** F100：已停止但視窗留著——不倒數、不響，暫停與停止兩顆收起來。 */
    private static boolean halted;
    private static WindowManager.LayoutParams params;
    /** F89 ⑤：收合／展開。記住使用者的選擇——每輪休息都要重按一次很煩。 */
    private static boolean expanded;
    /**
     * 使用者在**這一輪休息中**按過收合以外的關閉入口。
     *
     * <p>沒有這個旗標的話：關掉 overlay 後只要改休息秒數（前端會重下一次 ACTION_START），
     * overlay 就自己跑回來，等於吃掉使用者剛表達的意圖（2026-07-28 Codex review P2）。
     */
    private static boolean dismissed;

    // ---------- F69：顯示條件的四個輸入 ----------
    //
    // 規則收斂在 shouldShow() 一處。散在各呼叫點的話，「兩邊都沒有」這種最糟的失敗
    // 會從某條沒人想到的路徑漏出來。

    private static boolean active;
    private static boolean appForeground;
    private static boolean restCardVisible;
    private static int remaining;
    /** F89 ①：圓環的分母。沒有它就畫不出「還剩多少比例」。 */
    private static int target = 60;
    /** F89 ③：「動作名 · 第 N 組」。純顯示，拿不到就整行不畫。 */
    private static String hint = "";

    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    /** F74：Android 的最小觸控目標。視覺上的圖示比這小，但可按的範圍不能小於它。 */
    private static final int TOUCH_TARGET_DP = 48;
    private static final int BUTTON_GAP_DP = 8;

    // F89 ⑨：動效 160ms ease-out。ease-out ≒ DecelerateInterpolator（快進慢收），
    // 與 app.css 那邊的 cubic-bezier 同一個調性。
    private static final int ANIM_MS = 160;
    private static final Interpolator EASE_OUT = new DecelerateInterpolator();

    private RestOverlay() {}

    /**
     * 所有進入點都先繞到 main thread（F89 ⑧）。
     *
     * <p>2026-07-28 模擬器實測抓到的 crash：Capacitor 的 plugin 方法跑在 `CapacitorPlugins`
     * 執行緒，F69 的 setRestCardVisible 從那裡建立 view，之後服務的 CountDownTimer 在 main
     * thread 更新同一個 view →「Only the original thread that created a view hierarchy can
     * touch its views」直接閃退。收斂在這一個閘門，而不是要求每個呼叫端自己記得
     * （記不住的那次就是 crash）。
     */
    private static void onMain(Runnable action) {
        if (Looper.myLooper() == Looper.getMainLooper()) action.run();
        else MAIN.post(action);
    }

    /**
     * F89 ⑨：原生層的 prefers-reduced-motion。
     *
     * <p>Android 沒有跟 CSS 那個 media query 對應的 API；系統層最接近的是開發者選項／協助工具
     * 把「動畫比例」關掉（`Settings.Global.ANIMATOR_DURATION_SCALE` = 0），Google 自家 app
     * 也是拿它當減少動態的判斷。查不到就當作要動效（預設 1.0）——判不出來時給正常體驗，
     * 不要反過來把所有人的動效都關掉。
     */
    private static boolean reduceMotion(Context context) {
        try {
            float scale = Settings.Global.getFloat(
                context.getContentResolver(), Settings.Global.ANIMATOR_DURATION_SCALE, 1f);
            return scale == 0f;
        } catch (Exception e) {
            return false;
        }
    }

    /** F89 ⑨：出現／換態時的 160ms ease-out。reduced-motion 時直接就位，不做過場。 */
    private static void animateIn(Context context, View target) {
        if (target == null) return;
        if (reduceMotion(context)) {
            target.setAlpha(1f);
            target.setScaleX(1f);
            target.setScaleY(1f);
            return;
        }
        target.setAlpha(0f);
        target.setScaleX(.92f);
        target.setScaleY(.92f);
        target.animate()
            .alpha(1f).scaleX(1f).scaleY(1f)
            .setDuration(ANIM_MS).setInterpolator(EASE_OUT).start();
    }

    /** Android 6 起 SYSTEM_ALERT_WINDOW 是「特殊權限」，宣告了也要使用者逐 app 手動開。 */
    static boolean permitted(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true;
        return Settings.canDrawOverlays(context);
    }

    /**
     * F69 ①④⑥：唯一的顯示判斷。
     *
     * <p>「app 在前景」**且**「畫面上有 REST 卡片」＝使用者已經看得到倒數 → 藏。其餘都顯示。
     * 手動關閉（④）優先於一切自動顯示。
     *
     * <p>F123 ①（取代 F122 的情境 × 狀態表）：**app 在前景時一律不顯示**。
     * app 內的倒數改由通知列橫條承擔，時間到改跳 heads-up（見 RestTimerService）。
     * 條件因此塌成單一輸入 `appForeground`——`restCardVisible` 與 `halted`
     * 不再參與這個判斷（前者仍是 heads-up 的條件、後者仍決定視窗畫成哪一態，都還有用）。
     *
     * <p>沿革：F122 曾把前景的隱藏條件擴成 `restCardVisible || halted`
     * （Ryan 2026-08-03 回報「停止後回 app 切頁視窗又冒出來」）。F123 把整個 app 內都關掉，
     * 那一版的兩個條件於是被這一條吸收——**但 F122 ③「藏不等於結束」仍然成立且更重要了**。
     *
     * <p>⚠ 這裡**藏的不是結束**：active／待記組／±15s 調過的秒數全部留著（F122 ③），
     * F100 ③「只有 ✕、開新一輪、結束訓練會結束這輪」原封不動。
     */
    private static boolean shouldShow() {
        if (!active || dismissed) return false;
        return !appForeground;
    }

    /**
     * F123 ③：現在該不該用 heads-up 通知當「時間到」的介面。
     *
     * <p>「app 在前景**且**不在所屬動作的計時頁」——正好是浮動視窗以前在 app 內會出現的那一格。
     * 人在計時頁時畫面上已有倒數卡（不跳），app 不在前景時浮動視窗就是警示介面（也不跳），
     * 三個介面任何時刻只有一個在講「時間到」。
     *
     * <p>兩個旗標**與 overlay 開關無關**：使用者把浮動視窗關掉時它們照樣在維護，
     * 所以 heads-up 不受那個設定影響。
     */
    static boolean headsUpWanted() {
        return appForeground && !restCardVisible;
    }

    /** 服務啟動／停止這輪休息。 */
    static void setActive(Context context, boolean value, int seconds, String hintText) {
        // F100：新的一輪＝不再是「已停止」狀態（旗標留著會讓暫停鈕永遠消失）
        halted = false;
        onMain(() -> {
            active = value;
            if (value) {
                remaining = seconds;
                target = Math.max(1, seconds); // 分母不能是 0
                hint = hintText == null ? "" : hintText;
            }
            apply(context);
        });
    }

    /** F69 ②：app 切到前景／背景。 */
    static void setAppForeground(Context context, boolean value) {
        onMain(() -> {
            appForeground = value;
            if (value && restCardVisible) dismissed = false; // F71 ⑩：同下
            apply(context);
            // F123 ③：這是 headsUpWanted() 的輸入之一——切前景／背景時警示介面要跟著換手，
            // 不能等到下一秒的 tick 才發現（切出去時 heads-up 要收、浮動視窗接手）
            RestTimerService.refreshAlarmSurface(context);
        });
    }

    /** F69 ③：前端切畫面時回報 REST 卡片是否可見。 */
    static void setRestCardVisible(Context context, boolean value) {
        onMain(() -> {
            restCardVisible = value;
            // F71 ⑩：關閉只是「現在別擋我」，效力到你回頭看見 app 內的倒數為止——
            // 那一刻解除，之後再離開計時頁就會再出現。解除當下不會彈出來，
            // 因為此時 shouldShow() 本來就是 false（卡片可見）。
            if (value && appForeground) dismissed = false;
            apply(context);
            // F123 ③：進／出所屬計時頁也要換手——走進計時頁時 heads-up 要收（卡片接手），
            // 響鈴中走出去時要跳出來
            RestTimerService.refreshAlarmSurface(context);
        });
    }

    /** F71 ①：暫停狀態變了——換掉按鈕圖示與狀態字。狀態本身由服務與前端各自維護。 */
    /**
     * F100：切換「已停止但視窗還在」的顯示。
     *
     * <p>② 暫停在這個狀態下不可按——沒有在跑的倒數可暫停，按了沒反應比按不到更糟；
     * 停止鈕同理（已經停了，再按一次沒有語意）。兩顆一起收起來，±15s 與主按鈕留著。
     * ⑥ F73 的警示色也在這裡退回一般色（鈴已經停了，還紅著會讓人以為仍在響）。
     */
    static void setHalted(Context context, boolean value, int resetSeconds) {
        onMain(() -> {
            halted = value;
            paused = false;
            remaining = resetSeconds;
            target = resetSeconds > 0 ? resetSeconds : target;
            applyStateVisibility();
            applyAlarmTint(false);
            paintTime();
            // F122 ②：halted 現在是 shouldShow() 的輸入之一，所以換態時必須重跑顯示判斷。
            // 少了這一行，人已經在 app 內（例如日曆頁）按停止時視窗不會當場收掉，
            // 要等下一次切頁才生效。放在三個 paint 之後：view 還在時先畫成就緒態再決定去留，
            // 被 detach 的話那幾個呼叫本來就是 null-safe 的 no-op。
            apply(context);
        });
    }

    /** F104 ①：這輪的待記組。weight < 0 或 reps < 0 ＝ 沒帶，整塊不顯示。 */
    static void setDraft(
        Context context, double weight, int reps, boolean bodyweight,
        int exerciseId, int setNumber
    ) {
        onMain(() -> {
            draftWeight = weight;
            draftReps = reps;
            draftBodyweight = bodyweight;
            draftExerciseId = exerciseId;
            draftSetNumber = setNumber;
            logQueued = false;
            // 新的一輪＝上一輪的記錄狀態不再適用（失敗態不該跨輪殘留）
            clearLogPending();
            logFailed = false;
            apply(context);
        });
    }

    /**
     * F104 ⑤：前端回報了就地記錄的結果。
     *
     * <p>成功不必在這裡做什麼——前端會接著開新的一輪休息，走 setActive／setDraft 把整個
     * 視窗重畫成下一組。這裡只負責**失敗**那條路：明確講出「沒記到」並把主按鈕退回
     * 「回 app 記下一組」，讓使用者走原本那條路。
     */
    static void onLogResult(Context context, boolean ok) {
        onMain(() -> {
            clearLogPending();
            logQueued = false;
            // F125 ⑤：寫進去了就清，否則下次開 app 會幽靈重播（伺服器雖然會去重，
            // 但留著等於讓「補送」這條路永遠有東西可送）
            if (ok) PendingLog.clear(context);
            if (ok) {
                logFailed = false;
                vibrateOnce(context); // ③ 成功回饋：短單擊，與鬧鈴的重複震動分得開
            } else {
                logFailed = true;
            }
            apply(context);
        });
    }

    /**
     * F116 ②⑥：兩態的按鈕組互斥。
     *
     * <p>就緒態（halted）＝沒有在倒數：待記組 ＋「完成這組」；暫停／停止／±15s 全收起來——
     * 沒有在跑的倒數可暫停、可加減秒數，留著只會讓人按了沒反應。
     * 休息態＝倒數中：暫停／停止／±15s；「完成這組」收起來（要記下一組先按停止，
     * 與 app 內「繼續下一組 → 完成這組」是同一組動作）。
     *
     * <p>⚠ 一定要在 buildExpanded 結尾也呼叫一次：收合⇄展開會**重建**整棵 view，
     * 重建出來的都是預設 VISIBLE（F100／F103 都踩過這個坑）。
     */
    private static void applyStateVisibility() {
        boolean resting = !halted;
        if (pauseButton != null) pauseButton.setVisibility(resting ? View.VISIBLE : View.GONE);
        if (stopButton != null) stopButton.setVisibility(resting ? View.VISIBLE : View.GONE);
        if (adjustRow != null) adjustRow.setVisibility(resting ? View.VISIBLE : View.GONE);
        if (logButton != null) {
            logButton.setVisibility(!resting && hasDraft() ? View.VISIBLE : View.GONE);
        }
        if (draftRow != null) draftRow.setVisibility(hasDraft() ? View.VISIBLE : View.GONE);
    }

    private static void clearLogPending() {
        logPending = false;
        if (logTimeout != null) {
            MAIN.removeCallbacks(logTimeout);
            logTimeout = null;
        }
    }

    /** ③ 成功回饋的震動：**短單擊**。鬧鈴是重複震動，兩者在同一個視窗上不能混淆。 */
    private static void vibrateOnce(Context context) {
        try {
            Vibrator vib = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
            if (vib == null || !vib.hasVibrator()) return;
            vib.vibrate(VibrationEffect.createOneShot(40, VibrationEffect.DEFAULT_AMPLITUDE));
        } catch (Exception ignored) {
            // 震動不是必要條件（文字回饋已經在畫面上），失敗就算了
        }
    }

    static void setPaused(Context context, boolean value) {
        onMain(() -> {
            paused = value;
            if (pauseButton != null) {
                pauseButton.setImageResource(
                    paused ? R.drawable.ic_rest_play : R.drawable.ic_rest_pause);
            }
            if (status != null) status.setText(statusText());
            applyAlarmTint(remaining < 0 && !paused); // F73 ③：暫停中不算「響著」
            apply(context);
        });
    }

    static void update(Context context, int remainingSeconds) {
        onMain(() -> {
            remaining = remainingSeconds;
            paintTime();
            // F73 ①②③：鬧鐘響著（超時且非暫停）時停止鈕轉警示色——人在別的 app 裡時，
            // 這顆小視窗是唯一看得到的東西，得指出該點哪裡。
            applyAlarmTint(remainingSeconds < 0 && !paused);
            apply(context);
        });
    }

    /** 把秒數、圓環比例與超時配色一次刷上去（收合／展開共用）。 */
    private static void paintTime() {
        boolean over = remaining < 0;
        if (countdown != null) {
            countdown.setText(text(remaining));
            countdown.setTextColor(over ? OVER : ACCENT);
        }
        if (status != null) status.setText(statusText());
        if (ring != null) {
            // F89 ⑨：每秒線性更新。超時後停在滿格（比例夾在 0–1），不讓環反向繞回去——
            // 那會讓「超時」看起來像「又重新開始」。
            ring.setProgress(over ? 0f : Math.max(0f, Math.min(1f, remaining / (float) target)));
            ring.setOver(over);
        }
        if (mainButton != null) {
            // F104 ⑥：有「記下這組」時，回 app 退居次要——描邊而不是實心琥珀，
            // 兩顆同等份量的主按鈕會讓人每次都要選一次。超時仍轉 --over（F89 ④ 不回歸），
            // 但次要態只染框與字，不整顆塗滿。
            GradientDrawable bg = new GradientDrawable();
            int accent = over ? OVER : ACCENT;
            if (hasDraft()) {
                bg.setColor(Color.TRANSPARENT);
                bg.setStroke(dp(mainButton.getContext(), 1), over ? OVER : LINE);
                mainButton.setTextColor(over ? OVER : TEXT_DIM);
            } else {
                bg.setColor(accent);
                mainButton.setTextColor(ON_ACCENT);
            }
            bg.setCornerRadius(dp(mainButton.getContext(), 22));
            mainButton.setBackground(bg);
        }
    }

    private static String statusText() {
        if (halted) return "已停止";
        if (paused) return "已暫停";
        return remaining < 0 ? "超時了" : "休息中";
    }

    /**
     * F73 ②：警示色只在響的時候上，停止／繼續之後回復。
     *
     * <p><b>為什麼改底色而不是文字色</b>（2026-07-28 模擬器實測抓到）：第一版用 emoji ＋
     * `setTextColor()`，而 emoji 是彩色字形、吃不到文字色，螢幕上什麼都沒變。
     * F89 換成文字鈕後兩者都可行，仍沿用底色——小尺寸下它比字色更容易一眼看到。
     */
    private static void applyAlarmTint(boolean alarming) {
        if (stopButton == null) return;
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(alarming ? OVER : CARD_HI);
        bg.setCornerRadius(dp(stopButton.getContext(), 22));
        stopButton.setBackground(bg);
        stopButton.setTextColor(alarming ? Color.WHITE : TEXT_DIM);
    }

    /** 關掉顯示，並記住這輪休息不要再自己冒出來（倒數照常走完）。 */
    /**
     * F64 ④：使用者手動收起視窗。
     *
     * <p>F100 ③④：**已停止**的狀態下按 ✕ 等於「這輪結束了」——倒數早就停了，
     * 只藏視窗會留下一個沒有倒數卻還活著的前景服務（孤兒）。所以這時候要一路收乾淨。
     * 還在倒數時按 ✕ 仍是原本的語意：只藏視窗，通知列的倒數照走（F64 ④）。
     */
    static void dismiss(Context context) {
        onMain(() -> {
            if (halted) {
                RestTimerService.stop(context); // ④ 不留孤兒服務／孤兒通知
                return;
            }
            dismissed = true;
            apply(context);
        });
    }

    /** 把 {@link #shouldShow()} 的結論落到實際的 window 上。重複呼叫安全。 */
    private static void apply(Context context) {
        if (shouldShow()) {
            attach(context);
        } else {
            detach(context);
        }
    }

    /** F72 ①：歸零後不消失而是繼續數，`+0:07`＝超時，與 app 內 REST 卡片一致。 */
    private static String text(int seconds) {
        int abs = Math.abs(seconds);
        String sign = seconds < 0 ? "+" : "";
        return String.format("%s%d:%02d", sign, abs / 60, abs % 60);
    }

    private static void attach(Context context) {
        if (!permitted(context)) return; // 沒授權就安靜不畫，通知列倒數照常（不當機不空白）
        if (view != null) {
            paintTime();
            return;
        }
        try {
            view = buildView(context);
            params = buildParams(context);
            windowManager(context).addView(view, params);
            paintTime();
            animateIn(context, view); // ⑨：出現時淡入放大，不要硬跳出來
        } catch (Exception e) {
            // OEM（例如 Samsung）可能在授權之外再擋一層，或 token 失效 —— 加不上就退回只有通知列
            clearRefs();
        }
    }

    /**
     * F64 ④：這輪休息結束——移除 view 並把所有狀態歸零。
     * 重複呼叫安全；ACTION_STOP、onFinish、onDestroy 都會走到這裡。
     *
     * <p>{@link #dismissed} 也在這裡清掉：這些呼叫點都代表「這輪結束了」，下一輪要重新顯示。
     */
    static void hide(Context context) {
        onMain(() -> {
            dismissed = false;
            active = false;
            paused = false;
            // ⚠ restCardVisible **不在這裡清**（2026-07-31 Ryan 真機回報的回歸）。
            // 它描述的是「人在哪個畫面」——那是前端擁有的狀態，跟「這輪休息結束了」無關。
            // 清掉它等於原生自己捏造了一個前端沒說過的事實：下一輪 setActive 時
            // shouldShow() 看到 restCardVisible=false 就把視窗畫出來，即使人正看著計時頁。
            //
            // 這個 bug 在 F103 之前被前端的值「每輪 true↔false 來回跳」掩護著（重送蓋回來了）；
            // F103 ② 把條件改成單純的「人在計時頁面」之後值不再變動，
            // 前端的去重（native-notify 的 lastCardVisible）就讓它送不出第二次。
            //
            // 殘留的 true 不會反過來害事：app 不在前景時 shouldShow() 根本不看這個旗標，
            // 而 app 在前景就代表前端活著、下一次 render 會把真實值送上來。
            detach(context);
        });
    }

    /** 只收起 window，不動狀態——F69 的「暫時藏起來」（這輪休息還在跑）。 */
    private static void detach(Context context) {
        if (view == null) return;
        view.animate().cancel(); // ⑨：view 要被移掉了，別讓動畫還抓著它跑
        try {
            windowManager(context).removeViewImmediate(view);
        } catch (Exception e) {
            /* 已經被移除或 window token 失效：目的已達成 */
        }
        clearRefs();
    }

    private static void clearRefs() {
        view = null;
        ring = null;
        countdown = null;
        status = null;
        pauseButton = null;
        stopButton = null;
        mainButton = null;
        params = null;
    }

    /**
     * F89 ⑤：切換收合／展開——重建 view（兩態版面差太多，共用一棵樹反而更難讀）。
     *
     * <p>⑨ 的過場由 {@link #attach} 的 {@link #animateIn} 接手：**只做入場、不做出場**。
     * 出場動畫要等 callback 跑完才 removeView，那段期間 hide()／服務被回收都可能插進來，
     * 留下移不掉的 view——在一個「關不掉的浮動視窗」上，那個風險換不到那 160ms。
     */
    private static void toggleExpanded(Context context) {
        onMain(() -> {
            expanded = !expanded;
            prefs(context).edit().putBoolean(KEY_EXPANDED, expanded).apply();
            detach(context);
            apply(context);
        });
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static WindowManager windowManager(Context context) {
        return (WindowManager) context.getApplicationContext()
            .getSystemService(Context.WINDOW_SERVICE);
    }

    private static int dp(Context context, int value) {
        return (int) TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP, value, context.getResources().getDisplayMetrics());
    }

    private static View buildView(Context context) {
        expanded = prefs(context).getBoolean(KEY_EXPANDED, false);
        return expanded ? buildExpanded(context) : buildCollapsed(context);
    }

    /** F89 ①：76dp 圓，只有圓環與秒數。點一下展開，拖曳移動。 */
    private static View buildCollapsed(Context context) {
        FrameLayout root = new FrameLayout(context);
        int size = dp(context, 76);
        root.setLayoutParams(new FrameLayout.LayoutParams(size, size));

        GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.OVAL);
        bg.setColor(CARD);
        root.setBackground(bg);
        // 設計稿的 box-shadow 在原生對應 elevation（系統 overlay 不吃 CSS 陰影）
        root.setElevation(dp(context, 14));

        ring = new RingView(context, dp(context, 26), dp(context, 7));
        root.addView(ring, new FrameLayout.LayoutParams(size, size));

        countdown = new TextView(context);
        countdown.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        countdown.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        countdown.setTextColor(ACCENT);
        FrameLayout.LayoutParams clp = new FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT);
        clp.gravity = Gravity.CENTER;
        root.addView(countdown, clp);

        root.setOnTouchListener(new DragListener(context));
        return root;
    }

    /** F89 ②③④：214dp 卡片。把手列 ＋ 圓環 ＋ 動作提示 ＋ 四顆控制鈕 ＋ 回 app 主按鈕。 */
    private static View buildExpanded(Context context) {
        LinearLayout root = new LinearLayout(context);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setLayoutParams(new LinearLayout.LayoutParams(
            dp(context, 214), LinearLayout.LayoutParams.WRAP_CONTENT));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(CARD);
        bg.setCornerRadius(dp(context, 24));
        root.setBackground(bg);
        root.setElevation(dp(context, 18));

        root.addView(buildHandle(context));
        root.addView(buildRingBlock(context));

        TextView hintLabel = new TextView(context);
        hintLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        hintLabel.setTextColor(TEXT_DIM);
        hintLabel.setGravity(Gravity.CENTER);
        hintLabel.setText(hint);
        hintLabel.setVisibility(hint.isEmpty() ? View.GONE : View.VISIBLE);
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        hlp.bottomMargin = dp(context, 10);
        root.addView(hintLabel, hlp);

        root.addView(buildDraftRow(context));
        root.addView(buildControls(context));
        root.addView(buildLogButton(context));
        root.addView(buildMainButton(context));

        // F100／F103 的教訓：收合⇄展開會**重建**整棵 view，任何「按下當時設一次」的狀態
        // 重建後都會被打回預設。所有依狀態而變的東西都在這裡重新套一次。
        paintDraft();
        paintLogButton();
        paintLogStatus();
        applyStateVisibility(); // 所有子 view 都建好之後才套，順序不能反（見 buildControls 的註解）

        // 卡片本體也可拖；點擊要收合。兩者由 DragListener 依位移量分辨
        root.setOnTouchListener(new DragListener(context));
        return root;
    }

    private static View buildHandle(Context context) {
        LinearLayout handle = new LinearLayout(context);
        handle.setOrientation(LinearLayout.HORIZONTAL);
        handle.setGravity(Gravity.CENTER_VERTICAL);
        handle.setPadding(dp(context, 16), dp(context, 12), dp(context, 16), dp(context, 10));

        View bar = new View(context);
        GradientDrawable barBg = new GradientDrawable();
        barBg.setColor(LINE);
        barBg.setCornerRadius(dp(context, 2));
        bar.setBackground(barBg);
        handle.addView(bar, new LinearLayout.LayoutParams(dp(context, 22), dp(context, 3)));

        TextView brand = new TextView(context);
        brand.setText("LIFT·LOG");
        brand.setTextSize(TypedValue.COMPLEX_UNIT_SP, 10);
        brand.setTypeface(Typeface.MONOSPACE);
        brand.setTextColor(TEXT_MUTE);
        brand.setLetterSpacing(0.18f);
        brand.setGravity(Gravity.CENTER);
        brand.setSingleLine(true); // 寬度不夠時寧可截斷，也不要疊成好幾行
        handle.addView(brand, new LinearLayout.LayoutParams(0,
            LinearLayout.LayoutParams.WRAP_CONTENT, 1f));

        // F100 ③：這顆改成**關閉**（原本是收合）。
        //
        // 規格衝突的處理：F89 ② 把它訂成「右側收合圖示」，但它長得就是一個 ✕，
        // Ryan 2026-07-31 也是照著外觀理解的（「右上角的 x 可以讓他消失」）。
        // 收合本來就有另一條路——F89 ⑤ 的「點本體收合⇄展開」——所以不需要兩個入口做同一件事，
        // 反而是「關閉」一直沒有入口。F89 ② 的那半句由 F100 ③ 取代。
        handle.addView(iconButton(context, R.drawable.ic_rest_close, v -> dismiss(context)));
        return handle;
    }

    private static View buildRingBlock(Context context) {
        FrameLayout block = new FrameLayout(context);
        int size = dp(context, 126);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(size, size);
        lp.gravity = Gravity.CENTER_HORIZONTAL;
        lp.bottomMargin = dp(context, 8);
        block.setLayoutParams(lp);

        ring = new RingView(context, dp(context, 44), dp(context, 8));
        block.addView(ring, new FrameLayout.LayoutParams(size, size));

        LinearLayout center = new LinearLayout(context);
        center.setOrientation(LinearLayout.VERTICAL);
        center.setGravity(Gravity.CENTER);
        FrameLayout.LayoutParams clp = new FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT);
        clp.gravity = Gravity.CENTER;
        block.addView(center, clp);

        countdown = new TextView(context);
        countdown.setTextSize(TypedValue.COMPLEX_UNIT_SP, 30);
        countdown.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        countdown.setTextColor(ACCENT);
        countdown.setGravity(Gravity.CENTER);
        center.addView(countdown);

        status = new TextView(context);
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 9);
        status.setTypeface(Typeface.MONOSPACE);
        status.setTextColor(TEXT_MUTE);
        status.setGravity(Gravity.CENTER);
        center.addView(status);
        return block;
    }

    /**
     * F89 ④：控制鈕維持四顆（Ryan 開工時定的，覆寫設計稿的兩顆）。
     *
     * <p>214dp 寬放不下一列四顆 48dp ＋ 間距，所以排兩列——四顆都保留比「為了排版砍掉兩顆」
     * 重要，±15s 正是健身房裡最常用的微調。
     */
    private static View buildControls(Context context) {
        LinearLayout wrap = new LinearLayout(context);
        wrap.setOrientation(LinearLayout.VERTICAL);
        wrap.setPadding(dp(context, 12), 0, dp(context, 12), dp(context, 8));

        LinearLayout row1 = new LinearLayout(context);
        row1.setOrientation(LinearLayout.HORIZONTAL);
        pauseButton = iconButton(context,
            paused ? R.drawable.ic_rest_play : R.drawable.ic_rest_pause, v -> {
                if (paused) {
                    RestTimerService.resume(context);
                    setPaused(context, false);
                    RestTimerPlugin.emit("resume");
                } else {
                    RestTimerService.pause(context);
                    setPaused(context, true);
                    RestTimerPlugin.emit("pause");
                }
            });
        LinearLayout.LayoutParams pauseLp = pillParams(context, true);
        pauseButton.setLayoutParams(pauseLp);
        GradientDrawable pauseBg = new GradientDrawable();
        pauseBg.setColor(CARD_HI);
        pauseBg.setCornerRadius(dp(context, 22));
        pauseButton.setBackground(pauseBg);
        row1.addView(pauseButton);

        // F100：停止＝停鈴並歸位，**不結束這輪**。視窗留著，人才有一條「回 app 記下一組」的路；
        // 真正讓它消失的是右上角的 ✕（③）。emit 由服務端統一送，這裡不重複送。
        stopButton = pillButton(context, "停止", v -> RestTimerService.halt(context));
        row1.addView(stopButton, pillParams(context, false));

        // F116 ⑤：「再開始」拿掉。視窗改成與計時頁同構的兩態之後，「停止」直接回就緒態、
        // 「完成這組」跟著回來，這顆沒有位置了（Ryan 2026-08-01 拍板）。
        wrap.addView(row1);

        LinearLayout row2 = new LinearLayout(context);
        row2.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        rlp.topMargin = dp(context, BUTTON_GAP_DP);
        row2.setLayoutParams(rlp);
        row2.addView(pillButton(context, "−15s", v -> RestTimerService.adjust(context, -15)),
            pillParams(context, true));
        row2.addView(pillButton(context, "+15s", v -> RestTimerService.adjust(context, 15)),
            pillParams(context, false));
        adjustRow = row2;
        wrap.addView(row2);
        // F100 ②：收合⇄展開會**重建**整棵 view，重建出來的兩顆是預設的 VISIBLE——
        // 已停止的狀態下它們必須維持收起來，否則收合再展開一次，暫停與停止就自己跑回來了
        //（2026-07-31 真機實測抓到；setHalted 只在按下停止的當下跑過一次，蓋不到之後的重建）。
        // ⚠ 這裡**不能**叫 applyStateVisibility()：本方法比 buildLogButton() 先執行，
        // 那時 logButton 還指著舊實例（或 null），新建的那顆會維持預設 VISIBLE。
        // 統一在 buildExpanded 結尾套一次（還有 setHalted 與 setDraft）。
        return wrap;
    }

    /** F89 ⑦：每顆 48dp 高、彼此 8dp——比全域的 44px 嚴，理由見 iconButton 的說明。 */
    private static LinearLayout.LayoutParams pillParams(Context context, boolean first) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            0, dp(context, TOUCH_TARGET_DP), 1f);
        if (!first) lp.setMarginStart(dp(context, BUTTON_GAP_DP));
        return lp;
    }

    /** F104 ②：待記組的 ± 小圓鈕。48dp／間距 8dp 照 F74／F89 ⑦，不放寬。 */
    private static TextView stepButton(Context context, String text, View.OnClickListener click) {
        TextView button = new TextView(context);
        button.setText(text);
        button.setGravity(Gravity.CENTER);
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        button.setTextColor(TEXT_DIM);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(CARD_HI);
        bg.setCornerRadius(dp(context, TOUCH_TARGET_DP) / 2f);
        button.setBackground(bg);
        button.setOnClickListener(click);
        pressFeedback(button);
        return button;
    }

    private static TextView pillButton(Context context, String text, View.OnClickListener click) {
        TextView button = new TextView(context);
        button.setText(text);
        button.setGravity(Gravity.CENTER);
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        button.setTextColor(TEXT_DIM);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(CARD_HI);
        bg.setCornerRadius(dp(context, 22));
        button.setBackground(bg);
        button.setOnClickListener(click);
        pressFeedback(button);
        return button;
    }

    /**
     * F104 ①②：待記組那一行——`{重量} kg × {次數}`，兩側各一顆 ±。
     *
     * <p>② 可調而不是唯讀：唯讀只在「下一組跟上一組完全一樣」時有用，真實訓練裡加重、
     * 掉次數都很常見，唯讀等於每次都要先判斷「這次能不能在視窗做」——規則不確定比功能少更糟。
     *
     * <p>調整**只在視窗內**，不立即寫入任何地方（② 明訂）：它只是還沒送出的草稿，
     * 與 app 內步進器同一個分寸。
     */
    private static View buildDraftRow(Context context) {
        LinearLayout row = new LinearLayout(context);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        rlp.setMargins(dp(context, 12), 0, dp(context, 12), dp(context, BUTTON_GAP_DP));
        row.setLayoutParams(rlp);

        row.addView(stepButton(context, "−", v -> adjustDraft(context, -2.5, 0)),
            new LinearLayout.LayoutParams(dp(context, TOUCH_TARGET_DP), dp(context, TOUCH_TARGET_DP)));

        draftLabel = new TextView(context);
        draftLabel.setGravity(Gravity.CENTER);
        draftLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        draftLabel.setTypeface(Typeface.MONOSPACE); // ① Mono：數字對齊，調整時不會左右跳
        draftLabel.setTextColor(TEXT_DIM);
        draftLabel.setSingleLine(true);
        LinearLayout.LayoutParams llp = new LinearLayout.LayoutParams(
            0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        llp.setMargins(dp(context, 4), 0, dp(context, 4), 0);
        row.addView(draftLabel, llp);

        row.addView(stepButton(context, "+", v -> adjustDraft(context, 2.5, 0)),
            new LinearLayout.LayoutParams(dp(context, TOUCH_TARGET_DP), dp(context, TOUCH_TARGET_DP)));

        LinearLayout wrap = new LinearLayout(context);
        wrap.setOrientation(LinearLayout.VERTICAL);
        wrap.addView(row);

        LinearLayout repsRow = new LinearLayout(context);
        repsRow.setOrientation(LinearLayout.HORIZONTAL);
        repsRow.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams rr = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        rr.setMargins(dp(context, 12), 0, dp(context, 12), dp(context, BUTTON_GAP_DP));
        repsRow.setLayoutParams(rr);
        repsRow.addView(stepButton(context, "−", v -> adjustDraft(context, 0, -1)),
            new LinearLayout.LayoutParams(dp(context, TOUCH_TARGET_DP), dp(context, TOUCH_TARGET_DP)));
        repsLabel = new TextView(context);
        repsLabel.setGravity(Gravity.CENTER);
        repsLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        repsLabel.setTypeface(Typeface.MONOSPACE); // 與重量那列對齊，調整時不左右跳
        repsLabel.setTextColor(TEXT_DIM);
        LinearLayout.LayoutParams rlp2 = new LinearLayout.LayoutParams(
            0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        repsRow.addView(repsLabel, rlp2);
        repsRow.addView(stepButton(context, "+", v -> adjustDraft(context, 0, 1)),
            new LinearLayout.LayoutParams(dp(context, TOUCH_TARGET_DP), dp(context, TOUCH_TARGET_DP)));
        wrap.addView(repsRow);

        // ⑤ 的狀態字：成功／失敗都要看得見，不能靜默切換
        logStatus = new TextView(context);
        logStatus.setGravity(Gravity.CENTER);
        logStatus.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        logStatus.setTextColor(OVER);
        logStatus.setVisibility(View.GONE);
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        slp.setMargins(dp(context, 12), 0, dp(context, 12), dp(context, 6));
        wrap.addView(logStatus, slp);

        draftRow = wrap;
        return wrap;
    }

    private static View draftRow;

    private static boolean hasDraft() {
        return draftWeight >= 0 && draftReps > 0;
    }

    /** ② 重量 ±2.5 下限 0、次數 ±1 下限 1。只動視窗上的草稿，不寫進任何地方。 */
    private static void adjustDraft(Context context, double dw, int dr) {
        if (!hasDraft()) return;
        draftWeight = Math.max(0, Math.round((draftWeight + dw) * 10) / 10.0);
        draftReps = Math.max(1, draftReps + dr);
        paintDraft();
    }

    private static void paintDraft() {
        // 一列一個量：上面重量、下面次數。擠在同一行的話兩組 ± 會分不出各自管哪一個。
        if (draftLabel != null) {
            draftLabel.setText(draftBodyweight
                ? (draftWeight > 0 ? "+" + trimNumber(draftWeight) + " kg" : "自體重")
                : trimNumber(draftWeight) + " kg");
        }
        if (repsLabel != null) repsLabel.setText(draftReps + " 次");
    }

    private static String trimNumber(double value) {
        return value == Math.rint(value)
            ? String.valueOf((long) value)
            : String.valueOf(Math.round(value * 10) / 10.0);
    }

    /**
     * F104 ③⑤：「記下這組」。
     *
     * <p>按下去只做一件事——把視窗上的數值送給前端（④：實際寫入一律由 JS 執行）。
     * 送出後鎖住按鈕並起一個 3 秒門檻：等不到回報就當作沒記到。
     */
    private static View buildLogButton(Context context) {
        logButton = new TextView(context);
        logButton.setGravity(Gravity.CENTER);
        logButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        logButton.setTypeface(null, Typeface.BOLD);
        logButton.setTextColor(ON_ACCENT);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(ACCENT);
        bg.setCornerRadius(dp(context, 22));
        logButton.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(context, TOUCH_TARGET_DP));
        lp.setMargins(dp(context, 12), 0, dp(context, 12), dp(context, BUTTON_GAP_DP));
        logButton.setLayoutParams(lp);
        logButton.setOnClickListener(v -> requestLog(context));
        pressFeedback(logButton);
        paintLogButton();
        // 可見性由 applyStateVisibility() 統一決定（就緒態才出現），這裡不各自判斷
        return logButton;
    }

    private static void requestLog(Context context) {
        if (!hasDraft() || logPending || logQueued) return; // 連按不得記成兩組
        logFailed = false;
        // F125 ③④：uuid 在**排入的那一刻**生成並落地。bridge 事件與開機補送帶同一個值，
        // 伺服器的 client_uuid 冪等去重才會生效（前端原本是寫入當下才生，補送會變成新的一筆）。
        String uuid = PendingLog.enqueue(
            context, draftWeight, draftReps, draftBodyweight, draftExerciseId, draftSetNumber);
        RestTimerPlugin.emitLog(draftWeight, draftReps, uuid);

        // F125 ①：app 在背景時 JS 整條鏈是凍住的（方向 A 已由實機量測判死），
        // 等 3 秒再說「沒記到」是**謊報**——那組其實會在回前景那一刻寫進去。
        // 所以背景不設逾時，改成誠實顯示「已排入」。
        if (!appForeground) {
            logQueued = true;
            paintLogButton();
            paintLogStatus();
            return;
        }

        logPending = true;
        paintLogButton();
        paintLogStatus();
        logTimeout = () -> {
            // ⑤ 等不到回報＝沒記到。**不得**表現得像成功，也不得開新的一輪休息
            //（新的一輪由前端在記錄成功之後才發起，這裡什麼都不做就是「不開」）。
            logPending = false;
            logTimeout = null;
            logFailed = true;
            paintLogButton();
            paintLogStatus();
        };
        MAIN.postDelayed(logTimeout, LOG_TIMEOUT_MS);
    }

    private static void paintLogButton() {
        if (logButton == null) return;
        // F116 ①：與 app 內計時頁一致的文案
        // F125 ①：三態。「已排入」不是暫時狀態——它會一直留到回前景寫入為止。
        logButton.setText(logQueued ? "已排入" : logPending ? "記錄中…" : "完成這組");
        logButton.setAlpha(logQueued || logPending ? 0.6f : 1f);
    }

    private static void paintLogStatus() {
        if (logStatus == null) return;
        if (logQueued) {
            // F125 ①：誠實講出實際會發生的事，不假裝已經寫進資料庫
            logStatus.setText("已排入，回 app 後記錄");
            logStatus.setVisibility(View.VISIBLE);
        } else if (logFailed) {
            logStatus.setText("沒記到——回 app 記下一組");
            logStatus.setVisibility(View.VISIBLE);
        } else {
            logStatus.setVisibility(View.GONE);
        }
    }

    /** F89 ④：主按鈕——把 app 拉回前景（超時時轉 --over，與圓環同步）。 */
    private static View buildMainButton(Context context) {
        mainButton = new TextView(context);
        mainButton.setText("回 app 記下一組");
        mainButton.setGravity(Gravity.CENTER);
        mainButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        // F104 ⑥：有「記下這組」在的時候，回 app 退居次要——兩顆同等大小的主按鈕
        // 會讓人每次都要選一次。沒有待記組時（舊版前端）它仍是唯一的主按鈕，維持琥珀。
        boolean secondary = hasDraft();
        mainButton.setTextColor(secondary ? TEXT_DIM : ON_ACCENT);
        mainButton.setTypeface(null, secondary ? Typeface.NORMAL : Typeface.BOLD);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(context, TOUCH_TARGET_DP));
        lp.setMargins(dp(context, 12), 0, dp(context, 12), dp(context, 12));
        mainButton.setLayoutParams(lp);
        mainButton.setOnClickListener(v -> {
            Intent intent = context.getPackageManager()
                .getLaunchIntentForPackage(context.getPackageName());
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                context.startActivity(intent);
            }
            // F110：把 app 拉到前景**不等於**停在對的那一頁——SINGLE_TOP 只是把既有的
            // Activity 叫回來，WebView 停在哪就是哪。這顆鈕的字面意思是「回去記 A 的下一組」，
            // 所以還要請前端導到那輪休息所屬動作的計時頁。
            //
            // 導頁交前端做：哪一頁、動作物件在哪、離線時怎麼退，全都是前端才知道的事
            // （原生只有一個 id）。與 F103 ⑤ 同一個分寸——原生回報「使用者按了什麼」，
            // 實際的狀態變更在 JS。
            RestTimerPlugin.emit("focus");
        });
        pressFeedback(mainButton);
        return mainButton;
    }

    /** F74 ④：按下時給回饋，且只改外觀不動版面（改尺寸會讓旁邊的鈕跟著跳）。 */
    private static void pressFeedback(View button) {
        button.setOnTouchListener((v, event) -> {
            switch (event.getAction()) {
                case MotionEvent.ACTION_DOWN:
                    v.setAlpha(0.5f);
                    break;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    v.setAlpha(1f);
                    break;
                default:
                    break;
            }
            return false; // 不吃掉事件，OnClickListener 照常收得到
        });
    }

    /**
     * F74／F89 ⑦：每顆按鈕的可觸控區域固定 48dp × 48dp，彼此間距 8dp。
     *
     * <p>加大的理由不是規範好看：使用情境是**剛做完一組、手是濕的、站在健身房裡**，
     * 而按錯收合與停止的後果完全不同。
     */
    private static ImageView iconButton(Context context, int drawableRes,
                                        View.OnClickListener onClick) {
        ImageView button = new ImageView(context);
        button.setImageResource(drawableRes);
        // F76 ④：用 tint 上色——vector drawable 吃得到，emoji 吃不到（那正是換掉它的原因）
        button.setImageTintList(android.content.res.ColorStateList.valueOf(TEXT_DIM));
        button.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
        int inset = dp(context, 12); // 48dp 觸控區裡放 24dp 圖示
        button.setPadding(inset, inset, inset, inset);
        button.setLayoutParams(new LinearLayout.LayoutParams(
            dp(context, TOUCH_TARGET_DP), dp(context, TOUCH_TARGET_DP)));
        pressFeedback(button);
        button.setOnClickListener(onClick);
        return button;
    }

    private static WindowManager.LayoutParams buildParams(Context context) {
        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE; // minSdk 24：8.0 以下沒有前者
        // ⚠ 視窗根 view 的尺寸由**這裡**決定——設在 root 的 LinearLayout.LayoutParams 會被忽略。
        // 第一版把 214dp 設在 root 上，實機量出來只有約 120dp 寬，「LIFT·LOG」被擠成三行
        // 才發現（2026-07-30 真機）。收合態維持 WRAP_CONTENT（圓自己有固定尺寸）。
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
            expanded ? dp(context, 214) : WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            // NOT_FOCUSABLE：下層 app 照常收得到按鍵與輸入法，overlay 只吃自己身上的觸控
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        // F89 ⑤：回到上次拖到的位置
        lp.x = prefs(context).getInt(KEY_X, dp(context, 16));
        lp.y = prefs(context).getInt(KEY_Y, dp(context, 120));
        return lp;
    }

    /** F89 ①③：圓環。收合與展開只差半徑與線寬，所以是同一個 view。 */
    private static final class RingView extends View {
        private final Paint track = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint arc = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final int radius;
        private float progress = 1f; // 1＝滿（剛開始休息）

        RingView(Context context, int radiusPx, int strokePx) {
            super(context);
            radius = radiusPx;
            track.setStyle(Paint.Style.STROKE);
            track.setStrokeWidth(strokePx);
            track.setColor(LINE);
            arc.setStyle(Paint.Style.STROKE);
            arc.setStrokeWidth(strokePx);
            arc.setStrokeCap(Paint.Cap.ROUND);
            arc.setColor(ACCENT);
        }

        void setProgress(float ratio) {
            progress = ratio;
            invalidate();
        }

        void setOver(boolean over) {
            arc.setColor(over ? OVER : ACCENT);
            invalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            float cx = getWidth() / 2f;
            float cy = getHeight() / 2f;
            RectF box = new RectF(cx - radius, cy - radius, cx + radius, cy + radius);
            canvas.drawCircle(cx, cy, radius, track);
            // 從 12 點鐘開始順時針；剩越少畫越短（與 web 版 dashoffset 的語意一致）
            canvas.drawArc(box, -90f, 360f * progress, false, arc);
        }
    }

    /**
     * F89 ⑤：拖曳移動 ＋ 點擊切換兩態。
     *
     * <p>兩者共用同一個 touch listener，靠**位移量**分辨：移動超過系統的 touchSlop 就是拖曳，
     * 否則放開時當成點擊。用長按判定會讓「想拖」的手指先等 500ms，健身房裡那半秒很煩。
     */
    private static final class DragListener implements View.OnTouchListener {
        private final Context context;
        private final int slop;
        private int startX;
        private int startY;
        private float touchX;
        private float touchY;
        private boolean dragged;

        DragListener(Context context) {
            this.context = context;
            this.slop = ViewConfiguration.get(context).getScaledTouchSlop();
        }

        @Override
        public boolean onTouch(View v, MotionEvent event) {
            switch (event.getAction()) {
                case MotionEvent.ACTION_DOWN:
                    startX = params.x;
                    startY = params.y;
                    touchX = event.getRawX();
                    touchY = event.getRawY();
                    dragged = false;
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    int dx = (int) (event.getRawX() - touchX);
                    int dy = (int) (event.getRawY() - touchY);
                    if (!dragged && Math.abs(dx) < slop && Math.abs(dy) < slop) return true;
                    dragged = true;
                    params.x = startX + dx;
                    params.y = startY + dy;
                    try {
                        windowManager(context).updateViewLayout(v, params);
                    } catch (Exception e) {
                        /* view 已被移除：忽略這次拖曳 */
                    }
                    return true;
                }
                case MotionEvent.ACTION_UP:
                    if (dragged) {
                        // F89 ⑤：位置持久化。設計稿寫 localStorage，但這是系統 overlay、
                        // 不經 WebView，那邊的儲存碰不到
                        prefs(context).edit()
                            .putInt(KEY_X, params.x).putInt(KEY_Y, params.y).apply();
                    } else {
                        toggleExpanded(context);
                    }
                    return true;
                default:
                    return false;
            }
        }
    }
}
