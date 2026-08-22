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
import java.util.Arrays;
import java.util.UUID;

/** Android 的唯一 domain store；所有本地 mutation 與 outbox 必須在同一個 transaction。 */
public class LocalStore extends SQLiteOpenHelper {
    static final String DATABASE_NAME = "liftlog-local.db";
    static final int DATABASE_VERSION = 4;
    private static final String WORKOUT_TEMPLATE_PREFIX = "workout_template:";
    // F159：動作的計量模式，值域與 server app/models.py 的 EXERCISE_MODE_REPS 一致。
    private static final String EXERCISE_MODE_REPS = "reps";
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
        // F159：migrateVersion4 要在 migrateVersion3 之前跑——v3 的 enqueueExistingDomainRows
        // 會用 exercisePayload／setPayload 把既有列補進 outbox，而這兩個共用函式現在會讀
        // v4 才新增的 mode／duration_seconds 欄位；順序反過來會撞「no such column」。
        migrateVersion4(db);
        migrateVersion3(db);
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        try {
            if (oldVersion < 1) createVersion1Schema(db);
            if (oldVersion < 2) migrateVersion2(db);
            if (oldVersion < 4) migrateVersion4(db);
            if (oldVersion < 3) migrateVersion3(db);
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
                String syncId = seedId(exercise[1]);
                ContentValues values = new ContentValues();
                values.put("sync_id", syncId);
                values.put("name_zh", exercise[0]);
                values.put("name_en", exercise[1]);
                values.put("muscle_group", exercise[2]);
                values.put("is_bodyweight", Integer.parseInt(exercise[3]));
                long row = db.insertWithOnConflict(
                    "exercises", null, values, SQLiteDatabase.CONFLICT_IGNORE
                );
                if (row != -1) {
                    insertOutbox(
                        db, seedMutationId(exercise[1]), "exercise", syncId, "upsert", 0,
                        null, exercisePayload(db, syncId)
                    );
                    created++;
                }
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

    /**
     * 建立 set 與 mutation receipt；供 F140 的 WebView 與 overlay 共用。
     * 舊呼叫端（RestOverlay、F140 instrumented test）只支援次數型、reps 不可為 null，
     * 沿用這個多載；F159 起 WebView 橋接（LocalStorePlugin）走下面帶 durationSeconds 的版本。
     */
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
        addSet(
            syncId, clientUuid, workoutId, exerciseId, setNumber, weightKg, reps, null,
            rpe, restSeconds, leaseGeneration, mutationId
        );
    }

    /** F159：reps／durationSeconds 兩者擇一為 null（呼叫端已驗證互斥），時間型 reps 傳 null。 */
    public void addSet(
        String syncId,
        String clientUuid,
        int workoutId,
        int exerciseId,
        Integer setNumber,
        double weightKg,
        Integer reps,
        Integer durationSeconds,
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
            putNullable(set, "reps", reps);
            putNullable(set, "duration_seconds", durationSeconds);
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

    /** 舊呼叫端（未帶 mode，如 SyncClientTest）沿用次數型預設；F159 起一律走下面帶 mode 的版本。 */
    public JSONObject createExercise(
        String syncId,
        String nameZh,
        String nameEn,
        String muscleGroup,
        boolean isBodyweight,
        String mutationId
    ) {
        return createExercise(syncId, nameZh, nameEn, muscleGroup, isBodyweight, null, mutationId);
    }

    public JSONObject createExercise(
        String syncId,
        String nameZh,
        String nameEn,
        String muscleGroup,
        boolean isBodyweight,
        String mode,
        String mutationId
    ) {
        return transaction(db -> {
            ContentValues exercise = new ContentValues();
            exercise.put("sync_id", syncId);
            exercise.put("name_zh", nameZh);
            exercise.put("name_en", emptyTo(nameEn, nameZh));
            exercise.put("muscle_group", emptyTo(muscleGroup, "其他"));
            exercise.put("is_bodyweight", isBodyweight ? 1 : 0);
            exercise.put("mode", emptyTo(mode, EXERCISE_MODE_REPS));
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
        Integer reps,
        Integer durationSeconds,
        Integer rpe,
        Integer restSeconds,
        String mutationId
    ) {
        return transaction(db -> {
            Entity set = activeEntity(db, "sets", id);
            ContentValues values = new ContentValues();
            values.put("weight_kg", weightKg);
            putNullable(values, "reps", reps);
            putNullable(values, "duration_seconds", durationSeconds);
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

    public int failedMutationCount() {
        return count("sync_outbox", "acked_at IS NULL AND error_code IS NOT NULL", null);
    }

    public int unresolvedConflictCount() {
        return count("sync_conflicts", "resolved_at IS NULL", null);
    }

    /**
     * F148：登出／刪帳後清空本機——outbox、衝突收件匣、全部 domain 表、sync 游標全部歸零。
     *
     * <p>刪除順序照 FK 方向：先刪會參照別人的子表（sets／template_exercises），
     * 才刪被參照的父表（exercises／workouts／templates），否則會撞外鍵約束。
     */
    public void wipeAllLocalData() {
        transaction(db -> {
            db.delete("sync_outbox", null, null);
            db.delete("sync_conflicts", null, null);
            db.delete("sets", null, null);
            db.delete("template_exercises", null, null);
            db.delete("workouts", null, null);
            db.delete("templates", null, null);
            db.delete("exercises", null, null);
            db.delete("body_metrics", null, null);
            db.delete("daily_status", null, null);
            db.delete("app_settings", null, null);
            putSyncState(db, "server_cursor", "0");
            putSyncState(db, "bootstrap_complete", "0");
            putSyncState(db, "last_synced_at", "");
            putSyncState(db, "last_error_code", "");
            putSyncState(db, "next_sync_at", "0");
            putSyncState(db, "sync_attempt_count", "0");
            return null;
        });
    }

    /** 未解決的衝突收件匣：每筆都帶本機與雲端兩份值，讓使用者自己選。 */
    public JSONObject conflicts() {
        SQLiteDatabase db = writableDatabase();
        JSONArray items = new JSONArray();
        try (Cursor cursor = db.query(
            "sync_conflicts",
            new String[]{"conflict_id", "mutation_id", "entity_type", "entity_id", "reason",
                "local_json", "server_json", "created_at"},
            "resolved_at IS NULL", null, null, null, "created_at ASC"
        )) {
            while (cursor.moveToNext()) {
                JSONObject item = jsonObject();
                put(item, "conflictId", cursor.getString(0));
                put(item, "mutationId", cursor.getString(1));
                put(item, "entityType", cursor.getString(2));
                put(item, "entityId", cursor.getString(3));
                put(item, "reason", cursor.getString(4));
                put(item, "local", parseObject(cursor.getString(5)));
                put(item, "server", nullableObject(cursor.getString(6)));
                put(item, "createdAt", cursor.getString(7));
                items.put(item);
            }
        }
        JSONObject result = jsonObject();
        put(result, "items", items);
        return result;
    }

    /**
     * 解決一筆衝突。`local` 保留本機值並以 server version 重排成新的 mutation；
     * `server` 直接採用雲端值並丟棄本機這次修改。兩者都不做 last-write-wins 自動判定。
     */
    public JSONObject resolveConflict(String conflictId, String choice, String mutationId) {
        boolean keepLocal = "local".equals(choice);
        if (!keepLocal && !"server".equals(choice)) {
            throw new IllegalArgumentException("不支援的衝突解決方式");
        }
        return transaction(db -> {
            try {
                return applyResolution(db, conflictId, keepLocal, mutationId);
            } catch (JSONException error) {
                throw new IllegalStateException("衝突資料格式不合法", error);
            }
        });
    }

    private JSONObject applyResolution(
        SQLiteDatabase db, String conflictId, boolean keepLocal, String mutationId
    ) throws JSONException {
        String[] row = unresolvedConflict(db, conflictId);
        String entityType = row[0];
        String entityId = row[1];
        JSONObject local = parseObject(row[3]);
        JSONObject server = nullableObject(row[4]);
        String operation = pendingOperation(db, row[2]);
        String table = tableForEntity(entityType);
        boolean tombstoned = server != null && !server.isNull("deleted_at");
        if (keepLocal && server == null) {
            throw new IllegalArgumentException("雲端沒有這筆資料，無法保留本機版本");
        }
        if (keepLocal && tombstoned) {
            throw new IllegalArgumentException("雲端已刪除這筆資料，只能採用雲端");
        }

        if (keepLocal) {
            int serverVersion = server.getInt("version");
            if ("delete".equals(operation)) {
                applyRemoteUpsert(db, entityType, table, rebased(server, local, serverVersion));
                markDeletedBySync(db, table, entityId);
            } else {
                applyRemoteUpsert(db, entityType, table, rebased(server, local, serverVersion));
            }
            insertOutbox(
                db, mutationId, entityType, entityId, operation, serverVersion, null, local
            );
        } else if (tombstoned) {
            applyRemoteDelete(db, table, server);
        } else if (server != null) {
            applyRemoteUpsert(db, entityType, table, server);
        }

        db.delete("sync_outbox", "mutation_id = ?", new String[]{row[2]});
        db.execSQL(
            "UPDATE sync_conflicts SET resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                + "WHERE conflict_id = ?",
            new Object[]{conflictId}
        );
        if (count("sync_outbox", "acked_at IS NULL AND error_code IS NOT NULL", null) == 0) {
            putSyncState(db, "last_error_code", "");
            putSyncState(db, "next_sync_at", "0");
        }
        return syncStatus(db);
    }

    /** 保留本機值時，欄位用本機的、版本與時間用 server 的——這樣重送才不會再撞版本。 */
    private static JSONObject rebased(JSONObject server, JSONObject local, int serverVersion)
        throws JSONException {
        JSONObject change = jsonObject();
        put(change, "entity_id", server.getString("entity_id"));
        put(change, "version", serverVersion);
        put(change, "updated_at", server.getString("updated_at"));
        put(change, "deleted_at", null);
        put(change, "payload", local);
        return change;
    }

    private static String[] unresolvedConflict(SQLiteDatabase db, String conflictId) {
        try (Cursor cursor = db.query(
            "sync_conflicts",
            new String[]{"entity_type", "entity_id", "mutation_id", "local_json", "server_json"},
            "conflict_id = ? AND resolved_at IS NULL",
            new String[]{conflictId}, null, null, null
        )) {
            if (!cursor.moveToFirst()) {
                throw new IllegalArgumentException("找不到未解決的衝突");
            }
            return new String[]{
                cursor.getString(0), cursor.getString(1), cursor.getString(2),
                cursor.getString(3), cursor.getString(4)
            };
        }
    }

    private static String pendingOperation(SQLiteDatabase db, String mutationId) {
        try (Cursor cursor = db.query(
            "sync_outbox", new String[]{"operation"},
            "mutation_id = ?", new String[]{mutationId}, null, null, null
        )) {
            if (!cursor.moveToFirst()) {
                throw new IllegalStateException("衝突對應的 mutation 已不存在");
            }
            return cursor.getString(0);
        }
    }

    private static void markDeletedBySync(SQLiteDatabase db, String table, String syncId) {
        db.execSQL(
            "UPDATE " + table + " SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                + "WHERE sync_id = ?",
            new Object[]{syncId}
        );
    }

    public long nextSyncAt() {
        String value = syncState(writableDatabase(), "next_sync_at");
        return value == null || value.isEmpty() ? 0 : Long.parseLong(value);
    }

    public JSONObject syncStatus() {
        return syncStatus(writableDatabase());
    }

    private JSONObject syncStatus(SQLiteDatabase db) {
        int failed = count("sync_outbox", "acked_at IS NULL AND error_code IS NOT NULL", null);
        int pending = count("sync_outbox", "acked_at IS NULL AND error_code IS NULL", null);
        String errorCode = syncState(db, "last_error_code");
        JSONObject result = jsonObject();
        put(result, "state", failed > 0 || errorCode != null && !errorCode.isEmpty()
            ? "offline".equals(errorCode) ? "offline" : "error"
            : pending > 0 ? "pending" : "synced");
        put(result, "pending", pending);
        put(result, "failed", failed);
        put(result, "cursor", serverCursor(db));
        put(result, "lastSyncedAt", syncState(db, "last_synced_at"));
        put(result, "errorCode", errorCode);
        put(result, "nextSyncAt", nextSyncAt());
        put(result, "bootstrapComplete", "1".equals(syncState(db, "bootstrap_complete")));
        put(result, "conflicts", count("sync_conflicts", "resolved_at IS NULL", null));
        put(result, "failed_items", failedItems(db));
        return result;
    }

    /** F160 ③：讓使用者知道哪一筆沒送出去，不只是幾筆——每筆帶可辨識的實體與錯誤碼。 */
    private JSONArray failedItems(SQLiteDatabase db) {
        JSONArray items = new JSONArray();
        try (Cursor cursor = db.query(
            "sync_outbox",
            new String[]{"mutation_id", "entity_type", "entity_id", "error_code", "created_at"},
            "acked_at IS NULL AND error_code IS NOT NULL", null, null, null, "created_at ASC"
        )) {
            while (cursor.moveToNext()) {
                JSONObject item = jsonObject();
                put(item, "mutationId", cursor.getString(0));
                put(item, "entityType", cursor.getString(1));
                put(item, "entityId", cursor.getString(2));
                put(item, "errorCode", cursor.getString(3));
                put(item, "createdAt", cursor.getString(4));
                items.put(item);
            }
        }
        return items;
    }

    public void markSyncSuccess(long nowMillis) {
        transaction(db -> {
            putSyncState(db, "last_synced_at", String.valueOf(nowMillis));
            putSyncState(db, "last_error_code", "");
            putSyncState(db, "sync_attempt_count", "0");
            try (Cursor cursor = db.query(
                "sync_outbox", new String[]{"COUNT(*)"},
                "acked_at IS NULL AND error_code IS NULL", null, null, null, null
            )) {
                cursor.moveToFirst();
                if (cursor.getInt(0) == 0) putSyncState(db, "next_sync_at", "0");
            }
            return null;
        });
    }

    public void markSyncError(String errorCode) {
        transaction(db -> {
            putSyncState(db, "last_error_code", emptyTo(errorCode, "sync_error"));
            putSyncState(db, "next_sync_at", "0");
            return null;
        });
    }

    int nextPullAttemptNumber() {
        String value = syncState(writableDatabase(), "sync_attempt_count");
        return (value == null ? 0 : Integer.parseInt(value)) + 1;
    }

    /** Pull 沒有 mutation body 可掛 retry；將次數與時間保存在 sync_state。 */
    public void markPullFailure(String errorCode, long retryAtMillis) {
        transaction(db -> {
            int attempt = nextPullAttemptNumber();
            putSyncState(db, "sync_attempt_count", String.valueOf(attempt));
            putSyncState(db, "last_error_code", emptyTo(errorCode, "sync_failed"));
            putSyncState(db, "next_sync_at", String.valueOf(retryAtMillis));
            return null;
        });
    }

    /** 依 server 邊界產生可重送的 push body；不改 mutation_id，也不先清 outbox。 */
    public JSONObject pendingPushBody(
        String deviceId, int maxCount, int maxBytes, long nowMillis
    ) {
        if (deviceId == null || deviceId.trim().isEmpty()) {
            throw new IllegalArgumentException("缺少 device_id");
        }
        if (maxCount < 1 || maxCount > 500 || maxBytes < 1) {
            throw new IllegalArgumentException("sync batch 邊界不合法");
        }
        SQLiteDatabase db = writableDatabase();
        JSONObject body = jsonObject();
        put(body, "schema_version", 1);
        put(body, "device_id", deviceId);
        JSONArray mutations = new JSONArray();
        put(body, "mutations", mutations);
        try (Cursor cursor = db.query(
            "sync_outbox",
            new String[]{
                "mutation_id", "entity_type", "entity_id", "operation", "base_version",
                "lease_generation", "payload_json", "next_attempt_at"
            },
            "acked_at IS NULL AND error_code IS NULL",
            null,
            null,
            null,
            "created_at ASC, rowid ASC"
        )) {
            while (cursor.moveToNext() && mutations.length() < maxCount) {
                String nextAttempt = cursor.getString(7);
                if (nextAttempt != null && Long.parseLong(nextAttempt) > nowMillis) break;
                JSONObject mutation = jsonObject();
                put(mutation, "mutation_id", cursor.getString(0));
                put(mutation, "entity_type", cursor.getString(1));
                put(mutation, "entity_id", cursor.getString(2));
                put(mutation, "operation", cursor.getString(3));
                put(mutation, "base_version", cursor.getInt(4));
                if (cursor.isNull(5)) put(mutation, "lease_generation", JSONObject.NULL);
                else put(mutation, "lease_generation", cursor.getInt(5));
                put(mutation, "payload", new JSONObject(cursor.getString(6)));
                mutations.put(mutation);
                if (body.toString().getBytes(StandardCharsets.UTF_8).length > maxBytes) {
                    mutations.remove(mutations.length() - 1);
                    if (mutations.length() == 0) {
                        throw new BatchTooLarge(cursor.getString(0));
                    }
                    break;
                }
            }
        } catch (JSONException error) {
            throw new IllegalStateException("outbox JSON 已損壞", error);
        }
        return body;
    }

    /** 暫時錯誤只延後同一批 mutation；資料與 mutation_id 都保留。 */
    public void markPushFailure(JSONObject body, String errorCode, long retryAtMillis) {
        transaction(db -> {
            try {
                JSONArray mutations = body.getJSONArray("mutations");
                for (int index = 0; index < mutations.length(); index++) {
                    String mutationId = mutations.getJSONObject(index).getString("mutation_id");
                    db.execSQL(
                        "UPDATE sync_outbox SET attempt_count = attempt_count + 1, "
                            + "next_attempt_at = ?, error_code = NULL "
                            + "WHERE mutation_id = ? AND acked_at IS NULL",
                        new Object[]{String.valueOf(retryAtMillis), mutationId}
                    );
                }
                putSyncState(db, "last_error_code", emptyTo(errorCode, "sync_failed"));
                putSyncState(db, "next_sync_at", String.valueOf(retryAtMillis));
                return null;
            } catch (JSONException error) {
                throw new IllegalArgumentException("push body 格式不合法", error);
            }
        });
    }

    /**
     * F160：整包層級的 HTTP 錯誤（409/403/422 等）不再呼叫這個方法——SyncClient 那類錯誤一律
     * 走 retryable 相同的 backoff（見 SyncClient.syncOnce）。這裡沒有 HTTP 呼叫點了，留給未來
     * server 明確指認「就是這批資料本身壞了」（而不是版本/環境不對）時使用。
     */
    public void markPushPermanentFailure(JSONObject body, String errorCode) {
        transaction(db -> {
            try {
                JSONArray mutations = body.getJSONArray("mutations");
                for (int index = 0; index < mutations.length(); index++) {
                    markMutationFailed(
                        db, mutations.getJSONObject(index).getString("mutation_id"), errorCode
                    );
                }
                putSyncState(db, "last_error_code", emptyTo(errorCode, "sync_failed"));
                putSyncState(db, "next_sync_at", "0");
                return null;
            } catch (JSONException error) {
                throw new IllegalArgumentException("push body 格式不合法", error);
            }
        });
    }

    public void markMutationFailed(String mutationId, String errorCode) {
        transaction(db -> {
            markMutationFailed(db, mutationId, errorCode);
            putSyncState(db, "last_error_code", emptyTo(errorCode, "sync_failed"));
            putSyncState(db, "next_sync_at", "0");
            return null;
        });
    }

    int nextAttemptNumber(JSONObject body) {
        try {
            JSONArray mutations = body.getJSONArray("mutations");
            int highest = 0;
            SQLiteDatabase db = writableDatabase();
            for (int index = 0; index < mutations.length(); index++) {
                String mutationId = mutations.getJSONObject(index).getString("mutation_id");
                try (Cursor cursor = db.query(
                    "sync_outbox", new String[]{"attempt_count"}, "mutation_id = ?",
                    new String[]{mutationId}, null, null, null
                )) {
                    if (cursor.moveToFirst()) highest = Math.max(highest, cursor.getInt(0));
                }
            }
            return highest + 1;
        } catch (JSONException error) {
            throw new IllegalArgumentException("push body 格式不合法", error);
        }
    }

    /** accepted receipt、下一筆 base_version 與 domain server version 在同一 transaction。 */
    public void applyPushResponse(JSONObject response, long nowMillis) {
        transaction(db -> {
            try {
                JSONArray accepted = response.getJSONArray("accepted");
                JSONArray conflicts = response.getJSONArray("conflicts");
                for (int index = 0; index < accepted.length(); index++) {
                    JSONObject item = accepted.getJSONObject(index);
                    acknowledgeMutation(
                        db,
                        item.getString("mutation_id"),
                        item.getInt("version"),
                        nowMillis
                    );
                }
                for (int index = 0; index < conflicts.length(); index++) {
                    recordPushConflict(db, conflicts.getJSONObject(index));
                }
                putSyncState(db, "last_error_code", "");
                putSyncState(db, "next_sync_at", "0");
                return null;
            } catch (JSONException error) {
                throw new IllegalArgumentException("push response 格式不合法", error);
            }
        });
    }

    public long serverCursor() {
        return serverCursor(writableDatabase());
    }

    /** change apply 與 cursor commit 共用 transaction；任一未知/損壞 change 全批回滾。 */
    public void applyPullPage(JSONObject page) {
        transaction(db -> {
            try {
                long cursor = serverCursor(db);
                long expected = cursor;
                JSONArray changes = page.getJSONArray("changes");
                for (int index = 0; index < changes.length(); index++) {
                    JSONObject change = changes.getJSONObject(index);
                    long sequence = change.getLong("server_seq");
                    if (change.getInt("schema_version") != 1 || sequence != expected + 1) {
                        throw new IllegalArgumentException("sync sequence/schema 不連續");
                    }
                    String entityType = change.getString("entity_type");
                    String entityId = change.getString("entity_id");
                    String operation = change.getString("operation");
                    String table = tableForEntity(entityType);
                    if (!operation.equals("upsert") && !operation.equals("delete")) {
                        throw new IllegalArgumentException("不支援的 sync operation");
                    }
                    if (!hasPendingMutation(db, entityType, entityId)) {
                        if (operation.equals("delete")) applyRemoteDelete(db, table, change);
                        else applyRemoteUpsert(db, entityType, table, change);
                    }
                    expected = sequence;
                }
                if (page.getLong("next_cursor") != expected) {
                    throw new IllegalArgumentException("next_cursor 與 change 不一致");
                }
                putSyncState(db, "server_cursor", String.valueOf(expected));
                putSyncState(db, "bootstrap_complete", page.getBoolean("has_more") ? "0" : "1");
                return null;
            } catch (JSONException error) {
                throw new IllegalArgumentException("pull response 格式不合法", error);
            }
        });
    }

    private JSONArray exercises(SQLiteDatabase db) {
        JSONArray result = new JSONArray();
        try (Cursor cursor = db.query(
            "exercises",
            new String[]{
                "rowid AS id", "sync_id", "name_zh", "name_en", "muscle_group", "is_bodyweight", "mode"
            },
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
                "e.rowid AS exercise_id", "s.set_number", "s.weight_kg", "s.reps",
                "s.duration_seconds", "s.rpe", "s.rest_seconds", "s.created_at"
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
            "exercises",
            new String[]{
                "rowid AS id", "sync_id", "name_zh", "name_en", "muscle_group", "is_bodyweight", "mode"
            },
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
                "e.rowid AS exercise_id", "s.set_number", "s.weight_kg", "s.reps",
                "s.duration_seconds", "s.rpe", "s.rest_seconds", "s.created_at"
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
                "e.rowid AS exercise_id", "s.set_number", "s.weight_kg", "s.reps",
                "s.duration_seconds", "s.rpe", "s.rest_seconds", "s.created_at"
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
        return cursorJson(
            cursor, "id", "sync_id", "name_zh", "name_en", "muscle_group", "is_bodyweight", "mode"
        );
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
            "weight_kg", "reps", "duration_seconds", "rpe", "rest_seconds", "created_at"
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

    /** server 端可能回 null（雲端根本沒有這筆），存進 sync_conflicts 時是字面 "null"。 */
    private static JSONObject nullableObject(String value) {
        return value == null || "null".equals(value) ? null : parseObject(value);
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
            db, "exercises", syncId, "sync_id", "name_zh", "name_en", "muscle_group",
            "is_bodyweight", "mode"
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
            "set_number", "weight_kg", "reps", "duration_seconds", "rpe", "rest_seconds"
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
        try (Cursor cursor = db.query(
            "templates", new String[]{"weekdays"}, "sync_id = ?",
            new String[]{syncId}, null, null, null
        )) {
            if (!cursor.moveToFirst()) throw new IllegalStateException("找不到 LocalStore 資料");
            put(payload, "weekdays", cursor.isNull(0) ? null : parseArray(cursor.getString(0)));
        }
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

    private static long serverCursor(SQLiteDatabase db) {
        String value = syncState(db, "server_cursor");
        return value == null ? 0 : Long.parseLong(value);
    }

    private static void acknowledgeMutation(
        SQLiteDatabase db, String mutationId, int version, long nowMillis
    ) {
        try (Cursor cursor = db.query(
            "sync_outbox",
            new String[]{"entity_type", "entity_id"},
            "mutation_id = ?",
            new String[]{mutationId},
            null,
            null,
            null
        )) {
            if (!cursor.moveToFirst()) {
                throw new IllegalArgumentException("server 回傳未知 mutation receipt");
            }
            String entityType = cursor.getString(0);
            String entityId = cursor.getString(1);
            ContentValues receipt = new ContentValues();
            receipt.put("acked_at", String.valueOf(nowMillis));
            receipt.putNull("next_attempt_at");
            receipt.putNull("error_code");
            db.update(
                "sync_outbox", receipt, "mutation_id = ?", new String[]{mutationId}
            );

            String table = tableForEntity(entityType);
            ContentValues serverVersion = new ContentValues();
            serverVersion.put("version", version);
            db.update(table, serverVersion, "sync_id = ?", new String[]{entityId});

            ContentValues nextBase = new ContentValues();
            nextBase.put("base_version", version);
            db.update(
                "sync_outbox",
                nextBase,
                "entity_type = ? AND entity_id = ? AND acked_at IS NULL "
                    + "AND mutation_id != ? AND error_code IS NULL",
                new String[]{entityType, entityId, mutationId}
            );
        }
    }

    private static void recordPushConflict(SQLiteDatabase db, JSONObject conflict)
        throws JSONException {
        String mutationId = conflict.getString("mutation_id");
        String reason = conflict.getString("reason");
        try (Cursor cursor = db.query(
            "sync_outbox",
            new String[]{"entity_type", "entity_id", "payload_json"},
            "mutation_id = ? AND acked_at IS NULL",
            new String[]{mutationId},
            null,
            null,
            null
        )) {
            if (!cursor.moveToFirst()) return;
            ContentValues values = new ContentValues();
            values.put("conflict_id", UUID.nameUUIDFromBytes(
                ("liftlog:conflict:" + mutationId + ":" + reason)
                    .getBytes(StandardCharsets.UTF_8)
            ).toString());
            values.put("mutation_id", mutationId);
            values.put("entity_type", cursor.getString(0));
            values.put("entity_id", cursor.getString(1));
            values.put("reason", reason);
            values.put("local_json", cursor.getString(2));
            values.put(
                "server_json",
                conflict.isNull("server") ? "null" : conflict.getJSONObject("server").toString()
            );
            db.insertWithOnConflict(
                "sync_conflicts", null, values, SQLiteDatabase.CONFLICT_REPLACE
            );
            ContentValues failed = new ContentValues();
            failed.put("error_code", reason);
            failed.putNull("next_attempt_at");
            db.update(
                "sync_outbox", failed, "mutation_id = ?", new String[]{mutationId}
            );
        }
    }

    private static boolean hasPendingMutation(
        SQLiteDatabase db, String entityType, String entityId
    ) {
        try (Cursor cursor = db.query(
            "sync_outbox",
            new String[]{"COUNT(*)"},
            "entity_type = ? AND entity_id = ? AND acked_at IS NULL",
            new String[]{entityType, entityId},
            null,
            null,
            null
        )) {
            cursor.moveToFirst();
            return cursor.getInt(0) > 0;
        }
    }

    private static String tableForEntity(String entityType) {
        switch (entityType) {
            case "exercise": return "exercises";
            case "template": return "templates";
            case "workout": return "workouts";
            case "set": return "sets";
            case "body_metric": return "body_metrics";
            case "daily_status": return "daily_status";
            case "setting": return "app_settings";
            default: throw new IllegalArgumentException("不支援的 sync entity: " + entityType);
        }
    }

    private static void applyRemoteDelete(
        SQLiteDatabase db, String table, JSONObject change
    ) throws JSONException {
        ContentValues values = new ContentValues();
        values.put("version", change.getInt("version"));
        values.put("updated_at", change.getString("updated_at"));
        values.put(
            "deleted_at",
            change.isNull("deleted_at") ? change.getString("updated_at")
                : change.getString("deleted_at")
        );
        db.update(table, values, "sync_id = ?", new String[]{change.getString("entity_id")});
        if (table.equals("templates")) {
            db.delete(
                "template_exercises", "template_sync_id = ?",
                new String[]{change.getString("entity_id")}
            );
        }
    }

    private static void applyRemoteUpsert(
        SQLiteDatabase db, String entityType, String table, JSONObject change
    ) throws JSONException {
        JSONObject payload = change.getJSONObject("payload");
        String entityId = change.getString("entity_id");
        if (!entityId.equals(payload.getString("sync_id"))) {
            throw new IllegalArgumentException("payload sync_id 與 entity_id 不一致");
        }
        ContentValues values = new ContentValues();
        values.put("sync_id", entityId);
        values.put("version", change.getInt("version"));
        values.put("updated_at", change.getString("updated_at"));
        values.putNull("deleted_at");
        switch (entityType) {
            case "exercise":
                values.put("name_zh", payload.getString("name_zh"));
                values.put("name_en", payload.getString("name_en"));
                values.put("muscle_group", payload.getString("muscle_group"));
                values.put("is_bodyweight", payload.getBoolean("is_bodyweight") ? 1 : 0);
                // F159：舊版 server payload／pre-F105 資料不帶 mode，視為次數型。
                values.put(
                    "mode", payload.isNull("mode") ? EXERCISE_MODE_REPS : payload.getString("mode")
                );
                break;
            case "template":
                values.put("name", payload.getString("name"));
                if (payload.isNull("weekdays")) values.putNull("weekdays");
                else values.put("weekdays", payload.getJSONArray("weekdays").toString());
                break;
            case "workout":
                values.put("date", payload.getString("date"));
                putJsonNullable(values, payload, "template_sync_id");
                putJsonNullable(values, payload, "note");
                putJsonNullable(values, payload, "ended_at");
                putJsonNullable(values, payload, "owner_device_id");
                values.put("lease_generation", payload.getInt("lease_generation"));
                break;
            case "set":
                values.put("client_uuid", payload.getString("client_uuid"));
                values.put("workout_sync_id", payload.getString("workout_sync_id"));
                values.put("exercise_sync_id", payload.getString("exercise_sync_id"));
                values.put("set_number", payload.getInt("set_number"));
                values.put("weight_kg", payload.getDouble("weight_kg"));
                // F159 根因修正：reps 對時間型組是 null，getInt 對 JSONObject.NULL 一律拋
                // JSONException，且整批 pull 因此回滾（見 applyPullPage 的共用 transaction）。
                // rpe／rest_seconds 一直是用這個 null-safe 寫法，reps／duration_seconds 補齊同待遇。
                putJsonNullableInteger(values, payload, "reps");
                putJsonNullableInteger(values, payload, "duration_seconds");
                putJsonNullableInteger(values, payload, "rpe");
                putJsonNullableInteger(values, payload, "rest_seconds");
                break;
            case "body_metric":
                values.put("date", payload.getString("date"));
                values.put("weight_kg", payload.getDouble("weight_kg"));
                if (payload.isNull("body_fat_pct")) values.putNull("body_fat_pct");
                else values.put("body_fat_pct", payload.getDouble("body_fat_pct"));
                break;
            case "daily_status":
                values.put("date", payload.getString("date"));
                values.put("energy", payload.getInt("energy"));
                putJsonNullableInteger(values, payload, "sleep_quality");
                putJsonNullable(values, payload, "note");
                break;
            case "setting":
                values.put("key", payload.getString("key"));
                values.put("value", payload.getString("value"));
                break;
            default:
                throw new IllegalArgumentException("不支援的 sync entity: " + entityType);
        }
        upsertRemote(db, entityType, table, values);
        if (entityType.equals("template")) {
            db.delete("template_exercises", "template_sync_id = ?", new String[]{entityId});
            JSONArray exercises = payload.getJSONArray("exercises");
            for (int index = 0; index < exercises.length(); index++) {
                JSONObject item = exercises.getJSONObject(index);
                ContentValues child = new ContentValues();
                child.put("sync_id", UUID.nameUUIDFromBytes(
                    ("liftlog:template-exercise:" + entityId + ":" + item.getInt("position"))
                        .getBytes(StandardCharsets.UTF_8)
                ).toString());
                child.put("template_sync_id", entityId);
                child.put("exercise_sync_id", item.getString("exercise_sync_id"));
                child.put("position", item.getInt("position"));
                child.put("default_sets", item.getInt("default_sets"));
                putJsonNullableInteger(child, item, "rest_hint_seconds");
                db.insertOrThrow("template_exercises", null, child);
            }
        }
    }

    private static void upsertRemote(
        SQLiteDatabase db, String entityType, String table, ContentValues values
    ) {
        String syncId = values.getAsString("sync_id");
        int changed = db.update(table, values, "sync_id = ?", new String[]{syncId});
        String naturalKey = naturalKeyColumn(entityType);
        if (changed == 0 && naturalKey != null) {
            changed = db.update(
                table,
                values,
                naturalKey + " = ? AND deleted_at IS NULL",
                new String[]{values.getAsString(naturalKey)}
            );
        }
        if (changed == 0) db.insertOrThrow(table, null, values);
    }

    private static String naturalKeyColumn(String entityType) {
        switch (entityType) {
            case "body_metric":
            case "daily_status":
                return "date";
            case "setting":
                return "key";
            default:
                return null;
        }
    }

    private static void putJsonNullable(
        ContentValues values, JSONObject payload, String key
    ) throws JSONException {
        if (payload.isNull(key)) values.putNull(key); else values.put(key, payload.getString(key));
    }

    private static void putJsonNullableInteger(
        ContentValues values, JSONObject payload, String key
    ) throws JSONException {
        if (payload.isNull(key)) values.putNull(key); else values.put(key, payload.getInt(key));
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

    protected void migrateVersion3(SQLiteDatabase db) {
        long localRows = 0;
        String[] tables = {
            "exercises", "templates", "workouts", "sets", "body_metrics",
            "daily_status", "app_settings", "sync_outbox"
        };
        for (String table : tables) {
            try (Cursor cursor = db.rawQuery("SELECT COUNT(*) FROM " + table, null)) {
                cursor.moveToFirst();
                localRows += cursor.getLong(0);
            }
        }
        putSyncState(db, "bootstrap_complete", localRows > 0 ? "1" : "0");
        db.execSQL("INSERT OR IGNORE INTO sync_state(key, value) VALUES('next_sync_at', '0')");
        db.execSQL("INSERT OR IGNORE INTO sync_state(key, value) VALUES('last_error_code', '')");
        db.execSQL("INSERT OR IGNORE INTO sync_state(key, value) VALUES('sync_attempt_count', '0')");
        enqueueExistingDomainRows(db);
    }

    /**
     * F159：解除時間型動作的 APK 封鎖——`exercises` 補 `mode`，`sets` 補 `duration_seconds`
     * 並放寬 `reps` 的 NOT NULL（SQLite 沒有 ALTER COLUMN，只能整表重建）。
     * 兩步都是冪等的：欄位／約束已經是目標狀態就整段跳過，可安全重跑。
     */
    protected void migrateVersion4(SQLiteDatabase db) {
        if (!hasColumn(db, "exercises", "mode")) {
            db.execSQL(
                "ALTER TABLE exercises ADD COLUMN mode TEXT NOT NULL DEFAULT '"
                    + EXERCISE_MODE_REPS + "'"
            );
        }
        rebuildSetsForNullableReps(db);
    }

    private static boolean hasColumn(SQLiteDatabase db, String table, String column) {
        try (Cursor cursor = db.rawQuery("PRAGMA table_info(" + table + ")", null)) {
            int nameIndex = cursor.getColumnIndexOrThrow("name");
            while (cursor.moveToNext()) {
                if (column.equals(cursor.getString(nameIndex))) return true;
            }
        }
        return false;
    }

    private static boolean setsRepsIsNotNull(SQLiteDatabase db) {
        try (Cursor cursor = db.rawQuery("PRAGMA table_info(sets)", null)) {
            int nameIndex = cursor.getColumnIndexOrThrow("name");
            int notNullIndex = cursor.getColumnIndexOrThrow("notnull");
            while (cursor.moveToNext()) {
                if ("reps".equals(cursor.getString(nameIndex))) {
                    return cursor.getInt(notNullIndex) != 0;
                }
            }
        }
        return false;
    }

    /** 重建前後的複製保真度指紋：筆數、相異外鍵數與加總都要對得上，比對筆數不夠——
     *  欄位順序寫錯時筆數一樣正確，值卻整欄錯位。weight_kg 換成分（避免浮點數比較誤差）；
     *  rpe/rest_seconds/version 比照 reps/set_number 用加總，updated_at/deleted_at/created_at
     *  這三個文字時間戳用相異值數量（SQLite 沒有現成雜湊可比對值本身）。duration_seconds
     *  不用比——重建當下一律填 NULL，前後恆等，沒有鑑別力。package-private 供測試直接呼叫。 */
    static long[] setsFingerprint(SQLiteDatabase db) {
        try (Cursor cursor = db.rawQuery(
            "SELECT COUNT(*), COUNT(DISTINCT client_uuid), COUNT(DISTINCT workout_sync_id), "
                + "COUNT(DISTINCT exercise_sync_id), COALESCE(SUM(reps), -1), "
                + "COALESCE(SUM(set_number), -1), "
                + "CAST(ROUND(COALESCE(SUM(weight_kg), -1) * 100) AS INTEGER), "
                + "COALESCE(SUM(rpe), -1), COALESCE(SUM(rest_seconds), -1), "
                + "COALESCE(SUM(version), -1), COUNT(DISTINCT updated_at), "
                + "COUNT(DISTINCT deleted_at), COUNT(DISTINCT created_at) FROM sets",
            null
        )) {
            cursor.moveToFirst();
            long[] fingerprint = new long[cursor.getColumnCount()];
            for (int index = 0; index < fingerprint.length; index++) {
                fingerprint[index] = cursor.getLong(index);
            }
            return fingerprint;
        }
    }

    /**
     * 把既有 DB 的 `sets.reps` 從 NOT NULL 改成 nullable，`duration_seconds` 一併補上。
     * 已經是 nullable 就整段跳過（冪等）。
     *
     * <p>不像 server 端（app/migrations.py::_rebuild_sets_for_nullable_reps）另外關 `PRAGMA
     * foreign_keys`：SQLiteOpenHelper 的 onCreate/onUpgrade 本來就整個包在一個 transaction
     * 裡呼叫，PRAGMA foreign_keys 在交易內是無效指令；但這裡也不需要它——`sets` 只有指出去的
     * FK（→ workouts／exercises），沒有其他表以 FK 指向 `sets`，drop 掉它不會留下懸空參照。
     */
    private static void rebuildSetsForNullableReps(SQLiteDatabase db) {
        // P3-3：冪等判斷要看欄位存在性，不是 reps 的 NOT NULL 狀態——後者只是重建的其中一個
        // 結果，日後若再放寬其他欄位的 NOT NULL，用它判斷會誤判「已經重建過」而漏跑。
        if (hasColumn(db, "sets", "duration_seconds")) return;
        long[] fingerprintBefore = setsFingerprint(db);
        db.execSQL("CREATE TABLE sets_f159_new ("
            + "sync_id TEXT PRIMARY KEY NOT NULL, client_uuid TEXT NOT NULL UNIQUE,"
            + "workout_sync_id TEXT NOT NULL, exercise_sync_id TEXT NOT NULL,"
            + "set_number INTEGER NOT NULL CHECK(set_number > 0),"
            + "weight_kg REAL NOT NULL CHECK(weight_kg >= 0),"
            + "reps INTEGER CHECK(reps IS NULL OR reps > 0),"
            + "duration_seconds INTEGER CHECK(duration_seconds IS NULL OR duration_seconds > 0),"
            + "rpe INTEGER CHECK(rpe IS NULL OR rpe BETWEEN 1 AND 10),"
            + "rest_seconds INTEGER CHECK(rest_seconds IS NULL OR rest_seconds >= 0),"
            + syncColumns() + ","
            // P3-1：reps 與 duration_seconds 擇一且僅擇一——擋「兩者都給／都沒給」，
            // 擋不到「秒數寫進 reps 欄」這種型別正確但語意錯的值（那要靠 service 層/外掛驗證）。
            // 表級 CHECK 必須排在所有欄位定義之後，不能插在欄位之間（SQLite 語法要求）。
            + "CHECK((reps IS NULL) <> (duration_seconds IS NULL)),"
            + "FOREIGN KEY(workout_sync_id) REFERENCES workouts(sync_id),"
            + "FOREIGN KEY(exercise_sync_id) REFERENCES exercises(sync_id))");
        db.execSQL(
            "INSERT INTO sets_f159_new (sync_id, client_uuid, workout_sync_id, exercise_sync_id,"
                + " set_number, weight_kg, reps, duration_seconds, rpe, rest_seconds, version,"
                + " updated_at, deleted_at, created_at)"
                + " SELECT sync_id, client_uuid, workout_sync_id, exercise_sync_id, set_number,"
                + " weight_kg, reps, NULL, rpe, rest_seconds, version, updated_at, deleted_at,"
                + " created_at FROM sets"
        );
        db.execSQL("DROP TABLE sets");
        db.execSQL("ALTER TABLE sets_f159_new RENAME TO sets");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS ux_sets_number_active "
            + "ON sets(workout_sync_id, exercise_sync_id, set_number) WHERE deleted_at IS NULL");
        long[] fingerprintAfter = setsFingerprint(db);
        if (!Arrays.equals(fingerprintBefore, fingerprintAfter)) {
            throw new IllegalStateException(
                "F159 sets 重建前後資料不一致：" + Arrays.toString(fingerprintBefore)
                    + " -> " + Arrays.toString(fingerprintAfter)
            );
        }
        if (setsRepsIsNotNull(db)) {
            throw new IllegalStateException("F159 sets 重建後 reps 仍是 NOT NULL");
        }
    }

    private void enqueueExistingDomainRows(SQLiteDatabase db) {
        String[][] entities = {
            {"exercises", "exercise"},
            {"templates", "template"},
            {"workouts", "workout"},
            {"sets", "set"},
            {"body_metrics", "body_metric"},
            {"daily_status", "daily_status"},
            {"app_settings", "setting"}
        };
        for (String[] entity : entities) {
            enqueueExistingRows(db, entity[0], entity[1]);
        }
    }

    private void enqueueExistingRows(SQLiteDatabase db, String table, String entityType) {
        try (Cursor cursor = db.query(
            table,
            new String[]{"sync_id", "version", "deleted_at"},
            null,
            null,
            null,
            null,
            "rowid ASC"
        )) {
            while (cursor.moveToNext()) {
                String syncId = cursor.getString(0);
                if (hasAnyOutboxMutation(db, entityType, syncId)) continue;
                String operation = cursor.isNull(2) ? "upsert" : "delete";
                insertOutbox(
                    db,
                    migrationMutationId(entityType, syncId),
                    entityType,
                    syncId,
                    operation,
                    cursor.getInt(1),
                    "workout".equals(entityType) ? workoutLeaseGenerationBySyncId(db, syncId) : null,
                    payloadForEntity(db, entityType, syncId)
                );
            }
        }
    }

    private static boolean hasAnyOutboxMutation(
        SQLiteDatabase db, String entityType, String syncId
    ) {
        try (Cursor cursor = db.rawQuery(
            "SELECT EXISTS(SELECT 1 FROM sync_outbox WHERE entity_type = ? AND entity_id = ?)",
            new String[]{entityType, syncId}
        )) {
            cursor.moveToFirst();
            return cursor.getInt(0) == 1;
        }
    }

    private JSONObject payloadForEntity(SQLiteDatabase db, String entityType, String syncId) {
        switch (entityType) {
            case "exercise": return exercisePayload(db, syncId);
            case "template": return templatePayload(db, syncId);
            case "workout": return workoutPayload(db, syncId);
            case "set": return setPayload(db, syncId);
            case "body_metric": return bodyMetricPayload(db, syncId);
            case "daily_status": return dailyStatusPayload(db, syncId);
            case "setting": return settingPayload(db, syncId);
            default: throw new IllegalArgumentException("不支援的 migration entity: " + entityType);
        }
    }

    private static String migrationMutationId(String entityType, String syncId) {
        return UUID.nameUUIDFromBytes(
            ("liftlog:migration:v3:" + entityType + ":" + syncId)
                .getBytes(StandardCharsets.UTF_8)
        ).toString();
    }

    private int workoutLeaseGenerationBySyncId(SQLiteDatabase db, String syncId) {
        try (Cursor cursor = db.query(
            "workouts", new String[]{"lease_generation"}, "sync_id = ?",
            new String[]{syncId}, null, null, null
        )) {
            if (cursor.moveToFirst()) return cursor.getInt(0);
        }
        throw new IllegalStateException("找不到訓練");
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

    private static String seedMutationId(String nameEn) {
        return UUID.nameUUIDFromBytes(
            ("liftlog:seed-mutation:" + nameEn).getBytes(StandardCharsets.UTF_8)
        ).toString();
    }

    private static void markMutationFailed(
        SQLiteDatabase db, String mutationId, String errorCode
    ) {
        ContentValues failed = new ContentValues();
        failed.put("error_code", emptyTo(errorCode, "sync_failed"));
        failed.putNull("next_attempt_at");
        db.update(
            "sync_outbox", failed,
            "mutation_id = ? AND acked_at IS NULL", new String[]{mutationId}
        );
    }

    static final class BatchTooLarge extends IllegalStateException {
        final String mutationId;

        BatchTooLarge(String mutationId) {
            super("單筆 mutation 超過 sync 上限");
            this.mutationId = mutationId;
        }
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
