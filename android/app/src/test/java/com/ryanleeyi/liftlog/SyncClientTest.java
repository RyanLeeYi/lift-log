package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import android.content.Context;

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

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 36)
public class SyncClientTest {
    private Context context;
    private String databaseName;
    private LocalStore store;

    @Before
    public void setUp() {
        context = RuntimeEnvironment.getApplication();
        databaseName = "sync-client-test-" + UUID.randomUUID() + ".db";
        store = new LocalStore(context, databaseName);
        store.ensureReady();
    }

    @After
    public void tearDown() {
        store.close();
        context.deleteDatabase(databaseName);
    }

    @Test
    public void lostPushResponseRetriesSameMutationThenPulls() throws Exception {
        String mutationId = uuid();
        String deviceId = uuid();
        store.saveBodyMetric(uuid(), "2026-08-11", 80, null, mutationId);
        RecordingTransport transport = new RecordingTransport(mutationId);
        SyncClient client = new SyncClient(store, deviceId, transport, () -> 0.0);

        SyncClient.Result first = client.syncOnce(0);
        assertEquals("offline", first.state);
        assertEquals(1, store.pendingMutationCount());

        SyncClient.Result second = client.syncOnce(5_000);
        assertEquals("synced", second.state);
        assertEquals(0, store.pendingMutationCount());
        assertEquals(List.of("push", "push", "pull"), transport.calls);
        assertEquals(mutationId, transport.mutationIds.get(0));
        assertEquals(mutationId, transport.mutationIds.get(1));
    }

    @Test
    public void exponentialBackoffHasJitterAndCapsAtFifteenMinutes() {
        assertEquals(5_000, SyncClient.retryDelayMillis(1, 0.0));
        assertTrue(SyncClient.retryDelayMillis(2, 0.5) > 10_000);
        assertEquals(900_000, SyncClient.retryDelayMillis(30, 1.0));
    }

    @Test
    public void oversizedMutationBecomesPermanentErrorWithoutCrashing() throws Exception {
        String mutationId = uuid();
        store.saveDailyStatus(
            uuid(), "2026-08-11", 3, null, "x".repeat(1024 * 1024), mutationId
        );
        SyncClient client = new SyncClient(
            store, uuid(), new RecordingTransport(mutationId), () -> 0.0
        );

        assertEquals("error", client.syncOnce(0).state);
        assertEquals(1, store.pendingMutationCount());
        assertEquals(0, store.syncStatus().getInt("pending"));
        assertEquals(1, store.syncStatus().getInt("failed"));
        assertEquals("payload_too_large", store.syncStatus().getString("errorCode"));
    }

    @Test
    public void incompletePushReceiptSchedulesRetryInsteadOfLooping() throws Exception {
        store.saveBodyMetric(uuid(), "2026-08-11", 80, null, uuid());
        SyncClient client = new SyncClient(store, uuid(), new SyncClient.Transport() {
            @Override
            public JSONObject push(JSONObject body) throws JSONException {
                return new JSONObject()
                    .put("accepted", new JSONArray())
                    .put("conflicts", new JSONArray());
            }

            @Override
            public JSONObject pull(long cursor) {
                throw new AssertionError("receipt 不完整時不得 pull");
            }
        }, () -> 0.0);

        assertEquals("error", client.syncOnce(0).state);
        assertEquals(5_000, store.nextSyncAt());
        assertEquals(1, store.pendingMutationCount());
    }

    @Test
    public void authFailureNeverPoisonsLocalMutations() throws Exception {
        store.saveBodyMetric(uuid(), "2026-08-11", 80, null, uuid());
        SyncClient client = new SyncClient(store, uuid(), new SyncClient.Transport() {
            @Override
            public JSONObject push(JSONObject body) throws IOException {
                throw new SyncClient.TransportFailure("auth_required", false);
            }

            @Override
            public JSONObject pull(long cursor) {
                throw new AssertionError("auth failure 時不得 pull");
            }
        }, () -> 0.0);

        assertEquals("error", client.syncOnce(0).state);
        assertEquals(1, store.syncStatus().getInt("pending"));
        assertEquals(0, store.syncStatus().getInt("failed"));
        assertEquals("error", store.syncStatus().getString("state"));
    }

    @Test
    public void pullOnlyFailuresPersistAndIncreaseBackoff() {
        SyncClient client = new SyncClient(store, uuid(), new SyncClient.Transport() {
            @Override
            public JSONObject push(JSONObject body) {
                throw new AssertionError("空 outbox 不得 push");
            }

            @Override
            public JSONObject pull(long cursor) throws IOException {
                throw new IOException("offline");
            }
        }, () -> 0.0);

        assertEquals("offline", client.syncOnce(0).state);
        assertEquals(5_000, store.nextSyncAt());
        assertEquals("offline", client.syncOnce(5_000).state);
        assertEquals(15_000, store.nextSyncAt());
    }

    @Test
    public void unexpectedPullRuntimeFailureStillPersistsVisibleRetry() throws Exception {
        String localExercise = uuid();
        store.createExercise(
            localExercise, "重複動作", "Duplicate", "測試", false, uuid()
        );
        store.applyPushResponse(new JSONObject()
            .put("accepted", new JSONArray().put(new JSONObject()
                .put("mutation_id", store.pendingPushBody(uuid(), 1, 1024 * 1024, 0)
                    .getJSONArray("mutations").getJSONObject(0).getString("mutation_id"))
                .put("version", 1)
                .put("server_seq", 1)))
            .put("conflicts", new JSONArray()), 0);
        String remoteExercise = uuid();
        SyncClient client = new SyncClient(store, uuid(), new SyncClient.Transport() {
            @Override
            public JSONObject push(JSONObject body) {
                throw new AssertionError("outbox 已清，不得 push");
            }

            @Override
            public JSONObject pull(long cursor) throws JSONException {
                return new JSONObject()
                    .put("changes", new JSONArray().put(new JSONObject()
                        .put("server_seq", 1)
                        .put("schema_version", 1)
                        .put("entity_type", "exercise")
                        .put("entity_id", remoteExercise)
                        .put("operation", "upsert")
                        .put("version", 1)
                        .put("updated_at", "2026-08-12T00:00:00Z")
                        .put("deleted_at", JSONObject.NULL)
                        .put("payload", new JSONObject()
                            .put("sync_id", remoteExercise)
                            .put("name_zh", "重複動作")
                            .put("name_en", "Duplicate")
                            .put("muscle_group", "測試")
                            .put("is_bodyweight", false))))
                    .put("next_cursor", 1)
                    .put("has_more", false);
            }
        }, () -> 0.0);

        assertEquals("error", client.syncOnce(0).state);
        assertEquals(0, store.serverCursor());
        assertEquals(5_000, store.nextSyncAt());
        assertEquals("error", store.syncStatus().getString("state"));
        assertEquals("sync_error", store.syncStatus().getString("errorCode"));
    }

    private static String uuid() {
        return UUID.randomUUID().toString();
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
