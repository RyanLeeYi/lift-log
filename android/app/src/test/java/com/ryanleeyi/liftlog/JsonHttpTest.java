package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

import org.junit.Test;

import java.io.IOException;

public class JsonHttpTest {
    @Test
    public void onlyHttpsOrExplicitLocalHttpMayCarryBearerTokens() throws Exception {
        assertEquals(
            "https://sync.example.com/api/sync/pull",
            JsonHttp.safeUrl("https://sync.example.com", "/api/sync/pull").toString()
        );
        assertRejected("http://sync.example.com");
        assertRejected("https://user:secret@sync.example.com");
        assertRejected("https://sync.example.com/unexpected-base-path");
    }

    private static void assertRejected(String baseUrl) throws Exception {
        try {
            JsonHttp.safeUrl(baseUrl, "/api/sync/pull");
            fail("不安全的 sync URL 必須被拒絕");
        } catch (IOException expected) {
            assertEquals("sync base URL 不安全", expected.getMessage());
        }
    }
}
