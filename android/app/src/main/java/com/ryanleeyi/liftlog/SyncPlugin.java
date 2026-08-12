package com.ryanleeyi.liftlog;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONException;
import org.json.JSONObject;

/** Minimal Capacitor bridge for the frozen native sync core. */
@CapacitorPlugin(name = "Sync")
public class SyncPlugin extends Plugin {
    @PluginMethod
    public void initialize(PluginCall call) {
        String baseUrl = call.getString("baseUrl");
        if (!SecureStore.saveBaseUrl(getContext(), baseUrl)) {
            call.reject("同步站點設定無效");
            return;
        }
        try {
            SyncScheduler.initialize(getContext());
            call.resolve(status());
        } catch (RuntimeException error) {
            call.reject("同步排程無法啟動", "SYNC_SCHEDULE_ERROR", error);
        }
    }

    @PluginMethod
    public void status(PluginCall call) {
        try {
            call.resolve(status());
        } catch (RuntimeException error) {
            call.reject("無法讀取同步狀態", "SYNC_STATUS_ERROR", error);
        }
    }

    @PluginMethod
    public void syncNow(PluginCall call) {
        SyncScheduler.syncNow(getContext(), new SyncScheduler.ResultCallback() {
            @Override
            public void onResult(SyncClient.Result result) {
                resolveOnMain(call, result, null);
            }

            @Override
            public void onError(RuntimeException error) {
                resolveOnMain(call, null, error);
            }
        });
    }

    private void resolveOnMain(PluginCall call, SyncClient.Result result, RuntimeException error) {
        if (getActivity() == null) {
            call.reject("同步畫面已關閉");
            return;
        }
        getActivity().runOnUiThread(() -> {
            if (error != null) {
                call.reject("同步失敗", "SYNC_ERROR", error);
                return;
            }
            try {
                JSObject response = status();
                response.put("state", result.state);
                response.put("pending", result.pending);
                response.put("cursor", result.cursor);
                call.resolve(response);
            } catch (RuntimeException statusError) {
                call.reject("無法讀取同步狀態", "SYNC_STATUS_ERROR", statusError);
            }
        });
    }

    private JSObject status() {
        LocalStore store = LocalStore.getInstance(getContext());
        store.ensureReady();
        try {
            JSONObject value = store.syncStatus();
            return JSObject.fromJSONObject(value);
        } catch (JSONException error) {
            throw new IllegalStateException("同步狀態格式不合法", error);
        }
    }
}
