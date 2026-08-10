package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.fail;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

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
