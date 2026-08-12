package com.ryanleeyi.liftlog;

import android.content.Context;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;

/** 背景 sync 的 rotating session；refresh token 永遠只從加密 preferences 讀寫。 */
final class NativeAuthSession {
    private NativeAuthSession() {}

    static String accessToken(Context context, String baseUrl, boolean forceRefresh)
        throws IOException {
        long now = System.currentTimeMillis();
        String current = SecureStore.accessToken(context);
        if (!forceRefresh && current != null
            && SecureStore.accessExpiresAt(context) > now + 30_000) {
            return current;
        }
        String refresh = SecureStore.refreshToken(context);
        String deviceId = SecureStore.deviceId(context);
        if (refresh == null || deviceId == null) {
            throw new SyncClient.TransportFailure("auth_required", false);
        }
        try {
            JsonHttp.Response response = JsonHttp.request(
                baseUrl,
                "/api/auth/refresh",
                "POST",
                new JSONObject().put("refresh_token", refresh).put("device_id", deviceId),
                null
            );
            if (response.status == 401) {
                SecureStore.clearAuthSession(context);
                throw new SyncClient.TransportFailure("auth_required", false);
            }
            if (response.status < 200 || response.status >= 300) {
                throw new SyncClient.TransportFailure(
                    "auth_refresh_" + response.status,
                    response.status == 408 || response.status == 429 || response.status >= 500
                );
            }
            String accessToken = response.body.getString("access_token");
            String refreshToken = response.body.getString("refresh_token");
            long expiresAt = now + response.body.getLong("expires_in") * 1000;
            if (!SecureStore.saveAuthSession(context, accessToken, refreshToken, expiresAt)) {
                throw new SyncClient.TransportFailure("secure_store_unavailable", false);
            }
            return accessToken;
        } catch (JSONException error) {
            throw new SyncClient.TransportFailure("auth_response_invalid", false);
        }
    }
}
