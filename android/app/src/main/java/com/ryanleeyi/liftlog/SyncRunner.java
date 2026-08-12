package com.ryanleeyi.liftlog;

import android.content.Context;

/** UI、foreground 與 JobService 共用同一個同步入口。 */
final class SyncRunner {
    private SyncRunner() {}

    // ponytail: process-wide lock avoids JobService/UI races; per-account locks only if multi-user arrives.
    static synchronized SyncClient.Result run(Context context, long nowMillis) {
        Context app = context.getApplicationContext();
        LocalStore store = LocalStore.getInstance(app);
        store.ensureReady();
        String baseUrl = SecureStore.baseUrl(app);
        String deviceId = SecureStore.deviceId(app);
        if (baseUrl == null || deviceId == null) {
            store.markSyncError("sync_not_configured");
            return new SyncClient.Result("error", store.pendingMutationCount(), store.serverCursor());
        }
        return new SyncClient(
            store,
            deviceId,
            new SyncHttpTransport(app, baseUrl),
            Math::random
        ).syncOnce(nowMillis);
    }
}
