package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.app.job.JobScheduler;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * F149 ⑥ 的 Android instrumentation 覆蓋：local migration、transaction rollback、
 * process death、離線數週、outbox retry、兩裝置 conflict/takeover 六個範圍。
 *
 * 與 JVM（Robolectric）層同名測試的差別在執行環境：這裡跑在實機的 Android SQLite、
 * 真實檔案系統與真實 JobScheduler 上，驗的是「同一段程式在真機也成立」，
 * 不是重複驗邏輯分支。
 */
@RunWith(AndroidJUnit4.class)
public class F149SyncInstrumentedTest {
    private Context context;
    private String databaseName;
    private LocalStore store;

    @Before
    public void setUp() {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        databaseName = "f149-" + UUID.randomUUID() + ".db";
        store = new LocalStore(context, databaseName);
    }

    @After
    public void tearDown() {
        if (store != null) store.close();
        context.deleteDatabase(databaseName);
    }

    // --- local migration ---------------------------------------------------

    @Test
    public void versionOneDatabaseUpgradesOnDeviceWithoutLosingRows() throws JSONException {
        String preservedId = createVersionOneDatabase();

        assertEquals(LocalStore.DATABASE_VERSION, store.ensureReady());
        assertEquals(1, store.count("exercises", "sync_id = ?", new String[]{preservedId}));
        assertTrue(store.syncStatus().getBoolean("bootstrapComplete"));
        // 升級把既有列補進 outbox；重開同一個檔案不得重跑 migration 或重複入列。
        int pendingAfterUpgrade = store.pendingMutationCount();
        store.close();
        store = new LocalStore(context, databaseName);
        assertEquals(LocalStore.DATABASE_VERSION, store.ensureReady());
        assertEquals(pendingAfterUpgrade, store.pendingMutationCount());
        store.seedExercises();
        assertEquals(0, store.seedExercises());
    }

    // --- transaction rollback ----------------------------------------------

    @Test
    public void domainAndOutboxRollBackTogetherOnDeviceSqlite() {
        store.ensureReady();
        String mutationId = uuid();
        store.createWorkout(uuid(), "2026-08-09", null, null, null, mutationId);

        try {
            store.createWorkout(uuid(), "2026-08-10", null, null, null, mutationId);
            fail("重複 mutation_id 應讓整個 transaction 失敗");
        } catch (RuntimeException expected) {
            assertNotNull(expected);
        }

        assertEquals(1, store.count("workouts", null, null));
        assertEquals(1, store.pendingMutationCount());
    }

    @Test
    public void failedMigrationRollsBackAndLeavesFileAtVersionOne() {
        String preservedId = createVersionOneDatabase();
        store.close();
        store = new FailingMigrationStore(context, databaseName);

        try {
            store.ensureReady();
            fail("migration 失敗必須阻止開庫");
        } catch (RuntimeException expected) {
            assertNotNull(expected);
        }
        try {
            store.ensureReady();
            fail("migration 失敗後必須持續鎖定寫入");
        } catch (IllegalStateException expected) {
            assertNotNull(expected.getCause());
        }

        store.close();
        store = null;
        SQLiteDatabase raw = SQLiteDatabase.openDatabase(
            context.getDatabasePath(databaseName).getPath(), null, SQLiteDatabase.OPEN_READONLY
        );
        try {
            assertEquals(1, raw.getVersion());
            try (Cursor cursor = raw.query(
                "exercises", new String[]{"COUNT(*)"}, "sync_id = ?",
                new String[]{preservedId}, null, null, null
            )) {
                cursor.moveToFirst();
                assertEquals(1, cursor.getInt(0));
            }
        } finally {
            raw.close();
        }
    }

    // --- process death + 離線數週 -------------------------------------------

    /**
     * 模擬 process death 的方式是「不呼叫 close() 就丟掉 handle」——寫入後沒有優雅關閉，
     * 資料只能靠實機 SQLite 自己的 journal 落地。真正的 SIGKILL 無法在同一個 process 內
     * 對自己施加（instrumentation 與 app 同 process），這是本測試已知的天花板。
     */
    @Test
    public void outboxAndRetryScheduleSurviveAbruptDeathAndWeeksOffline() throws JSONException {
        store.ensureReady();
        String mutationId = uuid();
        String deviceId = uuid();
        store.saveBodyMetric(uuid(), "2026-08-11", 80, null, mutationId);
        JSONObject batch = store.pendingPushBody(deviceId, 500, 1024 * 1024, 0);
        store.markPushFailure(batch, "offline", 900_000);

        store = new LocalStore(context, databaseName);  // 前一個 handle 沒有 close，等同被砍掉
        assertEquals(1, store.pendingMutationCount());
        assertEquals(900_000, store.nextSyncAt());
        assertEquals(0, store.pendingPushBody(deviceId, 500, 1024 * 1024, 899_999)
            .getJSONArray("mutations").length());

        JSONObject afterWeeks = store.pendingPushBody(
            deviceId, 500, 1024 * 1024, 21L * 24 * 60 * 60 * 1000
        );
        assertEquals(1, afterWeeks.getJSONArray("mutations").length());
        assertEquals(mutationId,
            afterWeeks.getJSONArray("mutations").getJSONObject(0).getString("mutation_id"));
    }

    /** process death 之後要靠 JobScheduler 把 sync 叫回來——這裡驗真實系統服務有留下 job。 */
    @Test
    public void retryLeavesPendingJobInRealJobScheduler() {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        assertNotNull("實機必須有 JobScheduler", scheduler);
        scheduler.cancel(SyncScheduler.JOB_ID);
        assertNull(scheduler.getPendingJob(SyncScheduler.JOB_ID));

        LocalStore shared = LocalStore.getInstance(context);
        shared.ensureReady();
        long now = System.currentTimeMillis();
        shared.markPullFailure("offline", now + 60_000);
        try {
            SyncScheduler.scheduleRetry(context, now);
            assertNotNull("重試必須留下可在 process death 後恢復的 job",
                scheduler.getPendingJob(SyncScheduler.JOB_ID));
        } finally {
            scheduler.cancel(SyncScheduler.JOB_ID);
            shared.markSyncSuccess(now);
        }
    }

    // --- outbox retry -------------------------------------------------------

    @Test
    public void lostPushResponseRetriesSameMutationThenPullsOnDevice() throws Exception {
        store.ensureReady();
        String mutationId = uuid();
        store.saveBodyMetric(uuid(), "2026-08-11", 80, null, mutationId);
        RecordingTransport transport = new RecordingTransport(mutationId);
        SyncClient client = new SyncClient(store, uuid(), transport, () -> 0.0);

        assertEquals("offline", client.syncOnce(0).state);
        assertEquals(1, store.pendingMutationCount());
        assertEquals(5_000, store.nextSyncAt());

        assertEquals("synced", client.syncOnce(5_000).state);
        assertEquals(0, store.pendingMutationCount());
        assertEquals(List.of("push", "push", "pull"), transport.calls);
        assertEquals(mutationId, transport.mutationIds.get(0));
        assertEquals(mutationId, transport.mutationIds.get(1));
    }

    // --- 兩裝置 conflict / takeover ------------------------------------------

    @Test
    public void keepLocalRebasesOntoServerVersionOnDevice() throws JSONException {
        String syncId = pushConflictedBodyMetric(80, 75, 5, false);
        JSONObject conflict = store.conflicts().getJSONArray("items").getJSONObject(0);

        String retry = uuid();
        JSONObject status = store.resolveConflict(
            conflict.getString("conflictId"), "local", retry
        );
        assertEquals(0, status.getInt("conflicts"));
        assertEquals(80, store.snapshot().getJSONArray("body_metrics")
            .getJSONObject(0).getDouble("weight_kg"), 0.001);
        JSONObject next = store.pendingPushBody(uuid(), 10, 1024 * 1024, 2_000)
            .getJSONArray("mutations").getJSONObject(0);
        assertEquals(retry, next.getString("mutation_id"));
        assertEquals(5, next.getInt("base_version"));
        assertEquals(syncId, next.getString("entity_id"));
    }

    @Test
    public void useServerTakesOverAndTombstoneCannotBeResurrectedOnDevice() throws JSONException {
        pushConflictedBodyMetric(80, 75, 5, false);
        JSONObject conflict = store.conflicts().getJSONArray("items").getJSONObject(0);
        JSONObject status = store.resolveConflict(
            conflict.getString("conflictId"), "server", uuid()
        );
        assertEquals(0, status.getInt("conflicts"));
        assertEquals(0, status.getInt("pending"));
        assertEquals(75, store.snapshot().getJSONArray("body_metrics")
            .getJSONObject(0).getDouble("weight_kg"), 0.001);

        String tombstoned = pushConflictedBodyMetric(70, 65, 6, true);
        assertNotNull(tombstoned);
        String conflictId = store.conflicts().getJSONArray("items").getJSONObject(0)
            .getString("conflictId");
        try {
            store.resolveConflict(conflictId, "local", uuid());
            fail("雲端已刪除的資料不得由保留本機復活");
        } catch (IllegalArgumentException expected) {
            assertNotNull(expected.getMessage());
        }
        assertEquals(1, store.unresolvedConflictCount());
        store.resolveConflict(conflictId, "server", uuid());
        assertEquals(0, store.unresolvedConflictCount());
    }

    // --- helpers ------------------------------------------------------------

    private String createVersionOneDatabase() {
        store.close();
        String preservedId = uuid();
        SQLiteDatabase raw = context.openOrCreateDatabase(databaseName, 0, null);
        try {
            LocalStore.createVersion1Schema(raw);
            ContentValues exercise = new ContentValues();
            exercise.put("sync_id", preservedId);
            exercise.put("name_zh", "保留測試動作");
            exercise.put("name_en", "Preserved Test Exercise");
            exercise.put("muscle_group", "測試");
            exercise.put("is_bodyweight", 0);
            raw.insertOrThrow("exercises", null, exercise);
            raw.setVersion(1);
        } finally {
            raw.close();
        }
        store = new LocalStore(context, databaseName);
        return preservedId;
    }

    /** 建一筆本機體重、推上去被 server 以 version_mismatch／tombstone 擋掉，回傳 entity sync_id。 */
    private String pushConflictedBodyMetric(
        double localWeight, double serverWeight, int serverVersion, boolean serverDeleted
    ) throws JSONException {
        store.ensureReady();
        String syncId = uuid();
        String mutationId = uuid();
        String date = serverDeleted ? "2026-08-14" : "2026-08-13";
        store.saveBodyMetric(syncId, date, localWeight, null, mutationId);
        store.pendingPushBody(uuid(), 10, 1024 * 1024, 0);
        store.applyPushResponse(new JSONObject()
            .put("accepted", new JSONArray())
            .put("conflicts", new JSONArray().put(new JSONObject()
                .put("mutation_id", mutationId)
                .put("reason", serverDeleted ? "tombstoned" : "version_mismatch")
                .put("server", new JSONObject()
                    .put("entity_type", "body_metric")
                    .put("entity_id", syncId)
                    .put("version", serverVersion)
                    .put("updated_at", date + "T00:00:00Z")
                    .put("deleted_at", serverDeleted ? date + "T00:00:00Z" : JSONObject.NULL)
                    .put("payload", new JSONObject()
                        .put("sync_id", syncId)
                        .put("date", date)
                        .put("weight_kg", serverWeight)
                        .put("body_fat_pct", JSONObject.NULL))))), 1_000);
        assertEquals(1, store.unresolvedConflictCount());
        return syncId;
    }

    private static String uuid() {
        return UUID.randomUUID().toString();
    }

    private static final class FailingMigrationStore extends LocalStore {
        FailingMigrationStore(Context context, String databaseName) {
            super(context, databaseName);
        }

        @Override
        protected void migrateVersion2(SQLiteDatabase db) {
            super.migrateVersion2(db);
            throw new IllegalStateException("forced migration failure");
        }
    }

    private static final class RecordingTransport implements SyncClient.Transport {
        final List<String> calls = new ArrayList<>();
        final List<String> mutationIds = new ArrayList<>();
        final String mutationId;
        int pushes;

        RecordingTransport(String mutationId) {
            this.mutationId = mutationId;
        }

        @Override
        public JSONObject push(JSONObject body) throws IOException, JSONException {
            calls.add("push");
            mutationIds.add(body.getJSONArray("mutations").getJSONObject(0)
                .getString("mutation_id"));
            pushes++;
            if (pushes == 1) throw new IOException("response lost");
            return new JSONObject()
                .put("accepted", new JSONArray().put(new JSONObject()
                    .put("mutation_id", mutationId)
                    .put("version", 1)
                    .put("server_seq", 1)))
                .put("conflicts", new JSONArray());
        }

        @Override
        public JSONObject pull(long cursor) throws JSONException {
            calls.add("pull");
            return new JSONObject()
                .put("changes", new JSONArray())
                .put("next_cursor", cursor)
                .put("has_more", false);
        }
    }
}
