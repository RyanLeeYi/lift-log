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
    public void createAndSeedAreReadyAndIdempotent() {
        assertEquals(LocalStore.DATABASE_VERSION, store.ensureReady());
        assertEquals(35, store.seedExercises());
        assertEquals(0, store.seedExercises());
        assertEquals(35, store.count("exercises", "deleted_at IS NULL", null));
        assertEquals(0, store.pendingMutationCount());
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
    public void versionOneUpgradePreservesDomainRows() {
        String preservedId = createVersionOneDatabase();
        assertEquals(LocalStore.DATABASE_VERSION, store.ensureReady());
        assertEquals(1, store.count("exercises", "sync_id = ?", new String[]{preservedId}));
        assertEquals(0, store.pendingMutationCount());
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
