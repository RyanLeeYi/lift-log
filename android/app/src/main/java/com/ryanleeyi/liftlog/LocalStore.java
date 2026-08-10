package com.ryanleeyi.liftlog;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

/** Android 的唯一 domain store；所有本地 mutation 與 outbox 必須在同一個 transaction。 */
public class LocalStore extends SQLiteOpenHelper {
    static final String DATABASE_NAME = "liftlog-local.db";
    static final int DATABASE_VERSION = 2;
    private static final String WORKOUT_TEMPLATE_PREFIX = "workout_template:";
    // ponytail: rowid 只作本機 handle；若日後加入 VACUUM/rebuild，再 materialize local ids。

    private static final String[][] DEFAULT_EXERCISES = {
        {"深蹲", "Squat", "腿", "0"},
        {"前蹲舉", "Front Squat", "腿", "0"},
        {"腿推", "Leg Press", "腿", "0"},
        {"羅馬尼亞硬舉", "Romanian Deadlift", "腿", "0"},
        {"腿彎舉", "Leg Curl", "腿", "0"},
        {"腿伸展", "Leg Extension", "腿", "0"},
        {"保加利亞分腿蹲", "Bulgarian Split Squat", "腿", "0"},
        {"弓步蹲", "Lunge", "腿", "0"},
        {"站姿提踵", "Standing Calf Raise", "腿", "0"},
        {"硬舉", "Deadlift", "背", "0"},
        {"引體向上", "Pull-up", "背", "1"},
        {"滑輪下拉", "Lat Pulldown", "背", "0"},
        {"槓鈴划船", "Barbell Row", "背", "0"},
        {"坐姿划船", "Seated Cable Row", "背", "0"},
        {"單臂啞鈴划船", "One-arm Dumbbell Row", "背", "0"},
        {"聳肩", "Shrug", "背", "0"},
        {"臥推", "Bench Press", "胸", "0"},
        {"上斜臥推", "Incline Bench Press", "胸", "0"},
        {"啞鈴臥推", "Dumbbell Bench Press", "胸", "0"},
        {"啞鈴飛鳥", "Dumbbell Fly", "胸", "0"},
        {"繩索夾胸", "Cable Crossover", "胸", "0"},
        {"伏地挺身", "Push-up", "胸", "1"},
        {"雙槓下推", "Dip", "胸", "1"},
        {"肩推", "Overhead Press", "肩", "0"},
        {"啞鈴肩推", "Dumbbell Shoulder Press", "肩", "0"},
        {"側平舉", "Lateral Raise", "肩", "0"},
        {"面拉", "Face Pull", "肩", "0"},
        {"後三角飛鳥", "Reverse Fly", "肩", "0"},
        {"槓鈴彎舉", "Barbell Curl", "手臂", "0"},
        {"啞鈴彎舉", "Dumbbell Curl", "手臂", "0"},
        {"三頭下壓", "Triceps Pushdown", "手臂", "0"},
        {"窄握臥推", "Close-grip Bench Press", "手臂", "0"},
        {"棒式", "Plank", "核心", "1"},
        {"懸吊舉腿", "Hanging Leg Raise", "核心", "1"},
        {"腹部滾輪", "Ab Wheel Rollout", "核心", "1"}
    };

    private static LocalStore instance;
    private RuntimeException migrationFailure;

    public static synchronized LocalStore getInstance(Context context) {
        if (instance == null) {
            instance = new LocalStore(context.getApplicationContext(), DATABASE_NAME);
        }
        return instance;
    }

    LocalStore(Context context, String databaseName) {
        super(context, databaseName, null, DATABASE_VERSION);
    }

    @Override
    public void onConfigure(SQLiteDatabase db) {
        super.onConfigure(db);
        db.setForeignKeyConstraintsEnabled(true);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        createVersion1Schema(db);
        migrateVersion2(db);
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        try {
            if (oldVersion < 1) createVersion1Schema(db);
            if (oldVersion < 2) migrateVersion2(db);
            if (newVersion > DATABASE_VERSION) {
                throw new IllegalStateException("不支援 LocalStore schema v" + newVersion);
            }
        } catch (RuntimeException error) {
            migrationFailure = error;
            throw error;
        }
    }

    @Override
    public void onDowngrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        IllegalStateException error = new IllegalStateException(
            "禁止 LocalStore schema 降版：v" + oldVersion + " → v" + newVersion
        );
        migrationFailure = error;
        throw error;
    }

    public int ensureReady() {
        return writableDatabase().getVersion();
    }

    public int seedExercises() {
        return transaction(db -> {
            int created = 0;
            for (String[] exercise : DEFAULT_EXERCISES) {
                ContentValues values = new ContentValues();
                values.put("sync_id", seedId(exercise[1]));
                values.put("name_zh", exercise[0]);
                values.put("name_en", exercise[1]);
                values.put("muscle_group", exercise[2]);
                values.put("is_bodyweight", Integer.parseInt(exercise[3]));
                long row = db.insertWithOnConflict(
                    "exercises", null, values, SQLiteDatabase.CONFLICT_IGNORE
                );
                if (row != -1) created++;
            }
            return created;
        });
    }

    /** 建立 workout 與 mutation receipt；任一 insert 失敗都不留下半筆。 */
    public void createWorkout(
        String syncId,
        String date,
        Integer templateId,
        String note,
        String ownerDeviceId,
        String mutationId
    ) {
        transaction(db -> {
            String templateSyncId = templateId == null ? null : activeSyncId(
                db, "templates", templateId
            );
            String templateSnapshot = templateId == null
                ? null
                : templateById(db, templateId).toString();
            JSONObject payload = jsonObject();
            put(payload, "sync_id", syncId);
            put(payload, "date", date);
            put(payload, "template_sync_id", templateSyncId);
            put(payload, "note", note);
            put(payload, "owner_device_id", ownerDeviceId);
            put(payload, "lease_generation", 1);

            ContentValues workout = new ContentValues();
            workout.put("sync_id", syncId);
            workout.put("date", date);
            putNullable(workout, "template_sync_id", templateSyncId);
            putNullable(workout, "note", note);
            putNullable(workout, "owner_device_id", ownerDeviceId);
            workout.put("lease_generation", 1);
            db.insertOrThrow("workouts", null, workout);
            if (templateSnapshot != null) {
                putSyncState(db, WORKOUT_TEMPLATE_PREFIX + syncId, templateSnapshot);
            }
            insertOutbox(db, mutationId, "workout", syncId, "upsert", 0, 1, payload);
            return null;
        });
    }

    /** 建立 set 與 mutation receipt；供 F140 的 WebView 與 overlay 共用。 */
    public void addSet(
        String syncId,
        String clientUuid,
        int workoutId,
        int exerciseId,
        Integer setNumber,
        double weightKg,
        int reps,
        Integer rpe,
        Integer restSeconds,
        int leaseGeneration,
        String mutationId
    ) {
        transaction(db -> {
            String workoutSyncId = activeSyncId(db, "workouts", workoutId);
            String exerciseSyncId = activeSyncId(db, "exercises", exerciseId);
            int nextNumber = nextSetNumber(db, workoutSyncId, exerciseSyncId);
            int resolvedSetNumber = setNumber == null ? nextNumber : Math.max(setNumber, nextNumber);
            ContentValues set = new ContentValues();
            set.put("sync_id", syncId);
            set.put("client_uuid", clientUuid);
            set.put("workout_sync_id", workoutSyncId);
            set.put("exercise_sync_id", exerciseSyncId);
            set.put("set_number", resolvedSetNumber);
            set.put("weight_kg", weightKg);
            set.put("reps", reps);
            putNullable(set, "rpe", rpe);
            putNullable(set, "rest_seconds", restSeconds);
            db.insertOrThrow("sets", null, set);
            insertOutbox(
                db, mutationId, "set", syncId, "upsert", 0, leaseGeneration,
                setPayload(db, syncId)
            );
            return null;
        });
    }

    public JSONObject createExercise(
        String syncId,
        String nameZh,
        String nameEn,
        String muscleGroup,
        boolean isBodyweight,
        String mutationId
    ) {
        return transaction(db -> {
            ContentValues exercise = new ContentValues();
            exercise.put("sync_id", syncId);
            exercise.put("name_zh", nameZh);
            exercise.put("name_en", emptyTo(nameEn, nameZh));
            exercise.put("muscle_group", emptyTo(muscleGroup, "其他"));
            exercise.put("is_bodyweight", isBodyweight ? 1 : 0);
            long id = db.insertOrThrow("exercises", null, exercise);
            insertOutbox(
                db, mutationId, "exercise", syncId, "upsert", 0, null,
                exercisePayload(db, syncId)
            );
            return exerciseById(db, (int) id);
        });
    }

    public JSONObject workout(String syncId) {
        return workoutBySyncId(writableDatabase(), syncId);
    }

    public JSONObject set(String syncId) {
        return setBySyncId(writableDatabase(), syncId);
    }

    public JSONObject saveTemplate(
        Integer id,
        String syncId,
        String name,
        JSONArray exercises,
        JSONArray weekdays,
        String mutationId
    ) {
        return transaction(db -> {
            Entity existing = id == null ? null : activeEntity(db, "templates", id);
            String templateSyncId = existing == null ? syncId : existing.syncId;
            int baseVersion = existing == null ? 0 : existing.version;
            ContentValues template = new ContentValues();
            template.put("name", name);
            template.put("weekdays", weekdays.toString());
            int templateId;
            if (existing == null) {
                template.put("sync_id", templateSyncId);
                templateId = (int) db.insertOrThrow("templates", null, template);
            } else {
                if (db.update("templates", template, "rowid = ?", new String[]{String.valueOf(id)}) != 1) {
                    throw new IllegalStateException("找不到課表");
                }
                bumpVersion(db, "templates", id);
                db.delete("template_exercises", "template_sync_id = ?", new String[]{templateSyncId});
                templateId = id;
            }
            for (int position = 0; position < exercises.length(); position++) {
                try {
                    JSONObject item = exercises.getJSONObject(position);
                    String exerciseSyncId = activeSyncId(db, "exercises", item.getInt("exerciseId"));
                    ContentValues child = new ContentValues();
                    child.put("sync_id", UUID.randomUUID().toString());
                    child.put("template_sync_id", templateSyncId);
                    child.put("exercise_sync_id", exerciseSyncId);
                    child.put("position", position);
                    child.put("default_sets", item.getInt("defaultSets"));
                    if (item.isNull("restHintSeconds")) child.putNull("rest_hint_seconds");
                    else child.put("rest_hint_seconds", item.getInt("restHintSeconds"));
                    db.insertOrThrow("template_exercises", null, child);
                } catch (JSONException error) {
                    throw new IllegalArgumentException("課表動作格式不合法", error);
                }
            }
            insertOutbox(
                db, mutationId, "template", templateSyncId, "upsert", baseVersion, null,
                templatePayload(db, templateSyncId)
            );
            return templateById(db, templateId);
        });
    }

    public void deleteTemplate(int id, String mutationId) {
        transaction(db -> {
            Entity template = activeEntity(db, "templates", id);
            markDeleted(db, "templates", id);
            JSONObject payload = jsonObject();
            put(payload, "sync_id", template.syncId);
            insertOutbox(
                db, mutationId, "template", template.syncId, "delete", template.version, null, payload
            );
            return null;
        });
    }

    public JSONObject updateSet(
        int id,
        double weightKg,
        int reps,
        Integer rpe,
        Integer restSeconds,
        String mutationId
    ) {
        return transaction(db -> {
            Entity set = activeEntity(db, "sets", id);
            ContentValues values = new ContentValues();
            values.put("weight_kg", weightKg);
            values.put("reps", reps);
            putNullable(values, "rpe", rpe);
            putNullable(values, "rest_seconds", restSeconds);
            if (db.update("sets", values, "rowid = ?", new String[]{String.valueOf(id)}) != 1) {
                throw new IllegalStateException("找不到組數");
            }
            bumpVersion(db, "sets", id);
            insertOutbox(
                db, mutationId, "set", set.syncId, "upsert", set.version, null,
                setPayload(db, set.syncId)
            );
            return setById(db, id);
        });
    }

    public void deleteSet(int id, String mutationId) {
        transaction(db -> {
            Entity set = activeEntity(db, "sets", id);
            JSONObject payload = setPayload(db, set.syncId);
            markDeleted(db, "sets", id);
            insertOutbox(
                db, mutationId, "set", set.syncId, "delete", set.version, null, payload
            );
            return null;
        });
    }

    public JSONObject endWorkout(int id, String mutationId) {
        return transaction(db -> {
            Entity workout = activeEntity(db, "workouts", id);
            JSONObject current = workoutById(db, id);
            if (!current.isNull("ended_at")) return current;
            db.execSQL(
                "UPDATE workouts SET ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    + "WHERE rowid = ?",
                new Object[]{id}
            );
            bumpVersion(db, "workouts", id);
            insertOutbox(
                db, mutationId, "workout", workout.syncId, "upsert", workout.version,
                workoutLeaseGeneration(db, id), workoutPayload(db, workout.syncId)
            );
            return workoutById(db, id);
        });
    }

    public void deleteWorkout(int id, String mutationId) {
        transaction(db -> {
            Entity workout = activeEntity(db, "workouts", id);
            if (count("sets", "workout_sync_id = ?", new String[]{workout.syncId}) > 0) {
                throw new IllegalStateException("含有組數的訓練不得刪除");
            }
            markDeleted(db, "workouts", id);
            db.delete("sync_state", "key = ?", new String[]{WORKOUT_TEMPLATE_PREFIX + workout.syncId});
            JSONObject payload = jsonObject();
            put(payload, "sync_id", workout.syncId);
            insertOutbox(
                db, mutationId, "workout", workout.syncId, "delete", workout.version,
                workoutLeaseGeneration(db, id), payload
            );
            return null;
        });
    }

    public JSONObject saveBodyMetric(
        String syncId, String date, double weightKg, Double bodyFatPct, String mutationId
    ) {
        return transaction(db -> {
            Entity existing = activeByColumn(db, "body_metrics", "date", date);
            String entitySyncId = existing == null ? syncId : existing.syncId;
            int baseVersion = existing == null ? 0 : existing.version;
            ContentValues values = new ContentValues();
            values.put("weight_kg", weightKg);
            putNullable(values, "body_fat_pct", bodyFatPct);
            int id;
            if (existing == null) {
                values.put("sync_id", entitySyncId);
                values.put("date", date);
                id = (int) db.insertOrThrow("body_metrics", null, values);
            } else {
                db.update("body_metrics", values, "rowid = ?", new String[]{String.valueOf(existing.id)});
                bumpVersion(db, "body_metrics", existing.id);
                id = existing.id;
            }
            insertOutbox(
                db, mutationId, "body_metric", entitySyncId, "upsert", baseVersion, null,
                bodyMetricPayload(db, entitySyncId)
            );
            return bodyMetricById(db, id);
        });
    }

    public void deleteBodyMetric(String date, String mutationId) {
        deleteByDate("body_metrics", "body_metric", date, mutationId);
    }

    public JSONObject saveDailyStatus(
        String syncId, String date, int energy, Integer sleepQuality, String note, String mutationId
    ) {
        return transaction(db -> {
            Entity existing = activeByColumn(db, "daily_status", "date", date);
            String entitySyncId = existing == null ? syncId : existing.syncId;
            int baseVersion = existing == null ? 0 : existing.version;
            ContentValues values = new ContentValues();
            values.put("energy", energy);
            putNullable(values, "sleep_quality", sleepQuality);
            putNullable(values, "note", note);
            int id;
            if (existing == null) {
                values.put("sync_id", entitySyncId);
                values.put("date", date);
                id = (int) db.insertOrThrow("daily_status", null, values);
            } else {
                db.update("daily_status", values, "rowid = ?", new String[]{String.valueOf(existing.id)});
                bumpVersion(db, "daily_status", existing.id);
                id = existing.id;
            }
            insertOutbox(
                db, mutationId, "daily_status", entitySyncId, "upsert", baseVersion, null,
                dailyStatusPayload(db, entitySyncId)
            );
            return dailyStatusById(db, id);
        });
    }

    public void deleteDailyStatus(String date, String mutationId) {
        deleteByDate("daily_status", "daily_status", date, mutationId);
    }

    public JSONObject putSetting(String key, String value, String syncId, String mutationId) {
        return transaction(db -> {
            Entity existing = activeByColumn(db, "app_settings", "key", key);
            String entitySyncId = existing == null ? syncId : existing.syncId;
            int baseVersion = existing == null ? 0 : existing.version;
            ContentValues values = new ContentValues();
            values.put("value", value);
            int id;
            if (existing == null) {
                values.put("key", key);
                values.put("sync_id", entitySyncId);
                id = (int) db.insertOrThrow("app_settings", null, values);
            } else {
                db.update("app_settings", values, "rowid = ?", new String[]{String.valueOf(existing.id)});
                bumpVersion(db, "app_settings", existing.id);
                id = existing.id;
            }
            insertOutbox(
                db, mutationId, "setting", entitySyncId, "upsert", baseVersion, null,
                settingPayload(db, entitySyncId)
            );
            return settingById(db, id);
        });
    }

    public JSONObject snapshot() {
        SQLiteDatabase db = writableDatabase();
        JSONObject result = jsonObject();
        put(result, "exercises", exercises(db));
        put(result, "templates", templates(db));
        put(result, "workouts", workouts(db));
        put(result, "sets", sets(db));
        put(result, "body_metrics", bodyMetrics(db));
        put(result, "daily_status", dailyStatuses(db));
        put(result, "settings", settings(db));
        return result;
    }

    public int pendingMutationCount() {
        return count("sync_outbox", "acked_at IS NULL", null);
    }

    private JSONArray exercises(SQLiteDatabase db) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "exercises", new String[]{"rowid AS id", "sync_id", "name_zh", "name_en", "muscle_group", "is_bodyweight"},
            "deleted_at IS NULL", null, null, null, "name_zh COLLATE NOCASE"
        )) {
            while (cursor.moveToNext()) result.put(exerciseJson(cursor));
        }
        return result;
    }

    private JSONArray templates(SQLiteDatabase db) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "templates", new String[]{"rowid AS id", "sync_id", "name", "weekdays"},
            "deleted_at IS NULL", null, null, null, "name COLLATE NOCASE"
        )) {
            while (cursor.moveToNext()) result.put(templateJson(db, cursor));
        }
        return result;
    }

    private JSONArray workouts(SQLiteDatabase db) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "workouts w LEFT JOIN templates t ON t.sync_id = w.template_sync_id",
            new String[]{
                "w.rowid AS id", "w.sync_id", "w.date", "t.rowid AS template_id", "w.note",
                "w.created_at", "w.ended_at", "w.lease_generation"
            },
            "w.deleted_at IS NULL", null, null, null, "w.date DESC, w.created_at DESC"
        )) {
            while (cursor.moveToNext()) result.put(workoutJson(db, cursor));
        }
        return result;
    }

    private JSONArray sets(SQLiteDatabase db) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "sets s LEFT JOIN workouts w ON w.sync_id = s.workout_sync_id "
                + "LEFT JOIN exercises e ON e.sync_id = s.exercise_sync_id",
            new String[]{
                "s.rowid AS id", "s.sync_id", "s.client_uuid", "w.rowid AS workout_id",
                "e.rowid AS exercise_id", "s.set_number", "s.weight_kg", "s.reps", "s.rpe",
                "s.rest_seconds", "s.created_at"
            },
            "s.deleted_at IS NULL", null, null, null, "s.created_at ASC"
        )) {
            while (cursor.moveToNext()) result.put(setJson(cursor));
        }
        return result;
    }

    private JSONArray bodyMetrics(SQLiteDatabase db) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "body_metrics", new String[]{"rowid AS id", "sync_id", "date", "weight_kg", "body_fat_pct"},
            "deleted_at IS NULL", null, null, null, "date DESC"
        )) {
            while (cursor.moveToNext()) result.put(bodyMetricJson(cursor));
        }
        return result;
    }

    private JSONArray dailyStatuses(SQLiteDatabase db) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "daily_status", new String[]{"rowid AS id", "sync_id", "date", "energy", "sleep_quality", "note"},
            "deleted_at IS NULL", null, null, null, "date DESC"
        )) {
            while (cursor.moveToNext()) result.put(dailyStatusJson(cursor));
        }
        return result;
    }

    private JSONArray settings(SQLiteDatabase db) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "app_settings", new String[]{"key", "sync_id", "value"},
            "deleted_at IS NULL", null, null, null, "key ASC"
        )) {
            while (cursor.moveToNext()) result.put(settingJson(cursor));
        }
        return result;
    }

    private JSONObject exerciseById(SQLiteDatabase db, int id) {
        try (Cursor cursor = db.query(
            "exercises", new String[]{"rowid AS id", "sync_id", "name_zh", "name_en", "muscle_group", "is_bodyweight"},
            "rowid = ? AND deleted_at IS NULL", new String[]{String.valueOf(id)}, null, null, null
        )) {
            if (cursor.moveToFirst()) return exerciseJson(cursor);
        }
        throw new IllegalArgumentException("找不到動作");
    }

    private JSONObject templateById(SQLiteDatabase db, int id) {
        try (Cursor cursor = db.query(
            "templates", new String[]{"rowid AS id", "sync_id", "name", "weekdays"},
            "rowid = ? AND deleted_at IS NULL", new String[]{String.valueOf(id)}, null, null, null
        )) {
            if (cursor.moveToFirst()) return templateJson(db, cursor);
        }
        throw new IllegalArgumentException("找不到課表");
    }

    private JSONObject workoutById(SQLiteDatabase db, int id) {
        try (Cursor cursor = db.query(
            "workouts w LEFT JOIN templates t ON t.sync_id = w.template_sync_id",
            new String[]{
                "w.rowid AS id", "w.sync_id", "w.date", "t.rowid AS template_id", "w.note",
                "w.created_at", "w.ended_at", "w.lease_generation"
            },
            "w.rowid = ? AND w.deleted_at IS NULL", new String[]{String.valueOf(id)}, null, null, null
        )) {
            return cursor.moveToFirst() ? workoutJson(db, cursor) : null;
        }
    }

    private JSONObject workoutBySyncId(SQLiteDatabase db, String syncId) {
        try (Cursor cursor = db.query(
            "workouts w LEFT JOIN templates t ON t.sync_id = w.template_sync_id",
            new String[]{
                "w.rowid AS id", "w.sync_id", "w.date", "t.rowid AS template_id", "w.note",
                "w.created_at", "w.ended_at", "w.lease_generation"
            },
            "w.sync_id = ? AND w.deleted_at IS NULL", new String[]{syncId}, null, null, null
        )) {
            return cursor.moveToFirst() ? workoutJson(db, cursor) : null;
        }
    }

    private JSONObject setById(SQLiteDatabase db, int id) {
        try (Cursor cursor = db.query(
            "sets s LEFT JOIN workouts w ON w.sync_id = s.workout_sync_id "
                + "LEFT JOIN exercises e ON e.sync_id = s.exercise_sync_id",
            new String[]{
                "s.rowid AS id", "s.sync_id", "s.client_uuid", "w.rowid AS workout_id",
                "e.rowid AS exercise_id", "s.set_number", "s.weight_kg", "s.reps", "s.rpe",
                "s.rest_seconds", "s.created_at"
            },
            "s.rowid = ? AND s.deleted_at IS NULL", new String[]{String.valueOf(id)}, null, null, null
        )) {
            return cursor.moveToFirst() ? setJson(cursor) : null;
        }
    }

    private JSONObject setBySyncId(SQLiteDatabase db, String syncId) {
        try (Cursor cursor = db.query(
            "sets s LEFT JOIN workouts w ON w.sync_id = s.workout_sync_id "
                + "LEFT JOIN exercises e ON e.sync_id = s.exercise_sync_id",
            new String[]{
                "s.rowid AS id", "s.sync_id", "s.client_uuid", "w.rowid AS workout_id",
                "e.rowid AS exercise_id", "s.set_number", "s.weight_kg", "s.reps", "s.rpe",
                "s.rest_seconds", "s.created_at"
            },
            "s.sync_id = ? AND s.deleted_at IS NULL", new String[]{syncId}, null, null, null
        )) {
            return cursor.moveToFirst() ? setJson(cursor) : null;
        }
    }

    private JSONObject bodyMetricById(SQLiteDatabase db, int id) {
        try (Cursor cursor = db.query(
            "body_metrics", new String[]{"rowid AS id", "sync_id", "date", "weight_kg", "body_fat_pct"},
            "rowid = ? AND deleted_at IS NULL", new String[]{String.valueOf(id)}, null, null, null
        )) {
            return cursor.moveToFirst() ? bodyMetricJson(cursor) : null;
        }
    }

    private JSONObject dailyStatusById(SQLiteDatabase db, int id) {
        try (Cursor cursor = db.query(
            "daily_status", new String[]{"rowid AS id", "sync_id", "date", "energy", "sleep_quality", "note"},
            "rowid = ? AND deleted_at IS NULL", new String[]{String.valueOf(id)}, null, null, null
        )) {
            return cursor.moveToFirst() ? dailyStatusJson(cursor) : null;
        }
    }

    private JSONObject settingById(SQLiteDatabase db, int id) {
        try (Cursor cursor = db.query(
            "app_settings", new String[]{"key", "sync_id", "value"},
            "rowid = ? AND deleted_at IS NULL", new String[]{String.valueOf(id)}, null, null, null
        )) {
            return cursor.moveToFirst() ? settingJson(cursor) : null;
        }
    }

    private JSONObject templateJson(SQLiteDatabase db, Cursor cursor) {
        JSONObject result = jsonObject();
        String syncId = cursor.getString(cursor.getColumnIndexOrThrow("sync_id"));
        put(result, "id", cursor.getInt(cursor.getColumnIndexOrThrow("id")));
        put(result, "sync_id", syncId);
        put(result, "name", cursor.getString(cursor.getColumnIndexOrThrow("name")));
        put(result, "weekdays", parseArray(cursor.getString(cursor.getColumnIndexOrThrow("weekdays"))));
        put(result, "exercises", templateExercises(db, syncId));
        return result;
    }

    private JSONArray templateExercises(SQLiteDatabase db, String templateSyncId) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "template_exercises te JOIN exercises e ON e.sync_id = te.exercise_sync_id",
            new String[]{
                "e.rowid AS exercise_id", "te.position", "te.default_sets", "te.rest_hint_seconds",
                "e.name_zh", "e.name_en", "e.muscle_group", "e.is_bodyweight"
            },
            "te.template_sync_id = ? AND te.deleted_at IS NULL AND e.deleted_at IS NULL",
            new String[]{templateSyncId}, null, null, "te.position ASC"
        )) {
            while (cursor.moveToNext()) {
                JSONObject item = jsonObject();
                put(item, "exercise_id", cursor.getInt(cursor.getColumnIndexOrThrow("exercise_id")));
                put(item, "position", cursor.getInt(cursor.getColumnIndexOrThrow("position")));
                putCursorValue(item, "default_sets", cursor, "default_sets");
                putCursorValue(item, "rest_hint_seconds", cursor, "rest_hint_seconds");
                putCursorValue(item, "name_zh", cursor, "name_zh");
                putCursorValue(item, "name_en", cursor, "name_en");
                putCursorValue(item, "muscle_group", cursor, "muscle_group");
                putCursorValue(item, "is_bodyweight", cursor, "is_bodyweight");
                result.put(item);
            }
        }
        return result;
    }

    private JSONObject exerciseJson(Cursor cursor) {
        return cursorJson(cursor, "id", "sync_id", "name_zh", "name_en", "muscle_group", "is_bodyweight");
    }

    private JSONObject workoutJson(SQLiteDatabase db, Cursor cursor) {
        JSONObject result = cursorJson(
            cursor, "id", "sync_id", "date", "template_id", "note", "created_at", "ended_at", "lease_generation"
        );
        String snapshot = syncState(db, WORKOUT_TEMPLATE_PREFIX + result.optString("sync_id"));
        put(result, "template_snapshot", snapshot == null ? null : parseObject(snapshot));
        return result;
    }

    private JSONObject setJson(Cursor cursor) {
        return cursorJson(
            cursor, "id", "sync_id", "client_uuid", "workout_id", "exercise_id", "set_number",
            "weight_kg", "reps", "rpe", "rest_seconds", "created_at"
        );
    }

    private JSONObject bodyMetricJson(Cursor cursor) {
        return cursorJson(cursor, "id", "sync_id", "date", "weight_kg", "body_fat_pct");
    }

    private JSONObject dailyStatusJson(Cursor cursor) {
        return cursorJson(cursor, "id", "sync_id", "date", "energy", "sleep_quality", "note");
    }

    private JSONObject settingJson(Cursor cursor) {
        return cursorJson(cursor, "key", "sync_id", "value");
    }

    private static JSONObject cursorJson(Cursor cursor, String... columns) {
        JSONObject result = jsonObject();
        for (String column : columns) putCursorValue(result, column, cursor, column);
        return result;
    }

    private static void putCursorValue(JSONObject target, String key, Cursor cursor, String column) {
        int index = cursor.getColumnIndexOrThrow(column);
        if (cursor.isNull(index)) {
            put(target, key, null);
        } else if (cursor.getType(index) == Cursor.FIELD_TYPE_FLOAT) {
            put(target, key, cursor.getDouble(index));
        } else if (cursor.getType(index) == Cursor.FIELD_TYPE_INTEGER) {
            put(target, key, cursor.getLong(index));
        } else {
            put(target, key, cursor.getString(index));
        }
    }

    private static JSONArray parseArray(String value) {
        try {
            return value == null ? new JSONArray() : new JSONArray(value);
        } catch (JSONException error) {
            throw new IllegalStateException("LocalStore 週期資料損壞", error);
        }
    }

    private static JSONObject parseObject(String value) {
        try {
            return new JSONObject(value);
        } catch (JSONException error) {
            throw new IllegalStateException("LocalStore JSON metadata 損壞", error);
        }
    }

    private JSONObject exercisePayload(SQLiteDatabase db, String syncId) {
        return payloadBySync(
            db, "exercises", syncId, "sync_id", "name_zh", "name_en", "muscle_group", "is_bodyweight"
        );
    }

    private JSONObject workoutPayload(SQLiteDatabase db, String syncId) {
        return payloadBySync(
            db, "workouts", syncId, "sync_id", "date", "template_sync_id", "note", "ended_at",
            "owner_device_id", "lease_generation"
        );
    }

    private JSONObject setPayload(SQLiteDatabase db, String syncId) {
        return payloadBySync(
            db, "sets", syncId, "sync_id", "client_uuid", "workout_sync_id", "exercise_sync_id",
            "set_number", "weight_kg", "reps", "rpe", "rest_seconds"
        );
    }

    private JSONObject bodyMetricPayload(SQLiteDatabase db, String syncId) {
        return payloadBySync(
            db, "body_metrics", syncId, "sync_id", "date", "weight_kg", "body_fat_pct"
        );
    }

    private JSONObject dailyStatusPayload(SQLiteDatabase db, String syncId) {
        return payloadBySync(
            db, "daily_status", syncId, "sync_id", "date", "energy", "sleep_quality", "note"
        );
    }

    private JSONObject settingPayload(SQLiteDatabase db, String syncId) {
        return payloadBySync(db, "app_settings", syncId, "sync_id", "key", "value");
    }

    private JSONObject templatePayload(SQLiteDatabase db, String syncId) {
        JSONObject payload = payloadBySync(db, "templates", syncId, "sync_id", "name");
        Entity template = activeByColumn(db, "templates", "sync_id", syncId);
        JSONObject templateJson = templateById(db, template.id);
        put(payload, "weekdays", templateJson.optJSONArray("weekdays"));
        JSONArray items = new JSONArray();
        try (Cursor cursor = db.query(
            "template_exercises", new String[]{"exercise_sync_id", "position", "default_sets", "rest_hint_seconds"},
            "template_sync_id = ? AND deleted_at IS NULL", new String[]{syncId}, null, null, "position ASC"
        )) {
            while (cursor.moveToNext()) {
                items.put(cursorJson(cursor, "exercise_sync_id", "position", "default_sets", "rest_hint_seconds"));
            }
        }
        put(payload, "exercises", items);
        return payload;
    }

    private JSONObject payloadBySync(SQLiteDatabase db, String table, String syncId, String... columns) {
        try (Cursor cursor = db.query(
            table, columns, "sync_id = ?", new String[]{syncId}, null, null, null
        )) {
            if (cursor.moveToFirst()) return cursorJson(cursor, columns);
        }
        throw new IllegalStateException("找不到 LocalStore 資料");
    }

    private void deleteByDate(String table, String entityType, String date, String mutationId) {
        transaction(db -> {
            Entity entity = activeByColumn(db, table, "date", date);
            JSONObject payload = "body_metrics".equals(table)
                ? bodyMetricPayload(db, entity.syncId)
                : dailyStatusPayload(db, entity.syncId);
            markDeleted(db, table, entity.id);
            insertOutbox(
                db, mutationId, entityType, entity.syncId, "delete", entity.version, null, payload
            );
            return null;
        });
    }

    private Entity activeEntity(SQLiteDatabase db, String table, int id) {
        try (Cursor cursor = db.query(
            table, new String[]{"rowid AS id", "sync_id", "version"},
            "rowid = ? AND deleted_at IS NULL", new String[]{String.valueOf(id)}, null, null, null
        )) {
            if (cursor.moveToFirst()) {
                return new Entity(cursor.getInt(0), cursor.getString(1), cursor.getInt(2));
            }
        }
        throw new IllegalArgumentException("找不到本機資料 handle");
    }

    private Entity activeByColumn(SQLiteDatabase db, String table, String column, String value) {
        try (Cursor cursor = db.query(
            table, new String[]{"rowid AS id", "sync_id", "version"},
            column + " = ? AND deleted_at IS NULL", new String[]{value}, null, null, null
        )) {
            if (cursor.moveToFirst()) {
                return new Entity(cursor.getInt(0), cursor.getString(1), cursor.getInt(2));
            }
        }
        return null;
    }

    private String activeSyncId(SQLiteDatabase db, String table, int id) {
        return activeEntity(db, table, id).syncId;
    }

    private int nextSetNumber(SQLiteDatabase db, String workoutSyncId, String exerciseSyncId) {
        try (Cursor cursor = db.rawQuery(
            "SELECT COALESCE(MAX(set_number), 0) + 1 FROM sets "
                + "WHERE workout_sync_id = ? AND exercise_sync_id = ?",
            new String[]{workoutSyncId, exerciseSyncId}
        )) {
            cursor.moveToFirst();
            return cursor.getInt(0);
        }
    }

    private static void putSyncState(SQLiteDatabase db, String key, String value) {
        ContentValues state = new ContentValues();
        state.put("key", key);
        state.put("value", value);
        db.insertWithOnConflict("sync_state", null, state, SQLiteDatabase.CONFLICT_REPLACE);
    }

    private static String syncState(SQLiteDatabase db, String key) {
        try (Cursor cursor = db.query(
            "sync_state", new String[]{"value"}, "key = ?", new String[]{key}, null, null, null
        )) {
            return cursor.moveToFirst() ? cursor.getString(0) : null;
        }
    }

    private int workoutLeaseGeneration(SQLiteDatabase db, int id) {
        try (Cursor cursor = db.query(
            "workouts", new String[]{"lease_generation"}, "rowid = ?",
            new String[]{String.valueOf(id)}, null, null, null
        )) {
            if (cursor.moveToFirst()) return cursor.getInt(0);
        }
        throw new IllegalStateException("找不到訓練");
    }

    private static void bumpVersion(SQLiteDatabase db, String table, int id) {
        db.execSQL(
            "UPDATE " + table + " SET version = version + 1, "
                + "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE rowid = ?",
            new Object[]{id}
        );
    }

    private static void markDeleted(SQLiteDatabase db, String table, int id) {
        db.execSQL(
            "UPDATE " + table + " SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), "
                + "version = version + 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                + "WHERE rowid = ?",
            new Object[]{id}
        );
    }

    private static String emptyTo(String value, String fallback) {
        return value == null || value.trim().isEmpty() ? fallback : value;
    }

    private static final class Entity {
        final int id;
        final String syncId;
        final int version;

        Entity(int id, String syncId, int version) {
            this.id = id;
            this.syncId = syncId;
            this.version = version;
        }
    }

    int count(String table, String selection, String[] args) {
        try (Cursor cursor = writableDatabase().query(
            table, new String[]{"COUNT(*)"}, selection, args, null, null, null
        )) {
            cursor.moveToFirst();
            return cursor.getInt(0);
        }
    }

    <T> T transaction(Transaction<T> work) {
        SQLiteDatabase db = writableDatabase();
        db.beginTransaction();
        try {
            T result = work.run(db);
            db.setTransactionSuccessful();
            return result;
        } finally {
            db.endTransaction();
        }
    }

    interface Transaction<T> {
        T run(SQLiteDatabase db);
    }

    private SQLiteDatabase writableDatabase() {
        if (migrationFailure != null) {
            throw new IllegalStateException(
                "LocalStore migration 失敗；已鎖定寫入以保留原始資料",
                migrationFailure
            );
        }
        return getWritableDatabase();
    }

    static void createVersion1Schema(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS exercises ("
            + "sync_id TEXT PRIMARY KEY NOT NULL,"
            + "name_zh TEXT NOT NULL, name_en TEXT NOT NULL, muscle_group TEXT NOT NULL,"
            + "is_bodyweight INTEGER NOT NULL DEFAULT 0 CHECK(is_bodyweight IN (0,1)),"
            + syncColumns() + ")");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS ux_exercises_name_zh_active "
            + "ON exercises(name_zh) WHERE deleted_at IS NULL");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS ux_exercises_name_en_active "
            + "ON exercises(name_en COLLATE NOCASE) WHERE deleted_at IS NULL");

        db.execSQL("CREATE TABLE IF NOT EXISTS templates ("
            + "sync_id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, weekdays TEXT,"
            + syncColumns() + ")");
        db.execSQL("CREATE TABLE IF NOT EXISTS template_exercises ("
            + "sync_id TEXT PRIMARY KEY NOT NULL, template_sync_id TEXT NOT NULL,"
            + "exercise_sync_id TEXT NOT NULL, position INTEGER NOT NULL CHECK(position >= 0),"
            + "default_sets INTEGER NOT NULL CHECK(default_sets > 0),"
            + "rest_hint_seconds INTEGER CHECK(rest_hint_seconds IS NULL OR rest_hint_seconds >= 0),"
            + syncColumns() + ","
            + "FOREIGN KEY(template_sync_id) REFERENCES templates(sync_id),"
            + "FOREIGN KEY(exercise_sync_id) REFERENCES exercises(sync_id))");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS ux_template_position_active "
            + "ON template_exercises(template_sync_id, position) WHERE deleted_at IS NULL");

        db.execSQL("CREATE TABLE IF NOT EXISTS workouts ("
            + "sync_id TEXT PRIMARY KEY NOT NULL, date TEXT NOT NULL, template_sync_id TEXT,"
            + "note TEXT, ended_at TEXT, owner_device_id TEXT,"
            + "lease_generation INTEGER NOT NULL DEFAULT 1 CHECK(lease_generation > 0),"
            + syncColumns() + ")");
        db.execSQL("CREATE INDEX IF NOT EXISTS ix_workouts_date ON workouts(date)");

        db.execSQL("CREATE TABLE IF NOT EXISTS sets ("
            + "sync_id TEXT PRIMARY KEY NOT NULL, client_uuid TEXT NOT NULL UNIQUE,"
            + "workout_sync_id TEXT NOT NULL, exercise_sync_id TEXT NOT NULL,"
            + "set_number INTEGER NOT NULL CHECK(set_number > 0),"
            + "weight_kg REAL NOT NULL CHECK(weight_kg >= 0), reps INTEGER NOT NULL CHECK(reps > 0),"
            + "rpe INTEGER CHECK(rpe IS NULL OR rpe BETWEEN 1 AND 10),"
            + "rest_seconds INTEGER CHECK(rest_seconds IS NULL OR rest_seconds >= 0),"
            + syncColumns() + ","
            + "FOREIGN KEY(workout_sync_id) REFERENCES workouts(sync_id),"
            + "FOREIGN KEY(exercise_sync_id) REFERENCES exercises(sync_id))");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS ux_sets_number_active "
            + "ON sets(workout_sync_id, exercise_sync_id, set_number) WHERE deleted_at IS NULL");

        db.execSQL("CREATE TABLE IF NOT EXISTS body_metrics ("
            + "sync_id TEXT PRIMARY KEY NOT NULL, date TEXT NOT NULL,"
            + "weight_kg REAL NOT NULL CHECK(weight_kg BETWEEN 30 AND 300),"
            + "body_fat_pct REAL CHECK(body_fat_pct IS NULL OR body_fat_pct > 0 AND body_fat_pct < 100),"
            + syncColumns() + ")");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS ux_body_metrics_date_active "
            + "ON body_metrics(date) WHERE deleted_at IS NULL");

        db.execSQL("CREATE TABLE IF NOT EXISTS daily_status ("
            + "sync_id TEXT PRIMARY KEY NOT NULL, date TEXT NOT NULL,"
            + "energy INTEGER NOT NULL CHECK(energy BETWEEN 1 AND 5),"
            + "sleep_quality INTEGER CHECK(sleep_quality IS NULL OR sleep_quality BETWEEN 1 AND 5),"
            + "note TEXT," + syncColumns() + ")");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_status_date_active "
            + "ON daily_status(date) WHERE deleted_at IS NULL");

        db.execSQL("CREATE TABLE IF NOT EXISTS app_settings ("
            + "key TEXT PRIMARY KEY NOT NULL, sync_id TEXT NOT NULL UNIQUE, value TEXT NOT NULL,"
            + syncColumns() + ")");
    }

    protected void migrateVersion2(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS sync_outbox ("
            + "mutation_id TEXT PRIMARY KEY NOT NULL, entity_type TEXT NOT NULL,"
            + "entity_id TEXT NOT NULL, operation TEXT NOT NULL "
            + "CHECK(operation IN ('upsert','delete','takeover')),"
            + "base_version INTEGER NOT NULL CHECK(base_version >= 0),"
            + "lease_generation INTEGER, payload_json TEXT NOT NULL,"
            + "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),"
            + "attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),"
            + "next_attempt_at TEXT, error_code TEXT, acked_at TEXT)");
        db.execSQL("CREATE INDEX IF NOT EXISTS ix_sync_outbox_pending "
            + "ON sync_outbox(acked_at, next_attempt_at, created_at)");
        db.execSQL("CREATE TABLE IF NOT EXISTS sync_state ("
            + "key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL "
            + "DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))");
        db.execSQL("INSERT OR IGNORE INTO sync_state(key, value) VALUES('server_cursor', '0')");
        db.execSQL("CREATE TABLE IF NOT EXISTS sync_conflicts ("
            + "conflict_id TEXT PRIMARY KEY NOT NULL, mutation_id TEXT,"
            + "entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, reason TEXT NOT NULL,"
            + "local_json TEXT NOT NULL, server_json TEXT NOT NULL,"
            + "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),"
            + "resolved_at TEXT)");
        db.execSQL("CREATE INDEX IF NOT EXISTS ix_sync_conflicts_unresolved "
            + "ON sync_conflicts(resolved_at, created_at)");
    }

    private static String syncColumns() {
        return "version INTEGER NOT NULL DEFAULT 0 CHECK(version >= 0),"
            + "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),"
            + "deleted_at TEXT, created_at TEXT NOT NULL "
            + "DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))";
    }

    private static void insertOutbox(
        SQLiteDatabase db,
        String mutationId,
        String entityType,
        String entityId,
        String operation,
        int baseVersion,
        Integer leaseGeneration,
        JSONObject payload
    ) {
        ContentValues values = new ContentValues();
        values.put("mutation_id", mutationId);
        values.put("entity_type", entityType);
        values.put("entity_id", entityId);
        values.put("operation", operation);
        values.put("base_version", baseVersion);
        putNullable(values, "lease_generation", leaseGeneration);
        values.put("payload_json", payload.toString());
        db.insertOrThrow("sync_outbox", null, values);
    }

    private static String seedId(String nameEn) {
        return UUID.nameUUIDFromBytes(
            ("liftlog:exercise:" + nameEn).getBytes(StandardCharsets.UTF_8)
        ).toString();
    }

    private static JSONObject jsonObject() {
        return new JSONObject();
    }

    private static void put(JSONObject object, String key, Object value) {
        try {
            object.put(key, value == null ? JSONObject.NULL : value);
        } catch (JSONException error) {
            throw new IllegalArgumentException("無法建立 mutation payload", error);
        }
    }

    private static void putNullable(ContentValues values, String key, String value) {
        if (value == null) values.putNull(key); else values.put(key, value);
    }

    private static void putNullable(ContentValues values, String key, Integer value) {
        if (value == null) values.putNull(key); else values.put(key, value);
    }

    private static void putNullable(ContentValues values, String key, Double value) {
        if (value == null) values.putNull(key); else values.put(key, value);
    }
}
