package com.ryanleeyi.liftlog;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

/** Android 的唯一 domain store；所有本地 mutation 與 outbox 必須在同一個 transaction。 */
public class LocalStore extends SQLiteOpenHelper {
    static final String DATABASE_NAME = "liftlog-local.db";
    static final int DATABASE_VERSION = 2;

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
        String templateSyncId,
        String note,
        String ownerDeviceId,
        String mutationId
    ) {
        JSONObject payload = jsonObject();
        put(payload, "sync_id", syncId);
        put(payload, "date", date);
        put(payload, "template_sync_id", templateSyncId);
        put(payload, "note", note);
        put(payload, "owner_device_id", ownerDeviceId);
        put(payload, "lease_generation", 1);

        transaction(db -> {
            ContentValues workout = new ContentValues();
            workout.put("sync_id", syncId);
            workout.put("date", date);
            putNullable(workout, "template_sync_id", templateSyncId);
            putNullable(workout, "note", note);
            putNullable(workout, "owner_device_id", ownerDeviceId);
            workout.put("lease_generation", 1);
            db.insertOrThrow("workouts", null, workout);
            insertOutbox(db, mutationId, "workout", syncId, "upsert", 0, 1, payload);
            return null;
        });
    }

    /** 建立 set 與 mutation receipt；供 F140 的 WebView 與 overlay 共用。 */
    public void addSet(
        String syncId,
        String clientUuid,
        String workoutSyncId,
        String exerciseSyncId,
        int setNumber,
        double weightKg,
        int reps,
        Integer rpe,
        Integer restSeconds,
        int leaseGeneration,
        String mutationId
    ) {
        JSONObject payload = jsonObject();
        put(payload, "sync_id", syncId);
        put(payload, "client_uuid", clientUuid);
        put(payload, "workout_sync_id", workoutSyncId);
        put(payload, "exercise_sync_id", exerciseSyncId);
        put(payload, "set_number", setNumber);
        put(payload, "weight_kg", weightKg);
        put(payload, "reps", reps);
        put(payload, "rpe", rpe);
        put(payload, "rest_seconds", restSeconds);

        transaction(db -> {
            ContentValues set = new ContentValues();
            set.put("sync_id", syncId);
            set.put("client_uuid", clientUuid);
            set.put("workout_sync_id", workoutSyncId);
            set.put("exercise_sync_id", exerciseSyncId);
            set.put("set_number", setNumber);
            set.put("weight_kg", weightKg);
            set.put("reps", reps);
            putNullable(set, "rpe", rpe);
            putNullable(set, "rest_seconds", restSeconds);
            db.insertOrThrow("sets", null, set);
            insertOutbox(
                db, mutationId, "set", syncId, "upsert", 0, leaseGeneration, payload
            );
            return null;
        });
    }

    public int pendingMutationCount() {
        return count("sync_outbox", "acked_at IS NULL", null);
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
}
