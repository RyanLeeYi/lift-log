package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.util.UUID;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 36)
public class LocalStoreTest {
    private Context context;
    private String databaseName;
    private LocalStore store;

    @Before
    public void setUp() {
        context = RuntimeEnvironment.getApplication();
        databaseName = "local-store-test-" + UUID.randomUUID() + ".db";
        store = new LocalStore(context, databaseName);
    }

    @After
    public void tearDown() {
        if (store != null) store.close();
        context.deleteDatabase(databaseName);
    }

    @Test
    public void createAndSeedAreReadyAndIdempotent() throws JSONException {
        assertEquals(LocalStore.DATABASE_VERSION, store.ensureReady());
        assertEquals(35, store.seedExercises());
        assertEquals(0, store.seedExercises());
        assertEquals(35, store.count("exercises", "deleted_at IS NULL", null));
        assertEquals(35, store.pendingMutationCount());
        assertFalse(store.syncStatus().getBoolean("bootstrapComplete"));
    }

    @Test
    public void domainAndOutboxRollbackTogether() {
        store.ensureReady();
        String firstMutation = uuid();
        store.createWorkout(uuid(), "2026-08-09", null, null, null, firstMutation);

        try {
            store.createWorkout(uuid(), "2026-08-10", null, null, null, firstMutation);
            fail("重複 mutation_id 應讓整個 transaction 失敗");
        } catch (RuntimeException expected) {
            assertNotNull(expected);
        }

        assertEquals(1, store.count("workouts", null, null));
        assertEquals(1, store.pendingMutationCount());
    }

    @Test
    public void versionOneUpgradePreservesDomainRows() throws JSONException {
        String preservedId = createVersionOneDatabase();
        assertEquals(LocalStore.DATABASE_VERSION, store.ensureReady());
        assertEquals(1, store.count("exercises", "sync_id = ?", new String[]{preservedId}));
        assertEquals(1, store.pendingMutationCount());
        assertTrue(store.syncStatus().getBoolean("bootstrapComplete"));
    }

    @Test
    public void versionTwoUpgradeBackfillsEveryExistingDomainRow() {
        store.close();
        SQLiteDatabase raw = context.openOrCreateDatabase(databaseName, 0, null);
        try {
            LocalStore.createVersion1Schema(raw);
            store.migrateVersion2(raw);
            String exerciseId = UUID.nameUUIDFromBytes(
                "liftlog:exercise:Squat".getBytes(java.nio.charset.StandardCharsets.UTF_8)
            ).toString();
            ContentValues exercise = new ContentValues();
            exercise.put("sync_id", exerciseId);
            exercise.put("name_zh", "深蹲");
            exercise.put("name_en", "Squat");
            exercise.put("muscle_group", "腿");
            exercise.put("is_bodyweight", 0);
            raw.insertOrThrow("exercises", null, exercise);

            String templateId = uuid();
            ContentValues template = new ContentValues();
            template.put("sync_id", templateId);
            template.put("name", "既有課表");
            raw.insertOrThrow("templates", null, template);

            String workoutId = uuid();
            ContentValues workout = new ContentValues();
            workout.put("sync_id", workoutId);
            workout.put("date", "2026-08-10");
            raw.insertOrThrow("workouts", null, workout);

            ContentValues set = new ContentValues();
            set.put("sync_id", uuid());
            set.put("client_uuid", uuid());
            set.put("workout_sync_id", workoutId);
            set.put("exercise_sync_id", exerciseId);
            set.put("set_number", 1);
            set.put("weight_kg", 100);
            set.put("reps", 5);
            raw.insertOrThrow("sets", null, set);

            ContentValues metric = new ContentValues();
            metric.put("sync_id", uuid());
            metric.put("date", "2026-08-10");
            metric.put("weight_kg", 80);
            raw.insertOrThrow("body_metrics", null, metric);

            ContentValues status = new ContentValues();
            status.put("sync_id", uuid());
            status.put("date", "2026-08-10");
            status.put("energy", 4);
            raw.insertOrThrow("daily_status", null, status);

            ContentValues setting = new ContentValues();
            setting.put("key", "weekly_target_days");
            setting.put("sync_id", uuid());
            setting.put("value", "4");
            raw.insertOrThrow("app_settings", null, setting);
            raw.setVersion(2);
        } finally {
            raw.close();
        }

        store = new LocalStore(context, databaseName);
        assertEquals(LocalStore.DATABASE_VERSION, store.ensureReady());
        assertEquals(7, store.pendingMutationCount());
    }

    @Test
    public void failedUpgradeRollsBackAndLocksWrites() {
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
                "exercises",
                new String[]{"COUNT(*)"},
                "sync_id = ?",
                new String[]{preservedId},
                null,
                null,
                null
            )) {
                cursor.moveToFirst();
                assertEquals(1, cursor.getInt(0));
            }
        } finally {
            raw.close();
        }
    }

    @Test
    public void fullDomainCrudUsesLocalRowsAndOutboxTogether() throws JSONException {
        store.ensureReady();
        JSONObject exercise = store.createExercise(
            uuid(), "測試動作", "", null, false, uuid()
        );
        int exerciseId = exercise.getInt("id");
        assertEquals("測試動作", exercise.getString("name_en"));
        assertEquals("其他", exercise.getString("muscle_group"));

        JSONObject template = store.saveTemplate(
            null,
            uuid(),
            "腿日",
            templateExercises(exerciseId, 3, 90),
            new JSONArray().put(1).put(4),
            uuid()
        );
        int templateId = template.getInt("id");
        String templateSyncId = template.getString("sync_id");
        JSONObject updatedTemplate = store.saveTemplate(
            templateId,
            null,
            "腿日更新",
            templateExercises(exerciseId, 4, 120),
            new JSONArray().put(2),
            uuid()
        );
        assertEquals(templateSyncId, updatedTemplate.getString("sync_id"));
        assertEquals(4, updatedTemplate.getJSONArray("exercises").getJSONObject(0).getInt("default_sets"));

        String workoutSyncId = uuid();
        store.createWorkout(workoutSyncId, "2026-08-10", templateId, "離線訓練", uuid(), uuid());
        JSONObject workout = store.workout(workoutSyncId);
        int workoutId = workout.getInt("id");
        assertEquals(templateId, workout.getInt("template_id"));

        String setSyncId = uuid();
        store.addSet(
            setSyncId, uuid(), workoutId, exerciseId, null, 100, 5, 8, 90, 1, uuid()
        );
        JSONObject set = store.set(setSyncId);
        assertEquals(1, set.getInt("set_number"));
        int setId = set.getInt("id");
        JSONObject changedSet = store.updateSet(setId, 102.5, 6, 9, 60, uuid());
        assertEquals(102.5, changedSet.getDouble("weight_kg"), 0.001);
        assertEquals(6, changedSet.getInt("reps"));
        store.deleteSet(setId, uuid());
        assertNull(store.set(setSyncId));

        String replacementSyncId = uuid();
        store.addSet(
            replacementSyncId, uuid(), workoutId, exerciseId, 1, 105, 4, null, 45, 1, uuid()
        );
        JSONObject replacement = store.set(replacementSyncId);
        assertEquals(2, replacement.getInt("set_number"));
        store.deleteSet(replacement.getInt("id"), uuid());

        try {
            store.deleteWorkout(workoutId, uuid());
            fail("有 tombstone set 的 workout 不得刪除");
        } catch (IllegalStateException expected) {
            assertNotNull(expected);
        }
        JSONObject ended = store.endWorkout(workoutId, uuid());
        assertNotNull(ended.getString("ended_at"));
        int mutationsAfterEnd = store.pendingMutationCount();
        assertEquals(ended.toString(), store.endWorkout(workoutId, uuid()).toString());
        assertEquals(mutationsAfterEnd, store.pendingMutationCount());

        String metricSyncId = uuid();
        JSONObject metric = store.saveBodyMetric(metricSyncId, "2026-08-10", 80, 18.0, uuid());
        JSONObject updatedMetric = store.saveBodyMetric(uuid(), "2026-08-10", 79.5, null, uuid());
        assertEquals(metric.getString("sync_id"), updatedMetric.getString("sync_id"));
        assertEquals(79.5, updatedMetric.getDouble("weight_kg"), 0.001);
        store.deleteBodyMetric("2026-08-10", uuid());

        String statusSyncId = uuid();
        JSONObject status = store.saveDailyStatus(statusSyncId, "2026-08-10", 4, 3, "還行", uuid());
        JSONObject updatedStatus = store.saveDailyStatus(uuid(), "2026-08-10", 5, null, "很好", uuid());
        assertEquals(status.getString("sync_id"), updatedStatus.getString("sync_id"));
        assertEquals(5, updatedStatus.getInt("energy"));
        store.deleteDailyStatus("2026-08-10", uuid());

        String settingSyncId = uuid();
        JSONObject setting = store.putSetting("default_rest", "90", settingSyncId, uuid());
        JSONObject updatedSetting = store.putSetting("default_rest", "120", uuid(), uuid());
        assertEquals(setting.getString("sync_id"), updatedSetting.getString("sync_id"));
        assertEquals("120", updatedSetting.getString("value"));

        JSONObject snapshot = store.snapshot();
        assertEquals(1, snapshot.getJSONArray("exercises").length());
        assertEquals(1, snapshot.getJSONArray("templates").length());
        assertEquals(1, snapshot.getJSONArray("workouts").length());
        assertEquals(0, snapshot.getJSONArray("sets").length());
        assertEquals(0, snapshot.getJSONArray("body_metrics").length());
        assertEquals(0, snapshot.getJSONArray("daily_status").length());
        assertEquals(1, snapshot.getJSONArray("settings").length());
        assertTrue(store.pendingMutationCount() >= 12);

        String emptyWorkoutSyncId = uuid();
        store.createWorkout(emptyWorkoutSyncId, "2026-08-11", null, null, null, uuid());
        store.deleteWorkout(store.workout(emptyWorkoutSyncId).getInt("id"), uuid());
        assertNull(store.workout(emptyWorkoutSyncId));
        store.deleteTemplate(templateId, uuid());
        assertEquals(0, store.snapshot().getJSONArray("templates").length());
    }

    @Test
    public void persistedRowsSurviveReopenAndRepeatedMutationRollsBack() throws JSONException {
        store.ensureReady();
        String firstMutation = uuid();
        JSONObject first = store.saveBodyMetric(uuid(), "2026-08-11", 81, null, firstMutation);
        try {
            store.saveBodyMetric(uuid(), "2026-08-11", 82, null, firstMutation);
            fail("重複 mutation_id 必須回滾 domain update");
        } catch (RuntimeException expected) {
            assertNotNull(expected);
        }
        assertEquals(81, store.snapshot().getJSONArray("body_metrics").getJSONObject(0).getDouble("weight_kg"), 0.001);

        store.close();
        store = new LocalStore(context, databaseName);
        JSONObject snapshot = store.snapshot();
        assertEquals(1, snapshot.getJSONArray("body_metrics").length());
        assertEquals(first.getString("sync_id"), snapshot.getJSONArray("body_metrics").getJSONObject(0).getString("sync_id"));
        assertFalse(snapshot.getJSONArray("body_metrics").getJSONObject(0).has("deleted_at"));
    }

    @Test
    public void workoutKeepsTemplateSnapshotAfterTemplateChangeAndReopen() throws JSONException {
        store.ensureReady();
        JSONObject exercise = store.createExercise(uuid(), "快照動作", "Snapshot", "腿", false, uuid());
        int exerciseId = exercise.getInt("id");
        JSONObject template = store.saveTemplate(
            null, uuid(), "原始課表", templateExercises(exerciseId, 3, 90),
            new JSONArray().put(1), uuid()
        );
        String workoutSyncId = uuid();
        store.createWorkout(
            workoutSyncId, "2026-08-10", template.getInt("id"), null, null, uuid()
        );
        store.saveTemplate(
            template.getInt("id"), null, "已修改課表", templateExercises(exerciseId, 5, 120),
            new JSONArray().put(2), uuid()
        );
        store.deleteTemplate(template.getInt("id"), uuid());

        store.close();
        store = new LocalStore(context, databaseName);
        JSONObject snapshot = store.workout(workoutSyncId).getJSONObject("template_snapshot");
        assertEquals("原始課表", snapshot.getString("name"));
        assertEquals(3, snapshot.getJSONArray("exercises").getJSONObject(0).getInt("default_sets"));
        assertEquals(1, snapshot.getJSONArray("weekdays").getInt(0));
    }

    @Test
    public void acceptedMutationAdvancesFollowingBaseVersionWithoutOverwritingLocalEdit()
        throws JSONException {
        store.ensureReady();
        String firstMutation = uuid();
        String secondMutation = uuid();
        store.saveBodyMetric(uuid(), "2026-08-11", 80, null, firstMutation);
        store.saveBodyMetric(uuid(), "2026-08-11", 79.5, null, secondMutation);

        JSONObject firstBatch = store.pendingPushBody(uuid(), 1, 1024 * 1024, 0);
        assertEquals(firstMutation,
            firstBatch.getJSONArray("mutations").getJSONObject(0).getString("mutation_id"));
        store.applyPushResponse(new JSONObject()
            .put("accepted", new JSONArray().put(new JSONObject()
                .put("mutation_id", firstMutation)
                .put("version", 1)
                .put("server_seq", 1)))
            .put("conflicts", new JSONArray()), 1_000);

        JSONObject secondBatch = store.pendingPushBody(uuid(), 500, 1024 * 1024, 1_000);
        JSONObject next = secondBatch.getJSONArray("mutations").getJSONObject(0);
        assertEquals(secondMutation, next.getString("mutation_id"));
        assertEquals(1, next.getInt("base_version"));
        assertEquals(79.5, store.snapshot().getJSONArray("body_metrics")
            .getJSONObject(0).getDouble("weight_kg"), 0.001);
    }

    @Test
    public void pullPageAndCursorCommitTogether() throws JSONException {
        store.ensureReady();
        String exerciseId = uuid();
        store.applyPullPage(new JSONObject()
            .put("changes", new JSONArray().put(new JSONObject()
                .put("server_seq", 1)
                .put("schema_version", 1)
                .put("entity_type", "exercise")
                .put("entity_id", exerciseId)
                .put("operation", "upsert")
                .put("version", 1)
                .put("updated_at", "2026-08-11T00:00:00Z")
                .put("deleted_at", JSONObject.NULL)
                .put("payload", new JSONObject()
                    .put("sync_id", exerciseId)
                    .put("name_zh", "遠端動作")
                    .put("name_en", "Remote")
                    .put("muscle_group", "腿")
                    .put("is_bodyweight", false))))
            .put("next_cursor", 1)
            .put("has_more", false));
        assertEquals(1, store.serverCursor());
        assertTrue(store.syncStatus().getBoolean("bootstrapComplete"));
        assertEquals("遠端動作", store.snapshot().getJSONArray("exercises")
            .getJSONObject(0).getString("name_zh"));

        try {
            store.applyPullPage(new JSONObject()
                .put("changes", new JSONArray().put(new JSONObject()
                    .put("server_seq", 2)
                    .put("schema_version", 1)
                    .put("entity_type", "future_entity")
                    .put("entity_id", uuid())
                    .put("operation", "upsert")
                    .put("version", 1)
                    .put("updated_at", "2026-08-11T00:00:01Z")
                    .put("deleted_at", JSONObject.NULL)
                    .put("payload", new JSONObject().put("sync_id", uuid()))))
                .put("next_cursor", 2)
                .put("has_more", false));
            fail("未知 entity 必須回滾整批");
        } catch (IllegalArgumentException expected) {
            assertNotNull(expected);
        }
        assertEquals(1, store.serverCursor());
        assertEquals(1, store.snapshot().getJSONArray("exercises").length());
    }

    @Test
    public void pullReconcilesNaturalKeysWhenRemoteSyncIdDiffers() throws JSONException {
        store.ensureReady();
        SQLiteDatabase db = store.getWritableDatabase();
        ContentValues metric = new ContentValues();
        metric.put("sync_id", uuid());
        metric.put("date", "2026-08-11");
        metric.put("weight_kg", 80);
        db.insertOrThrow("body_metrics", null, metric);
        ContentValues status = new ContentValues();
        status.put("sync_id", uuid());
        status.put("date", "2026-08-11");
        status.put("energy", 3);
        db.insertOrThrow("daily_status", null, status);
        ContentValues setting = new ContentValues();
        setting.put("key", "weekly_target_days");
        setting.put("sync_id", uuid());
        setting.put("value", "4");
        db.insertOrThrow("app_settings", null, setting);

        String remoteMetric = uuid();
        String remoteStatus = uuid();
        String remoteSetting = uuid();
        JSONArray changes = new JSONArray()
            .put(remoteChange(1, "body_metric", remoteMetric, new JSONObject()
                .put("sync_id", remoteMetric)
                .put("date", "2026-08-11")
                .put("weight_kg", 79.5)
                .put("body_fat_pct", JSONObject.NULL)))
            .put(remoteChange(2, "daily_status", remoteStatus, new JSONObject()
                .put("sync_id", remoteStatus)
                .put("date", "2026-08-11")
                .put("energy", 5)
                .put("sleep_quality", 4)
                .put("note", JSONObject.NULL)))
            .put(remoteChange(3, "setting", remoteSetting, new JSONObject()
                .put("sync_id", remoteSetting)
                .put("key", "weekly_target_days")
                .put("value", "5")));

        store.applyPullPage(new JSONObject()
            .put("changes", changes)
            .put("next_cursor", 3)
            .put("has_more", false));

        JSONObject snapshot = store.snapshot();
        assertEquals(3, store.serverCursor());
        assertEquals(1, snapshot.getJSONArray("body_metrics").length());
        assertEquals(remoteMetric, snapshot.getJSONArray("body_metrics")
            .getJSONObject(0).getString("sync_id"));
        assertEquals(1, snapshot.getJSONArray("daily_status").length());
        assertEquals(remoteStatus, snapshot.getJSONArray("daily_status")
            .getJSONObject(0).getString("sync_id"));
        assertEquals(1, snapshot.getJSONArray("settings").length());
        assertEquals(remoteSetting, snapshot.getJSONArray("settings")
            .getJSONObject(0).getString("sync_id"));
    }

    @Test
    public void retryScheduleAndOutboxSurviveProcessDeathAndWeeksOffline() throws JSONException {
        store.ensureReady();
        String mutationId = uuid();
        String deviceId = uuid();
        store.saveBodyMetric(uuid(), "2026-08-11", 80, null, mutationId);
        JSONObject batch = store.pendingPushBody(deviceId, 500, 1024 * 1024, 0);
        store.markPushFailure(batch, "offline", 900_000);
        assertEquals(0, store.pendingPushBody(deviceId, 500, 1024 * 1024, 899_999)
            .getJSONArray("mutations").length());

        store.close();
        store = new LocalStore(context, databaseName);
        JSONObject afterWeeks = store.pendingPushBody(
            deviceId, 500, 1024 * 1024, 21L * 24 * 60 * 60 * 1000
        );
        assertEquals(1, afterWeeks.getJSONArray("mutations").length());
        assertEquals(mutationId,
            afterWeeks.getJSONArray("mutations").getJSONObject(0).getString("mutation_id"));
    }

    @Test
    public void deferredMutationBlocksNewerMutationsToPreserveCausalOrder() throws JSONException {
        store.ensureReady();
        String deviceId = uuid();
        store.saveBodyMetric(uuid(), "2026-08-10", 80, null, uuid());
        store.saveBodyMetric(uuid(), "2026-08-11", 79, null, uuid());
        JSONObject first = store.pendingPushBody(deviceId, 1, 1024 * 1024, 0);
        store.markPushFailure(first, "offline", 5_000);

        assertEquals(0, store.pendingPushBody(deviceId, 500, 1024 * 1024, 1_000)
            .getJSONArray("mutations").length());
        store.markSyncSuccess(1_000);
        assertEquals(5_000, store.nextSyncAt());
    }

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

    private static JSONObject remoteChange(
        long sequence, String entityType, String entityId, JSONObject payload
    ) throws JSONException {
        return new JSONObject()
            .put("server_seq", sequence)
            .put("schema_version", 1)
            .put("entity_type", entityType)
            .put("entity_id", entityId)
            .put("operation", "upsert")
            .put("version", 1)
            .put("updated_at", "2026-08-11T00:00:00Z")
            .put("deleted_at", JSONObject.NULL)
            .put("payload", payload);
    }

    private static String uuid() {
        return UUID.randomUUID().toString();
    }

    private static JSONArray templateExercises(int exerciseId, int defaultSets, int restHint)
        throws JSONException {
        return new JSONArray().put(new JSONObject()
            .put("exerciseId", exerciseId)
            .put("defaultSets", defaultSets)
            .put("restHintSeconds", restHint));
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
}
