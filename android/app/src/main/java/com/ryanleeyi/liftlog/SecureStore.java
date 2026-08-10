package com.ryanleeyi.liftlog;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import java.util.UUID;

/**
 * F131 ⑤：原生側要打 API，所以要有 Bearer token 與 base URL。
 *
 * <p><b>為什麼原生要存一份。</b>token 原本只在 WebView 的 localStorage
 * （{@code liftlog.token}）。背景時 JS 整條鏈是凍住的，跟它要 token 就等於回到
 * F125 那條「等回前景」的路——那正是本條要取代的東西。所以只能事先存一份。
 *
 * <p><b>明文不行。</b>一般 SharedPreferences 是明文 XML。同一顆 token 就是全站憑證
 * （單人系統，見 CLAUDE.md），落在磁碟上等於多一個外洩面。用
 * {@link EncryptedSharedPreferences} 存，金鑰由 Android Keystore 管。
 *
 * <p><b>寫入者只有 JS。</b>token 的事實來源仍是前端（setup 頁輸入、換 token 都在那裡），
 * 這裡只是鏡射。JS 在啟動與換 token 時經 {@code RestTimerPlugin.setAuth()} 推過來。
 *
 * <p><b>加密失敗時不退回明文。</b>Keystore 在少數裝置上會壞（換機還原、系統升級）。
 * 那種情況寧可讓原生寫入路徑停擺、退回 F125 的「回 app 再寫」，也不要把 token 明文寫下去。
 */
final class SecureStore {

    private static final String TAG = "SecureStore";
    private static final String PREFS = "liftlog_secure";
    private static final String KEY_TOKEN = "token";
    private static final String KEY_BASE_URL = "base_url";
    private static final String KEY_ACCESS_TOKEN = "auth_access_token";
    private static final String KEY_REFRESH_TOKEN = "auth_refresh_token";
    private static final String KEY_ACCESS_EXPIRES_AT = "auth_access_expires_at";
    private static final String KEY_DEVICE_ID = "auth_device_id";

    private SecureStore() {}

    /**
     * 建好就快取（review MEDIUM）：`EncryptedSharedPreferences.create()` 每次都要走
     * Keystore RPC，冷啟動可達數百 ms，而 `ready()` 檢查跑在按鈕的 click handler 上——
     * 每按一次做兩趟 Keystore，Keystore 忙碌的裝置會有 ANR 風險。
     * 失敗也記下來，不要每次重試一遍同一個壞掉的 Keystore。
     */
    private static volatile SharedPreferences cached;
    private static volatile boolean unavailable;

    /** 取不到就回 null（呼叫端一律要當「現在不能打 API」處理，不要當空字串用）。 */
    private static SharedPreferences prefs(Context context) {
        if (cached != null) return cached;
        if (unavailable) return null;
        Context app = context.getApplicationContext();
        try {
            MasterKey key = new MasterKey.Builder(app)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build();
            cached = EncryptedSharedPreferences.create(
                app,
                PREFS,
                key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
            return cached;
        } catch (Exception e) {
            // 明文退路是刻意不做的：見類別註解
            Log.w(TAG, "加密儲存不可用，原生寫入路徑停用", e);
            unavailable = true;
            return null;
        }
    }

    static void save(Context context, String token, String baseUrl) {
        SharedPreferences p = prefs(context);
        if (p == null) return;
        p.edit().putString(KEY_TOKEN, token).putString(KEY_BASE_URL, baseUrl).apply();
    }

    static String token(Context context) {
        SharedPreferences p = prefs(context);
        return p == null ? null : p.getString(KEY_TOKEN, null);
    }

    static String baseUrl(Context context) {
        SharedPreferences p = prefs(context);
        return p == null ? null : p.getString(KEY_BASE_URL, null);
    }

    /** 401 之後由 JS 決定要不要清；原生自己不清（它分不出是 token 錯還是伺服器出包）。 */
    static void clear(Context context) {
        SharedPreferences p = prefs(context);
        if (p == null) return;
        p.edit().clear().apply();
    }

    static String deviceId(Context context) {
        SharedPreferences p = prefs(context);
        if (p == null) return null;
        String id = p.getString(KEY_DEVICE_ID, null);
        if (id != null) return id;
        id = UUID.randomUUID().toString();
        return p.edit().putString(KEY_DEVICE_ID, id).commit() ? id : null;
    }

    static boolean saveAuthSession(
        Context context,
        String accessToken,
        String refreshToken,
        long accessExpiresAt
    ) {
        SharedPreferences p = prefs(context);
        if (p == null || accessToken == null || accessToken.trim().isEmpty()
            || refreshToken == null || refreshToken.trim().isEmpty() || accessExpiresAt <= 0) {
            return false;
        }
        return p.edit()
            .putString(KEY_ACCESS_TOKEN, accessToken)
            .putString(KEY_REFRESH_TOKEN, refreshToken)
            .putLong(KEY_ACCESS_EXPIRES_AT, accessExpiresAt)
            .commit();
    }

    static String accessToken(Context context) {
        SharedPreferences p = prefs(context);
        return p == null ? null : p.getString(KEY_ACCESS_TOKEN, null);
    }

    static String refreshToken(Context context) {
        SharedPreferences p = prefs(context);
        return p == null ? null : p.getString(KEY_REFRESH_TOKEN, null);
    }

    static long accessExpiresAt(Context context) {
        SharedPreferences p = prefs(context);
        return p == null ? 0 : p.getLong(KEY_ACCESS_EXPIRES_AT, 0);
    }

    static void clearAuthSession(Context context) {
        SharedPreferences p = prefs(context);
        if (p == null) return;
        p.edit()
            .remove(KEY_ACCESS_TOKEN)
            .remove(KEY_REFRESH_TOKEN)
            .remove(KEY_ACCESS_EXPIRES_AT)
            .commit();
    }
}
