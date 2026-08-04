package com.ryanleeyi.liftlog;

import android.content.Context;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * F131 ①：把 {@link SetOutbox} 裡的組實際送到伺服器。
 *
 * <p><b>為什麼原生可以直接打。</b>休息中 {@code RestTimerService} 是前景服務，
 * Doze 與背景網路限制不擋它；而 F125 那條「等回前景」的路實測落差 19.25 秒。
 *
 * <p><b>為什麼開第二條寫入路徑是安全的。</b>伺服器對 {@code client_uuid} 冪等
 * （app/services/workouts.py:285）：原生寫過、前端之後又補送同一顆 uuid，回的是同一列。
 * 沒有這個前提就不該有這個檔案。
 *
 * <p><b>組號不在這裡算。</b>{@code set_number} 省略時由伺服器決定
 * （F131 ③，app/services/workouts.py 的 {@code _next_set_number}）。
 * F32 的規則只留一份，不在第二個語言重寫。
 *
 * <p><b>錯誤分類與前端 queue.js 一致</b>（那邊的註解是這套分類的來源）：
 * 連不上／5xx／逾時＝留著再試；4xx＝永久性失敗，標 failed 不無限重試；
 * 401 也標 failed——原生分不出是 token 錯還是伺服器出包，交給 JS 的 guard() 處理。
 */
final class SetUploader {

    private static final String TAG = "SetUploader";
    private static final int CONNECT_TIMEOUT_MS = 10000;
    private static final int READ_TIMEOUT_MS = 15000;

    /** 單執行緒：重送要照入列順序，且同一時間只有一個人在動 outbox。 */
    private static final ExecutorService IO = Executors.newSingleThreadExecutor();

    private SetUploader() {}

    /** 憑證備妥了沒——沒有的話原生寫入路徑整條不可用（呼叫端要退回 F125 的「回 app 再寫」）。 */
    static boolean ready(Context context) {
        return SecureStore.token(context) != null && SecureStore.baseUrl(context) != null;
    }

    /** 觸發一次重送（F131 ⑥-1 的三個觸發點都呼叫這支）。沒東西可送就什麼都不做。 */
    static void flush(Context context) {
        flush(context, null);
    }

    /**
     * @param done 送完（或判定不能送）之後在 IO 執行緒上回呼；null 代表不必回報。
     *     前端的對帳流程要等這個回呼，否則 GET 會取不到剛送出去的組（codex review P1）。
     */
    static void flush(Context context, Runnable done) {
        Context app = context.getApplicationContext();
        IO.execute(() -> {
            try {
                flushBlocking(app);
            } finally {
                if (done != null) done.run();
            }
        });
    }

    private static void flushBlocking(Context context) {
        // 沒有待送的也要回報一次現況（review MEDIUM）：使用者在 app 按「捨棄」之後，
        // 視窗那份 static 計數仍是舊值，早退會讓「沒記到 N 組」永遠掛在上面。
        if (!SetOutbox.hasPending(context)) {
            publishState(context, false);
            return;
        }
        String token = SecureStore.token(context);
        String baseUrl = SecureStore.baseUrl(context);
        if (token == null || baseUrl == null) {
            // 還沒拿到憑證（JS 從沒推過、或加密儲存壞掉）→ 留著等下次。
            // ⚠ 這條路不該有東西可送：RestOverlay 在排入**之前**就會檢查 ready()，
            // 不備妥就整條退回 F125（codex review P2——bridge 不公開 payload，
            // 卡在這裡的組前端補不了，會永久停在 pending）。
            Log.w(TAG, "沒有可用的憑證，跳過這次重送");
            return;
        }

        JSONArray entries = SetOutbox.all(context);
        boolean unauthorized = false;
        for (int i = 0; i < entries.length(); i++) {
            JSONObject entry = entries.optJSONObject(i);
            if (entry == null) continue;
            if (!SetOutbox.STATUS_PENDING.equals(entry.optString("status"))) continue;

            int status = post(baseUrl, token, entry);
            String uuid = entry.optString("uuid");
            if (status == 200 || status == 201) {
                SetOutbox.markSynced(context, uuid);
            } else if (status == 401) {
                // ⚠ 401 **不是**永久性失敗（review CRITICAL）。標 failed 就再也送不出去
                // （flushBlocking 只送 pending，沒有 failed → pending 的回復路徑），
                // 而 token 過期是完全可恢復的——重新登入後這些組本來就該送出去。
                // 與前端一致：queue.js:88 對 401 是「上拋、佇列原封保留」。
                unauthorized = true;
                break;
            } else if (status == 0 || status >= 500 || status == 408 || status == 429) {
                // 連不上／伺服器暫時故障／逾時／被限流：**中止整輪**，保住入列順序，之後再試
                break;
            } else {
                SetOutbox.markFailed(context, uuid);
            }
        }
        publishState(context, unauthorized);
    }

    /** ⑧：視窗與前端都要看得到現況——只更新計數的話，使用者看到的是「像成功一樣」的轉場。 */
    private static void publishState(Context context, boolean unauthorized) {
        int pending = SetOutbox.count(context, SetOutbox.STATUS_PENDING);
        int failed = SetOutbox.count(context, SetOutbox.STATUS_FAILED);
        RestOverlay.onOutboxState(context, pending, failed);
        RestTimerPlugin.emitOutbox(pending, failed);
        // token 失效要讓使用者知道，否則他會以為自己還登著，之後每一組都繼續送不出去
        if (unauthorized) RestTimerPlugin.emitUnauthorized();
    }

    /** @return HTTP 狀態碼；連不上回 0（與 queue.js 的 status 0 同義）。 */
    private static int post(String baseUrl, String token, JSONObject entry) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(baseUrl + "/api/workouts/" + entry.optInt("workoutId") + "/sets");
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Authorization", "Bearer " + token);
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
            conn.setReadTimeout(READ_TIMEOUT_MS);
            conn.setDoOutput(true);
            byte[] payload = body(entry).getBytes(StandardCharsets.UTF_8);
            try (OutputStream out = conn.getOutputStream()) {
                out.write(payload);
            }
            return conn.getResponseCode();
        } catch (IOException | JSONException e) {
            Log.w(TAG, "送出失敗，留在 outbox", e);
            return 0;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private static String body(JSONObject entry) throws JSONException {
        JSONObject payload = new JSONObject();
        payload.put("client_uuid", entry.optString("uuid"));
        payload.put("exercise_id", entry.optInt("exerciseId"));
        payload.put("weight_kg", entry.optDouble("weight"));
        payload.put("reps", entry.optInt("reps"));
        // set_number 刻意不帶：由伺服器算（F131 ③）
        // rpe 刻意不帶：就地記的組留 null（F104 ⑦）
        int rest = entry.optInt("restSeconds", -1);
        if (rest >= 0) payload.put("rest_seconds", rest);
        return payload.toString();
    }
}
