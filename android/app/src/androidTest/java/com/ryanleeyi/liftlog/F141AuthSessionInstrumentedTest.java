package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import android.content.Context;

import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.After;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.File;
import java.util.Scanner;

@RunWith(AndroidJUnit4.class)
public class F141AuthSessionInstrumentedTest {
    private final Context context = ApplicationProvider.getApplicationContext();

    @After
    public void cleanUp() {
        SecureStore.clearAuthSession(context);
    }

    @Test
    public void rotatingSessionIsEncryptedAndClearKeepsDeviceIdentity() throws Exception {
        String deviceId = SecureStore.deviceId(context);
        assertTrue(SecureStore.saveAuthSession(
            context, "access-secret", "refresh-secret", 123456789L));

        assertEquals("access-secret", SecureStore.accessToken(context));
        assertEquals("refresh-secret", SecureStore.refreshToken(context));
        assertEquals(123456789L, SecureStore.accessExpiresAt(context));

        File prefs = new File(context.getApplicationInfo().dataDir,
            "shared_prefs/liftlog_secure.xml");
        String raw;
        try (Scanner scanner = new Scanner(prefs, "UTF-8").useDelimiter("\\A")) {
            raw = scanner.hasNext() ? scanner.next() : "";
        }
        assertFalse(raw.contains("access-secret"));
        assertFalse(raw.contains("refresh-secret"));

        SecureStore.clearAuthSession(context);
        assertNull(SecureStore.accessToken(context));
        assertNull(SecureStore.refreshToken(context));
        assertEquals(deviceId, SecureStore.deviceId(context));
    }
}
