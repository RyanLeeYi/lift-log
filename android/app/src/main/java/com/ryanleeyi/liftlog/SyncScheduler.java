package com.ryanleeyi.liftlog;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Schedules sync only for real triggers; retry timing remains owned by LocalStore. */
final class SyncScheduler {
    static final int JOB_ID = 144;

    private static final ExecutorService SYNC_EXECUTOR = Executors.newSingleThreadExecutor();
    private static boolean networkCallbackRegistered;

    private SyncScheduler() {}

    interface ResultCallback {
        void onResult(SyncClient.Result result);
        void onError(RuntimeException error);
    }

    static synchronized void initialize(Context context) {
        Context app = context.getApplicationContext();
        if (!networkCallbackRegistered) {
            ConnectivityManager connectivity = app.getSystemService(ConnectivityManager.class);
            if (connectivity != null) {
                connectivity.registerDefaultNetworkCallback(new ConnectivityManager.NetworkCallback() {
                    @Override
                    public void onAvailable(Network network) {
                        kick(app);
                    }
                });
                networkCallbackRegistered = true;
            }
        }
        kick(app);
    }

    static void scheduleNow(Context context) {
        schedule(context, 0);
    }

    /** Starts an eligible sync immediately and leaves a job behind for process death recovery. */
    static void kick(Context context) {
        Context app = context.getApplicationContext();
        if (SecureStore.baseUrl(app) == null
            || (SecureStore.accessToken(app) == null && SecureStore.refreshToken(app) == null)) {
            return;
        }
        try {
            scheduleNow(app);
        } catch (RuntimeException ignored) {
            // A committed local mutation remains successful even when the fallback job is unavailable.
        }
        run(app, null);
    }

    static void syncNow(Context context, ResultCallback callback) {
        Context app = context.getApplicationContext();
        try {
            scheduleNow(app);
        } catch (RuntimeException ignored) {
            // The immediate runner remains useful even when process-death fallback is unavailable.
        }
        run(app, callback);
    }

    private static void run(Context app, ResultCallback callback) {
        try {
            SYNC_EXECUTOR.execute(() -> {
                long nowMillis = System.currentTimeMillis();
                try {
                    SyncClient.Result result = SyncRunner.run(app, nowMillis);
                    try {
                        afterRun(app, result, nowMillis);
                    } catch (RuntimeException ignored) {
                        // A completed core run is still successful if only its next fallback job failed.
                    }
                    if (callback != null) callback.onResult(result);
                } catch (RuntimeException error) {
                    try {
                        scheduleRetry(app, nowMillis);
                    } catch (RuntimeException ignored) {
                        // The core persisted the retry time; the next lifecycle trigger can reschedule it.
                    }
                    if (callback != null) callback.onError(error);
                }
            });
        } catch (RuntimeException error) {
            if (callback != null) callback.onError(error);
        }
    }

    static void scheduleRetry(Context context, long nowMillis) {
        long nextSyncAt = LocalStore.getInstance(context).nextSyncAt();
        if (nextSyncAt > nowMillis) schedule(context, nextSyncAt - nowMillis);
    }

    static void afterRun(Context context, SyncClient.Result result, long nowMillis) {
        if ("synced".equals(result.state) && result.pending > 0) {
            scheduleNow(context);
        } else {
            scheduleRetry(context, nowMillis);
        }
    }

    private static void schedule(Context context, long latencyMillis) {
        Context app = context.getApplicationContext();
        JobScheduler scheduler = app.getSystemService(JobScheduler.class);
        if (scheduler == null) throw new IllegalStateException("JobScheduler unavailable");
        JobInfo job = new JobInfo.Builder(
            JOB_ID, new ComponentName(app, SyncJobService.class)
        ).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setMinimumLatency(Math.max(0, latencyMillis))
            .build();
        if (scheduler.schedule(job) == JobScheduler.RESULT_FAILURE) {
            throw new IllegalStateException("sync job schedule failed");
        }
    }
}
