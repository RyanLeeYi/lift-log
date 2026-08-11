package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 36)
public class SyncContractFixtureTest {
    private static final String[] REQUEST_FIXTURES = {
        "push_exercise.json",
        "push_template.json",
        "push_workout.json",
        "push_set.json",
        "push_body_metric.json",
        "push_daily_status.json",
        "push_setting.json",
    };

    @Test
    public void requestFixturesKeepSchemaAndMutationContract() throws Exception {
        for (String fixtureName : REQUEST_FIXTURES) {
            JSONObject request = fixture(fixtureName);
            assertEquals(1, request.getInt("schema_version"));
            assertUuid(request.getString("device_id"));

            JSONArray mutations = request.getJSONArray("mutations");
            assertEquals(1, mutations.length());
            assertMutation(mutations.getJSONObject(0));
        }
    }

    @Test
    public void responseFixturesKeepReceiptConflictAndCursorContract() throws Exception {
        JSONObject accepted = fixture("response_push_accepted.json");
        assertEquals(1, accepted.getJSONArray("accepted").length());
        assertEquals(0, accepted.getJSONArray("conflicts").length());
        JSONObject receipt = accepted.getJSONArray("accepted").getJSONObject(0);
        assertUuid(receipt.getString("mutation_id"));
        assertTrue(receipt.getInt("version") > 0);
        assertTrue(receipt.getInt("server_seq") > 0);

        JSONObject conflict = fixture("response_push_conflict.json");
        assertEquals(0, conflict.getJSONArray("accepted").length());
        assertEquals(1, conflict.getJSONArray("conflicts").length());
        JSONObject server = conflict.getJSONArray("conflicts").getJSONObject(0).getJSONObject("server");
        assertUuid(server.getString("entity_id"));
        assertTrue(server.getString("updated_at").endsWith("Z"));
        assertEquals(server.getString("entity_id"), server.getJSONObject("payload").getString("sync_id"));

        JSONObject pull = fixture("response_pull_paginated.json");
        JSONArray changes = pull.getJSONArray("changes");
        assertTrue(changes.length() > 0);
        int previousSequence = 0;
        for (int index = 0; index < changes.length(); index++) {
            JSONObject change = changes.getJSONObject(index);
            int sequence = change.getInt("server_seq");
            assertTrue(sequence > previousSequence);
            assertEquals(1, change.getInt("schema_version"));
            assertUuid(change.getString("entity_id"));
            assertEquals(change.getString("entity_id"), change.getJSONObject("payload").getString("sync_id"));
            assertTrue(change.getString("updated_at").endsWith("Z"));
            previousSequence = sequence;
        }
        assertEquals(previousSequence, pull.getInt("next_cursor"));
        assertTrue(pull.getBoolean("has_more"));
    }

    private static JSONObject fixture(String fixtureName) throws IOException, JSONException {
        InputStream input = SyncContractFixtureTest.class.getClassLoader()
            .getResourceAsStream(fixtureName);
        assertNotNull("fixture must be on the test classpath: " + fixtureName, input);
        try (InputStream stream = input) {
            return new JSONObject(new String(stream.readAllBytes(), StandardCharsets.UTF_8));
        }
    }

    private static void assertMutation(JSONObject mutation) throws JSONException {
        String[] requiredFields = {
            "mutation_id", "entity_type", "entity_id", "operation", "base_version", "payload",
        };
        for (String field : requiredFields) {
            assertTrue("missing mutation field: " + field, mutation.has(field));
        }
        assertUuid(mutation.getString("mutation_id"));
        assertUuid(mutation.getString("entity_id"));
        assertFalse(mutation.getString("entity_type").isEmpty());
        assertFalse(mutation.getString("operation").isEmpty());
        assertTrue(mutation.getInt("base_version") >= 0);
        assertEquals(mutation.getString("entity_id"), mutation.getJSONObject("payload").getString("sync_id"));
    }

    private static void assertUuid(String value) {
        UUID.fromString(value);
    }
}
