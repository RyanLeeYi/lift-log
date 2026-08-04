package com.ryanleeyi.liftlog;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.UUID;

/**
 * F131 ⑥：原生側送不出去的組，存在這裡等重送。
 *
 * <p><b>與 F125 的 PendingLog 差在哪。</b>PendingLog 只有一格，而且是「等回 app 才寫」；
 * 舊的還在就丟掉新的（PendingLog.java:53），因為當時視窗按一次就鎖住、按不到第二次。
 * F131 讓視窗按完當場開新一輪，第二組按得到——所以這裡**必須支援多筆**。
 *
 * <p><b>兩種狀態，不是狀態機。</b>{@code pending}＝還沒送成功（離線、5xx、逾時），
 * {@code failed}＝永久性失敗（4xx／401），重試沒有意義、要讓使用者看到。
 * 這兩個字刻意與前端 queue.js 的用詞一致——回 app 後併進同一個
 * 「同步失敗 N 組」橫幅（app.js:372），不新增 UI。
 *
 * <p><b>不得被 ✕／停止清空。</b>那是現行 F125 ⑤ 的資料遺失來源
 * （RestTimerService.java 的 ACTION_STOP 會清 PendingLog）。這裡的清除只有兩個時機：
 * 寫入成功、使用者在 app 內明確捨棄。停止一輪休息不代表那組沒做。
 *
 * <p>存明文 SharedPreferences：內容是訓練資料，不是憑證（憑證在 {@link SecureStore}）。
 */
final class SetOutbox {

    private static final String TAG = "SetOutbox";
    private static final String PREFS = "liftlog_set_outbox";
    private static final String KEY_ENTRIES = "entries";

    static final String STATUS_PENDING = "pending";
    static final String STATUS_FAILED = "failed";

    /**
     * 所有「讀→改→寫」都要在這把鎖裡（codex review P2）。
     *
     * <p>{@code enqueue()} 跑在 UI 執行緒（使用者按下的那一刻），
     * {@code markSynced/markFailed} 跑在上傳的 IO 執行緒。沒有鎖的話，HTTP 回應那一側
     * 讀出陣列、還沒寫回時使用者剛好完成下一組，寫回就會把新那筆整個蓋掉——
     * 靜默少一組，正是這條 feature 要消滅的東西。
     */
    private static final Object LOCK = new Object();

    private SetOutbox() {}

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** 讀出目前的佇列；壞掉的內容一律當空的（絕不讓解析錯誤擋住新的一組落地）。 */
    static JSONArray all(Context context) {
        String raw = prefs(context).getString(KEY_ENTRIES, null);
        if (raw == null) return new JSONArray();
        try {
            return new JSONArray(raw);
        } catch (JSONException e) {
            Log.w(TAG, "outbox 內容毀損，視為空", e);
            return new JSONArray();
        }
    }

    private static void write(Context context, JSONArray entries) {
        prefs(context).edit().putString(KEY_ENTRIES, entries.toString()).apply();
    }

    /**
     * 排入一組，回傳 client_uuid。
     *
     * <p>uuid 在**按下的那一刻**生成（F125 ④ 不變）：重送與前端補送帶同一個值，
     * 伺服器對 client_uuid 的冪等去重才會生效（services/workouts.py:285）。
     *
     * @param restSeconds 剛結束那一輪的實際休息秒數；沒有就傳負數（不送這個欄位）。
     *     F129 花了四輪真機在保這個值，原生自己寫入時不補上就等於讓它回歸成 null。
     */
    static String enqueue(
        Context context, double weight, int reps, int exerciseId, int workoutId, int restSeconds
    ) {
        String uuid = UUID.randomUUID().toString();
        synchronized (LOCK) {
            JSONArray next = all(context);
            try {
                JSONObject entry = new JSONObject();
                entry.put("uuid", uuid);
                entry.put("workoutId", workoutId);
                entry.put("exerciseId", exerciseId);
                entry.put("weight", weight);
                entry.put("reps", reps);
                entry.put("restSeconds", restSeconds);
                entry.put("status", STATUS_PENDING);
                entry.put("queuedAt", System.currentTimeMillis());
                next.put(entry);
            } catch (JSONException e) {
                Log.e(TAG, "排入失敗", e);
                return uuid;
            }
            write(context, next);
        }
        return uuid;
    }

    /** 依 uuid 換掉一筆的狀態；{@code null} 代表移除（寫入成功）。 */
    private static void replace(Context context, String uuid, String status) {
        synchronized (LOCK) {
            replaceLocked(context, uuid, status);
        }
    }

    private static void replaceLocked(Context context, String uuid, String status) {
        JSONArray current = all(context);
        JSONArray next = new JSONArray();
        for (int i = 0; i < current.length(); i++) {
            JSONObject entry = current.optJSONObject(i);
            if (entry == null) continue;
            if (!uuid.equals(entry.optString("uuid"))) {
                next.put(entry);
                continue;
            }
            if (status == null) continue; // 移除
            try {
                entry.put("status", status);
            } catch (JSONException e) {
                Log.w(TAG, "改狀態失敗", e);
            }
            next.put(entry);
        }
        write(context, next);
    }

    /** 寫進資料庫了（含冪等命中）→ 移出佇列。 */
    static void markSynced(Context context, String uuid) {
        replace(context, uuid, null);
    }

    /** 永久性失敗（4xx／401）→ 留著但標 failed，供回 app 後回報與手動捨棄。 */
    static void markFailed(Context context, String uuid) {
        replace(context, uuid, STATUS_FAILED);
    }

    static int count(Context context, String status) {
        JSONArray entries = all(context);
        int n = 0;
        for (int i = 0; i < entries.length(); i++) {
            JSONObject entry = entries.optJSONObject(i);
            if (entry != null && status.equals(entry.optString("status"))) n++;
        }
        return n;
    }

    static boolean hasPending(Context context) {
        return count(context, STATUS_PENDING) > 0;
    }

    /** 使用者在 app 內明確捨棄失敗的那些（對應 app.js:372 的「點此捨棄」）。 */
    static void discardFailed(Context context) {
        synchronized (LOCK) {
            discardFailedLocked(context);
        }
    }

    private static void discardFailedLocked(Context context) {
        JSONArray current = all(context);
        JSONArray next = new JSONArray();
        for (int i = 0; i < current.length(); i++) {
            JSONObject entry = current.optJSONObject(i);
            if (entry != null && !STATUS_FAILED.equals(entry.optString("status"))) next.put(entry);
        }
        write(context, next);
    }
}
