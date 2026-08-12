package com.ryanleeyi.liftlog;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** Runs the frozen sync core away from the UI thread. */
public class SyncJobService extends JobService {
    @Override
    public boolean onStartJob(JobParameters parameters) {
        new Thread(() -> {
            long nowMillis = System.currentTimeMillis();
            try {
                SyncScheduler.afterRun(this, SyncRunner.run(this, nowMillis), nowMillis);
            } catch (RuntimeException ignored) {
                SyncScheduler.scheduleRetry(this, nowMillis);
            } finally {
                jobFinished(parameters, false);
            }
        }, "lift-log-sync").start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters parameters) {
        return true;
    }
}
