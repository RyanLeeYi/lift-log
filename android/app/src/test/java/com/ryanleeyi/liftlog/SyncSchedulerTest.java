package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 36)
public class SyncSchedulerTest {
    private Context context;
    private JobScheduler scheduler;

    @Before
    public void setUp() {
        context = RuntimeEnvironment.getApplication();
        scheduler = context.getSystemService(JobScheduler.class);
        scheduler.cancel(SyncScheduler.JOB_ID);
    }

    @Test
    public void immediateJobNeedsAnyNetworkAndRunsWithinFiveSeconds() {
        SyncScheduler.scheduleNow(context);

        JobInfo job = scheduler.getPendingJob(SyncScheduler.JOB_ID);
        assertNotNull(job);
        assertEquals(JobInfo.NETWORK_TYPE_ANY, job.getNetworkType());
        assertTrue(job.getMinLatencyMillis() <= 5_000);
    }

    @Test
    public void retryUsesPersistedNextSyncAt() throws Exception {
        long now = 1_000L;
        LocalStore store = LocalStore.getInstance(context);
        store.ensureReady();
        store.markPushFailure(
            new JSONObject().put("mutations", new JSONArray()), "offline", now + 4_321
        );

        SyncScheduler.scheduleRetry(context, now);

        JobInfo job = scheduler.getPendingJob(SyncScheduler.JOB_ID);
        assertNotNull(job);
        assertEquals(4_321, job.getMinLatencyMillis());
    }

    @Test
    public void initializeIsIdempotent() {
        SyncScheduler.initialize(context);
        SyncScheduler.initialize(context);

        assertEquals(0, scheduler.getAllPendingJobs().stream()
            .filter(job -> job.getId() == SyncScheduler.JOB_ID).count());
    }
}
