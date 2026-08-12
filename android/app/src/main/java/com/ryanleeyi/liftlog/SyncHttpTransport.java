package com.ryanleeyi.liftlog;

import android.content.Context;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;

/** F143 sync contract 的 Android HTTP transport；401 僅 refresh 一次，不記錄 token/body。 */
final class SyncHttpTransport implements SyncClient.Transport {
    private final Context context;
    private final String baseUrl;

    SyncHttpTransport(Context context, String baseUrl) {
        this.context = context.getApplicationContext();
        this.baseUrl = baseUrl;
    }

    @Override
    public JSONObject push(JSONObject body) throws IOException, JSONException {
        return request("POST", "/api/sync/push", body);
    }

    @Override
    public JSONObject pull(long cursor) throws IOException, JSONException {
        return request("GET", "/api/sync/pull?cursor=" + cursor + "&limit=1000", null);
    }

    private JSONObject request(String method, String path, JSONObject body)
        throws IOException, JSONException {
        String token = NativeAuthSession.accessToken(context, baseUrl, false);
        JsonHttp.Response response = JsonHttp.request(baseUrl, path, method, body, token);
        if (response.status == 401) {
            token = NativeAuthSession.accessToken(context, baseUrl, true);
            response = JsonHttp.request(baseUrl, path, method, body, token);
        }
        if (response.status >= 200 && response.status < 300) return response.body;
        boolean retryable = response.status == 408 || response.status == 429 || response.status >= 500;
        String code = response.body.optString("error", "sync_http_" + response.status);
        throw new SyncClient.TransportFailure(code, retryable);
    }
}
