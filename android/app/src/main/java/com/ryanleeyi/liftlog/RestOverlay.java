package com.ryanleeyi.liftlog;

import android.content.Context;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
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
    private static WindowManager.LayoutParams params;

    private RestOverlay() {}

    /** Android 6 起 SYSTEM_ALERT_WINDOW 是「特殊權限」，宣告了也要使用者逐 app 手動開。 */
    static boolean permitted(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true;
        return Settings.canDrawOverlays(context);
    }

    static synchronized void show(Context context, int seconds) {
        if (!permitted(context)) return; // ②：沒授權就安靜不畫，通知列倒數照常（不當機不空白）
        if (view != null) {
            update(seconds);
            return;
        }
        try {
            view = buildView(context);
            params = buildParams(context);
            windowManager(context).addView(view, params);
            update(seconds);
        } catch (Exception e) {
            // OEM（例如 Samsung）可能在授權之外再擋一層，或 token 失效 —— 加不上就退回只有通知列
            view = null;
            label = null;
        }
    }

    static synchronized void update(int remainingSeconds) {
        if (label == null) return;
        label.setText(String.format("⏱ %d:%02d", remainingSeconds / 60, remainingSeconds % 60));
    }

    /** ④：移除 view。重複呼叫安全——ACTION_STOP、onFinish、onDestroy 都會走到這裡。 */
    static synchronized void hide(Context context) {
        if (view == null) return;
        try {
            windowManager(context).removeViewImmediate(view);
        } catch (Exception e) {
            /* 已經被移除或 window token 失效：目的已達成 */
        }
        view = null;
        label = null;
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
        root.setPadding(dp(context, 14), dp(context, 8), dp(context, 8), dp(context, 8));

        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor("#E6111827"));
        bg.setCornerRadius(dp(context, 20));
        root.setBackground(bg);

        label = new TextView(context);
        label.setTextColor(Color.WHITE);
        label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        root.addView(label);

        TextView close = new TextView(context);
        close.setText("✕");
        close.setTextColor(Color.parseColor("#9CA3AF"));
        close.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        close.setPadding(dp(context, 12), 0, dp(context, 4), 0);
        // ③：關掉的是「顯示」不是「倒數」——通知列的倒數與提醒照常走完
        close.setOnClickListener(v -> hide(context));
        root.addView(close);

        root.setOnTouchListener(new DragListener(context));
        return root;
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
