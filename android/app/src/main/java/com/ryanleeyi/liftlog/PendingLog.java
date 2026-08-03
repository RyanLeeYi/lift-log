package com.ryanleeyi.liftlog;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.UUID;

/**
 * F125 ③：排入但還沒寫進資料庫的那一組，存在原生這一側。
 *
 * <p><b>為什麼需要它。</b>在 app 外按「完成這組」時，事件送得到 Capacitor bridge，
 * 但 JS 整條鏈要等回前景才執行（2026-08-01 實機量到 19.25 秒的落差，方向 A 已判死）。
 * 正常情況那個排隊中的事件會在回前景時自己跑完——**但如果行程在那之前被系統殺掉，
 * 事件就跟著沒了**，而視窗已經對使用者說過「已排入」。這個檔案就是那句話的保證。
 *
 * <p><b>去重的關鍵在 uuid（④）。</b>`client_uuid` 一定要在**排入的那一刻**生成、
 * 兩條路（bridge 事件與開機補送）帶同一個值。前端原本是在寫入當下才
 * `crypto.randomUUID()`，那樣補送會變成新的一筆，伺服器的冪等去重完全不會生效。
 *
 * <p><b>不存的東西。</b>累度（rpe）不存——F104 ⑦ 明訂就地記的組留 null。
 * 休息秒數也不存：它來自前端的 `pendingRestSeconds`，跟著 F66 的快照一起還原，
 * 在這裡存第二份只會多一個會走鐘的來源。
 */
final class PendingLog {

    private static final String PREFS = "liftlog_pending_log";
    private static final String KEY_UUID = "uuid";
    private static final String KEY_WEIGHT = "weight";
    private static final String KEY_REPS = "reps";
    private static final String KEY_BODYWEIGHT = "bodyweight";
    private static final String KEY_EXERCISE_ID = "exercise_id";
    private static final String KEY_SET_NUMBER = "set_number";

    private PendingLog() {}

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /**
     * 排入一組，回傳這一組的 client_uuid。
     *
     * <p>同一時間只保留一組：視窗上一次只有一個待記組，而且記完就會開新的一輪。
     * 舊的還在就代表上一次補送還沒成功——直接覆蓋會弄丟它，所以**保留舊的、不覆蓋**，
     * 並回傳舊的 uuid（呼叫端因此仍拿得到一個可用的 uuid，兩次按下不會變成兩筆）。
     */
    static String enqueue(
        Context context, double weight, int reps, boolean bodyweight,
        int exerciseId, int setNumber
    ) {
        SharedPreferences p = prefs(context);
        String existing = p.getString(KEY_UUID, null);
        if (existing != null) return existing;
        String uuid = UUID.randomUUID().toString();
        p.edit()
            .putString(KEY_UUID, uuid)
            .putFloat(KEY_WEIGHT, (float) weight)
            .putInt(KEY_REPS, reps)
            .putBoolean(KEY_BODYWEIGHT, bodyweight)
            .putInt(KEY_EXERCISE_ID, exerciseId)
            .putInt(KEY_SET_NUMBER, setNumber)
            .apply();
        return uuid;
    }

    /** 有沒有待補送的一組。 */
    static boolean has(Context context) {
        return prefs(context).getString(KEY_UUID, null) != null;
    }

    static String uuid(Context context) {
        return prefs(context).getString(KEY_UUID, null);
    }

    static double weight(Context context) {
        return prefs(context).getFloat(KEY_WEIGHT, -1f);
    }

    static int reps(Context context) {
        return prefs(context).getInt(KEY_REPS, -1);
    }

    static boolean bodyweight(Context context) {
        return prefs(context).getBoolean(KEY_BODYWEIGHT, false);
    }

    static int exerciseId(Context context) {
        return prefs(context).getInt(KEY_EXERCISE_ID, -1);
    }

    static int setNumber(Context context) {
        return prefs(context).getInt(KEY_SET_NUMBER, -1);
    }

    /** F125 ⑤：三個清除時機共用這一支——寫入成功、補送成功、這輪被收掉。 */
    static void clear(Context context) {
        prefs(context).edit().clear().apply();
    }
}
