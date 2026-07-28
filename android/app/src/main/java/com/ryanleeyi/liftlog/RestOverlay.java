package com.ryanleeyi.liftlog;

import android.content.Context;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * F64：浮在其他 app 之上的休息倒數小視窗。
 *
 * <p>秒數由 {@link RestTimerService} 的原生 CountDownTimer 推進來（acceptance ①）——
 * overlay 的使用情境本來就是「你人在別的 app 裡」，那時 WebView 一定在背景、JS 計時器被節流，
 * 所以絕不能讓前端每秒 call 過來畫。
 *
 * <p><b>為什麼握把是 static</b>（acceptance ④，F63 ③ 的教訓）：倒數自然歸零後服務已 stopSelf，
 * 之後送進來的 ACTION_STOP 會建立一個**全新的服務實例**。握把若放在實例欄位，新實例手上是 null，
 * 舊的 view 就永遠掛在螢幕上關不掉。window 由 WindowManager 持有、生命週期跟著 process，
 * 所以握把也要跟著 process 走。
 */
final class RestOverlay {

    private static View view;
    private static TextView label;
    private static ImageView pauseButton; // F71 ①：暫停／繼續兩態共用同一顆
    private static ImageView stopButton; // F73：鬧鐘響著時要轉警示色
    /** F71：暫停狀態。兩邊（app 內卡片與這裡）必須顯示一致，否則使用者不知道該信誰。 */
    private static boolean paused;
    private static WindowManager.LayoutParams params;
    /**
     * 使用者在**這一輪休息中**按過 ✕。
     *
     * <p>沒有這個旗標的話：關掉 overlay 後只要改休息秒數（前端會重下一次 ACTION_START），
     * overlay 就自己跑回來，等於吃掉使用者剛表達的意圖（2026-07-28 Codex review P2）。
     * 旗標在服務停止／倒數結束時清掉——那是新一輪休息，重新顯示才合理。
     */
    private static boolean dismissed;

    // ---------- F69：顯示條件的四個輸入 ----------
    //
    // 規則收斂在 shouldShow() 一處（acceptance ①）。散在各呼叫點的話，
    // 「兩邊都沒有」這種最糟的失敗（⑥）會從某條沒人想到的路徑漏出來。

    /** 這輪休息是否還在跑（服務啟動時 true，停止／歸零時 false）。 */
    private static boolean active;
    /** app 是否在前景。來源是 ActivityLifecycleCallbacks，不是 WebView（②）。 */
    private static boolean appForeground;
    /** 當前畫面看不看得到 app 內的 REST 卡片。由前端在切畫面時回報（③）。 */
    private static boolean restCardVisible;
    private static int remaining;

    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    /** F74：Android 的最小觸控目標。視覺上的圖示比這小，但可按的範圍不能小於它。 */
    private static final int TOUCH_TARGET_DP = 48;
    private static final int BUTTON_GAP_DP = 8;

    private RestOverlay() {}

    /**
     * 所有進入點都先繞到 main thread。
     *
     * <p>2026-07-28 模擬器實測抓到的 crash：Capacitor 的 plugin 方法跑在 `CapacitorPlugins`
     * 執行緒，F69 的 setRestCardVisible 從那裡建立 view，之後服務的 CountDownTimer 在 main
     * thread 更新同一個 view →「Only the original thread that created a view hierarchy can
     * touch its views」直接閃退。view 一律只能在 main thread 碰，所以收斂在這一個閘門，
     * 而不是要求每個呼叫端自己記得（記不住的那次就是 crash）。
     */
    private static void onMain(Runnable action) {
        if (Looper.myLooper() == Looper.getMainLooper()) action.run();
        else MAIN.post(action);
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
     */
    private static boolean shouldShow() {
        if (!active || dismissed) return false;
        return !(appForeground && restCardVisible);
    }

    /** 服務啟動／停止這輪休息。 */
    static void setActive(Context context, boolean value, int seconds) {
        onMain(() -> {
            active = value;
            if (value) remaining = seconds;
            apply(context);
        });
    }

    /** ②：app 切到前景／背景。 */
    static void setAppForeground(Context context, boolean value) {
        onMain(() -> {
            appForeground = value;
            if (value && restCardVisible) dismissed = false; // F71 ⑩：同上
            apply(context);
        });
    }

    /** ③：前端切畫面時回報 REST 卡片是否可見。 */
    static void setRestCardVisible(Context context, boolean value) {
        onMain(() -> {
            restCardVisible = value;
            // F71 ⑩：✕ 只是「現在別擋我」，效力到你回頭看見 app 內的倒數為止——
            // 那一刻解除，之後再離開計時頁就會再出現。解除當下不會彈出來，
            // 因為此時 shouldShow() 本來就是 false（卡片可見）。
            if (value && appForeground) dismissed = false;
            apply(context);
        });
    }

    /** F71 ①：暫停狀態變了——換掉按鈕圖示。狀態本身由服務與前端各自維護。 */
    static void setPaused(Context context, boolean value) {
        onMain(() -> {
            paused = value;
            if (pauseButton != null) {
                pauseButton.setImageResource(paused ? R.drawable.ic_rest_play : R.drawable.ic_rest_pause);
            }
            applyAlarmTint(remaining < 0 && !paused); // F73 ③：暫停中不算「響著」
            apply(context);
        });
    }

    static void update(Context context, int remainingSeconds) {
        onMain(() -> {
            remaining = remainingSeconds;
            if (label != null) label.setText(text(remainingSeconds));
            // F73 ①②③：鬧鐘響著（超時且非暫停）時停止鈕轉警示色——人在別的 app 裡時，
            // 這顆小視窗是唯一看得到的東西，得指出該點哪裡。
            applyAlarmTint(remainingSeconds < 0 && !paused);
            apply(context);
        });
    }

    /**
     * F73 ②：警示色只在響的時候上，停止／繼續之後回復。
     *
     * <p><b>為什麼改底色而不是文字色</b>（2026-07-28 模擬器實測抓到）：⏹ 是 **emoji**，
     * 而 emoji 是彩色字形，`setTextColor()` 對它完全沒有作用——第一版寫成改文字色，
     * 螢幕上什麼都沒變。底色是畫在 view 上的，與字形種類無關。
     */
    private static void applyAlarmTint(boolean alarming) {
        if (stopButton == null) return;
        if (!alarming) {
            stopButton.setBackground(null);
            return;
        }
        GradientDrawable highlight = new GradientDrawable();
        highlight.setColor(Color.parseColor("#FF5252"));
        highlight.setCornerRadius(dp(stopButton.getContext(), 24)); // F74：配合 48dp 的方形觸控區
        stopButton.setBackground(highlight);
    }

    /** 使用者按 ✕：關掉顯示，並記住這輪休息不要再自己冒出來（倒數照常走完）。 */
    static void dismiss(Context context) {
        onMain(() -> {
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

    /** F72 ①：歸零後不消失而是繼續數，負數＝超時（-0:07），與 app 內 REST 卡片一致。 */
    private static String text(int seconds) {
        int abs = Math.abs(seconds);
        String sign = seconds < 0 ? "-" : "";
        return String.format("⏱ %s%d:%02d", sign, abs / 60, abs % 60);
    }

    private static void attach(Context context) {
        if (!permitted(context)) return; // 沒授權就安靜不畫，通知列倒數照常（不當機不空白）
        if (view != null) {
            label.setText(text(remaining));
            return;
        }
        try {
            view = buildView(context);
            params = buildParams(context);
            windowManager(context).addView(view, params);
            label.setText(text(remaining));
        } catch (Exception e) {
            // OEM（例如 Samsung）可能在授權之外再擋一層，或 token 失效 —— 加不上就退回只有通知列
            view = null;
            label = null;
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
            restCardVisible = false;
            detach(context);
        });
    }

    /** 只收起 window，不動狀態——F69 的「暫時藏起來」（這輪休息還在跑）。 */
    private static void detach(Context context) {
        if (view == null) return;
        try {
            windowManager(context).removeViewImmediate(view);
        } catch (Exception e) {
            /* 已經被移除或 window token 失效：目的已達成 */
        }
        view = null;
        label = null;
        pauseButton = null;
        stopButton = null;
        params = null;
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
        LinearLayout root = new LinearLayout(context);
        root.setOrientation(LinearLayout.HORIZONTAL);
        root.setGravity(Gravity.CENTER_VERTICAL);
        // F74 ③：按鈕自己已經有 48dp 高，root 的垂直 padding 收掉，
        // 免得視窗整體變成一大塊——維持單列藥丸造型
        root.setPadding(dp(context, 14), dp(context, 2), dp(context, 6), dp(context, 2));

        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor("#E6111827"));
        bg.setCornerRadius(dp(context, 26)); // F74：高度變大，圓角跟著調才還是藥丸
        root.setBackground(bg);

        label = new TextView(context);
        label.setTextColor(Color.WHITE);
        label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        root.addView(label);

        // F71 ①：暫停／繼續。原生先動手（服務要立刻停），再回報前端讓畫面跟上（⑥）
        pauseButton = iconButton(context, paused ? R.drawable.ic_rest_play : R.drawable.ic_rest_pause, v -> {
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
        root.addView(pauseButton);

        // F71 ④：停止＝結束這段休息（等同繼續下一組），通知與視窗一起收掉
        stopButton = iconButton(context, R.drawable.ic_rest_stop, v -> {
            RestTimerPlugin.emit("stop");
            RestTimerService.stop(context);
        });
        root.addView(stopButton);

        // F64 ③／F71 ⑤：✕ 關掉的是「顯示」不是「倒數」——通知列的倒數與提醒照常走完
        root.addView(iconButton(context, R.drawable.ic_rest_close, v -> dismiss(context)));

        root.setOnTouchListener(new DragListener(context));
        return root;
    }

    /**
     * F74：每顆按鈕的可觸控區域固定 48dp × 48dp（Android 標準），彼此間距 8dp。
     *
     * <p>加大的理由不是規範好看：使用情境是**剛做完一組、手是濕的、站在健身房裡**，
     * 而按錯 ✕（只收起顯示）與 ⏹（結束整段休息）的後果完全不同。原本 16sp 文字加
     * 上下 4dp padding 只有約 29dp 高，兩顆之間又只隔 10dp。
     */
    private static ImageView iconButton(Context context, int drawableRes, View.OnClickListener onClick) {
        ImageView button = new ImageView(context);
        button.setImageResource(drawableRes);
        // F76 ④：用 tint 上色——vector drawable 吃得到，emoji 吃不到（那正是換掉它的原因）
        button.setImageTintList(android.content.res.ColorStateList.valueOf(
            Color.parseColor("#9CA3AF")));
        button.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
        int inset = dp(context, 12); // 48dp 觸控區裡放 24dp 圖示
        button.setPadding(inset, inset, inset, inset);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            dp(context, TOUCH_TARGET_DP), dp(context, TOUCH_TARGET_DP));
        lp.setMarginStart(dp(context, BUTTON_GAP_DP));
        button.setLayoutParams(lp);
        // F74 ④：按下時給回饋，且只改外觀不動版面（改尺寸會讓旁邊的鈕跟著跳）
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
        button.setOnClickListener(onClick);
        return button;
    }

    private static WindowManager.LayoutParams buildParams(Context context) {
        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE; // minSdk 24：8.0 以下沒有前者
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            // NOT_FOCUSABLE：下層 app 照常收得到按鍵與輸入法，overlay 只吃自己身上的觸控
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        lp.x = dp(context, 16);
        lp.y = dp(context, 120);
        return lp;
    }

    /** ⑤：拖曳移動。手指按下時記錄起點，移動時直接改 params 並 updateViewLayout。 */
    private static final class DragListener implements View.OnTouchListener {
        private final Context context;
        private int startX;
        private int startY;
        private float touchX;
        private float touchY;

        DragListener(Context context) {
            this.context = context;
        }

        @Override
        public boolean onTouch(View v, MotionEvent event) {
            switch (event.getAction()) {
                case MotionEvent.ACTION_DOWN:
                    startX = params.x;
                    startY = params.y;
                    touchX = event.getRawX();
                    touchY = event.getRawY();
                    return true;
                case MotionEvent.ACTION_MOVE:
                    params.x = startX + (int) (event.getRawX() - touchX);
                    params.y = startY + (int) (event.getRawY() - touchY);
                    try {
                        windowManager(context).updateViewLayout(v, params);
                    } catch (Exception e) {
                        /* view 已被移除：忽略這次拖曳 */
                    }
                    return true;
                default:
                    return false; // 讓 ACTION_UP 傳下去，關閉鈕的 click 才收得到
            }
        }
    }
}
