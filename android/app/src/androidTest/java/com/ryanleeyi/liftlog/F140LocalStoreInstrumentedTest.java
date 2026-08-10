package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Context;
import android.content.Intent;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.provider.Settings;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.webkit.WebView;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.json.JSONObject;
import org.json.JSONTokener;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.FileInputStream;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

@RunWith(AndroidJUnit4.class)
public class F140LocalStoreInstrumentedTest {
    private static final String OVERLAY_PREFS = "liftlog.overlay";
    private static final String OVERLAY_EXPANDED = "expanded";
    private static final long TIMEOUT_MS = 10_000;
    private static final long POLL_MS = 100;

    private Instrumentation instrumentation;
    private Context context;
    private MainActivity activity;

    @Before
    public void cleanBeforeTest() throws Exception {
        instrumentation = InstrumentationRegistry.getInstrumentation();
        context = instrumentation.getTargetContext();
        cleanTargetState();
    }

    @After
    public void cleanAfterTest() throws Exception {
        if (context == null) return;
        cleanTargetState();
        runShell("appops set " + context.getPackageName() + " android:system_alert_window default");
    }

    @Test
    public void overlayAndWebViewSharePersistentSQLite() throws Exception {
        String databaseName = "f140-" + UUID.randomUUID() + ".db";
        LocalStore webViewStore = new LocalStore(context, databaseName);
        LocalStore overlayStore = new LocalStore(context, databaseName);
        try {
            webViewStore.ensureReady();
            webViewStore.seedExercises();
            int exerciseId = webViewStore.snapshot().getJSONArray("exercises")
                .getJSONObject(0).getInt("id");
            String workoutSyncId = uuid();
            webViewStore.createWorkout(
                workoutSyncId, "2026-08-10", null, null, null, uuid()
            );
            int workoutId = webViewStore.workout(workoutSyncId).getInt("id");

            overlayStore.addSet(
                uuid(), uuid(), workoutId, exerciseId, null,
                42.5, 8, null, 90, 1, uuid()
            );
            assertEquals(1, webViewStore.snapshot().getJSONArray("sets").length());

            webViewStore.close();
            overlayStore.close();
            webViewStore = new LocalStore(context, databaseName);
            JSONObject reopened = webViewStore.snapshot();
            assertEquals(1, reopened.getJSONArray("workouts").length());
            assertEquals(1, reopened.getJSONArray("sets").length());
            assertEquals(2, webViewStore.pendingMutationCount());
        } finally {
            webViewStore.close();
            overlayStore.close();
            context.deleteDatabase(databaseName);
        }
    }

    @Test
    public void visibleOverlayButtonWritesSetAndWebViewPluginReadsIt() throws Exception {
        context.getSharedPreferences(OVERLAY_PREFS, Context.MODE_PRIVATE)
            .edit().putBoolean(OVERLAY_EXPANDED, true).commit();
        runShell("appops set " + context.getPackageName() + " android:system_alert_window allow");
        waitForOverlayPermission();

        activity = (MainActivity) instrumentation.startActivitySync(mainActivityIntent());
        WebView webView = waitForWebView(activity);
        JSONObject seeded = waitForPlugin(webView);
        int exerciseId = seeded.getInt("exerciseId");

        JSONObject workout = callPlugin(webView, "async () => {"
            + " const store = window.Capacitor.Plugins.LocalStore;"
            + " return store.createWorkout({syncId:'" + uuid() + "', date:'2026-08-10',"
            + " mutationId:'" + uuid() + "'});"
            + "}");
        int workoutId = workout.getInt("id");

        JSONObject started = callPlugin(webView, "async () => {"
            + " const timer = window.Capacitor.Plugins.RestTimer;"
            + " await timer.start({seconds:60, overlay:true, weight:42.5, reps:8,"
            + " exerciseId:" + exerciseId + ", setNumber:1, workoutId:" + workoutId + "});"
            + " return {started:true};"
            + "}");
        assertTrue(started.getBoolean("started"));

        UiAutomation automation = interactiveUiAutomation();
        assertTrue("必須能將 app 切到背景以顯示 overlay",
            automation.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME));
        clickVisibleOverlayNode(automation, "停止");
        clickVisibleOverlayNode(automation, "完成這組");

        context.startActivity(mainActivityIntent());
        webView = waitForWebView(activity);
        JSONObject persisted = waitForOverlaySet(webView);
        JSONObject set = persisted.getJSONArray("sets").getJSONObject(0);
        assertEquals(42.5, set.getDouble("weight_kg"), 0.001);
        assertEquals(8, set.getInt("reps"));
        assertEquals(2, persisted.getInt("pendingMutations"));
    }

    private Intent mainActivityIntent() {
        return new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    }

    private WebView waitForWebView(MainActivity target) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
        while (SystemClock.elapsedRealtime() < deadline) {
            AtomicReference<WebView> result = new AtomicReference<>();
            instrumentation.runOnMainSync(() -> {
                if (target.getBridge() != null) result.set(target.getBridge().getWebView());
            });
            if (result.get() != null) return result.get();
            SystemClock.sleep(POLL_MS);
        }
        throw new AssertionError("MainActivity 的 WebView 未在期限內建立");
    }

    private JSONObject waitForPlugin(WebView webView) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
        JSONObject last = null;
        while (SystemClock.elapsedRealtime() < deadline) {
            last = callPlugin(webView, "async () => {"
                + " const store = window.Capacitor?.Plugins?.LocalStore;"
                + " if (!store) return {ready:false};"
                + " await store.initialize();"
                + " const snapshot = await store.snapshot();"
                + " return {ready:true, exerciseId:snapshot.exercises[0]?.id};"
                + "}");
            if (last.optBoolean("ready") && last.optInt("exerciseId") > 0) return last;
            SystemClock.sleep(POLL_MS);
        }
        throw new AssertionError("Capacitor LocalStore plugin 未就緒：" + last);
    }

    private JSONObject waitForOverlaySet(WebView webView) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
        JSONObject last = null;
        while (SystemClock.elapsedRealtime() < deadline) {
            last = callPlugin(webView, "async () => {"
                + " const store = window.Capacitor.Plugins.LocalStore;"
                + " const snapshot = await store.snapshot();"
                + " const status = await store.status();"
                + " return {sets:snapshot.sets, pendingMutations:status.pendingMutations};"
                + "}");
            if (last.getJSONArray("sets").length() == 1) return last;
            SystemClock.sleep(POLL_MS);
        }
        throw new AssertionError("overlay 點擊後 LocalStore 未出現 set：" + last);
    }

    private JSONObject callPlugin(WebView webView, String asyncFunction) throws Exception {
        String key = uuid();
        evaluateJson(webView, "(() => {"
            + " window.__f140Results = window.__f140Results || {};"
            + " (async () => { try {"
            + " const value = await (" + asyncFunction + ")();"
            + " window.__f140Results['" + key + "'] = {done:true, value:value};"
            + " } catch (error) {"
            + " window.__f140Results['" + key + "'] = {done:true, error:String(error)};"
            + " } })();"
            + " return JSON.stringify({started:true});"
            + "})()");

        long deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
        JSONObject result = null;
        while (SystemClock.elapsedRealtime() < deadline) {
            result = evaluateJson(webView, "JSON.stringify(window.__f140Results['" + key
                + "'] || {done:false})");
            if (result.optBoolean("done")) {
                if (result.has("error")) throw new AssertionError(result.getString("error"));
                return result.getJSONObject("value");
            }
            SystemClock.sleep(POLL_MS);
        }
        throw new AssertionError("WebView Capacitor plugin 呼叫逾時：" + result);
    }

    private JSONObject evaluateJson(WebView webView, String script) throws Exception {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<String> rawResult = new AtomicReference<>();
        instrumentation.runOnMainSync(() -> webView.evaluateJavascript(script, value -> {
            rawResult.set(value);
            latch.countDown();
        }));
        assertTrue("WebView evaluateJavascript 逾時", latch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS));
        Object value = new JSONTokener(rawResult.get()).nextValue();
        if (!(value instanceof String)) throw new AssertionError("WebView 回傳不是 JSON 字串：" + value);
        return new JSONObject((String) value);
    }

    private void clickVisibleOverlayNode(UiAutomation automation, String text) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
        while (SystemClock.elapsedRealtime() < deadline) {
            AccessibilityNodeInfo node = findClickableNode(automation.getWindows(), text);
            if (node != null) {
                try {
                    assertTrue("overlay node 必須對使用者可見：" + text, node.isVisibleToUser());
                    assertTrue("overlay node 必須可點擊：" + text, node.isClickable());
                    assertTrue("overlay node 點擊失敗：" + text,
                        node.performAction(AccessibilityNodeInfo.ACTION_CLICK));
                    return;
                } finally {
                    node.recycle();
                }
            }
            SystemClock.sleep(POLL_MS);
        }
        throw new AssertionError("找不到可點擊的 overlay node：" + text
            + "；windows=" + describeWindows(automation.getWindows()));
    }

    private UiAutomation interactiveUiAutomation() {
        UiAutomation automation = instrumentation.getUiAutomation();
        AccessibilityServiceInfo serviceInfo = automation.getServiceInfo();
        assertNotNull("UiAutomation service info 不可為空", serviceInfo);
        serviceInfo.flags |= AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
        automation.setServiceInfo(serviceInfo);
        return automation;
    }

    private AccessibilityNodeInfo findClickableNode(List<AccessibilityWindowInfo> windows, String text) {
        for (AccessibilityWindowInfo window : windows) {
            AccessibilityNodeInfo node = findClickableNode(window.getRoot(), text);
            if (node != null) return node;
        }
        return null;
    }

    private AccessibilityNodeInfo findClickableNode(AccessibilityNodeInfo node, String text) {
        if (node == null) return null;
        CharSequence nodeText = node.getText();
        if (nodeText != null && text.contentEquals(nodeText) && node.isClickable()) return node;
        for (int index = 0; index < node.getChildCount(); index++) {
            AccessibilityNodeInfo found = findClickableNode(node.getChild(index), text);
            if (found != null) return found;
        }
        return null;
    }

    private String describeWindows(List<AccessibilityWindowInfo> windows) {
        StringBuilder description = new StringBuilder();
        for (AccessibilityWindowInfo window : windows) {
            AccessibilityNodeInfo root = window.getRoot();
            description.append("{type=").append(window.getType()).append(", text=");
            appendVisibleText(description, root);
            description.append('}');
        }
        return description.toString();
    }

    private void appendVisibleText(StringBuilder description, AccessibilityNodeInfo node) {
        if (node == null) return;
        if (node.getText() != null && node.isVisibleToUser()) {
            description.append(node.getText()).append('|');
        }
        for (int index = 0; index < node.getChildCount(); index++) {
            appendVisibleText(description, node.getChild(index));
        }
    }

    private void cleanTargetState() throws Exception {
        if (activity != null) {
            instrumentation.runOnMainSync(activity::finish);
            activity = null;
        }
        instrumentation.runOnMainSync(() -> RestOverlay.hide(context));
        context.stopService(new Intent(context, RestTimerService.class));
        instrumentation.waitForIdleSync();
        LocalStore.getInstance(context).close();
        context.deleteDatabase(LocalStore.DATABASE_NAME);
        context.getSharedPreferences(OVERLAY_PREFS, Context.MODE_PRIVATE).edit().clear().commit();
    }

    private void waitForOverlayPermission() {
        long deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
        while (SystemClock.elapsedRealtime() < deadline) {
            if (Settings.canDrawOverlays(context)) return;
            SystemClock.sleep(POLL_MS);
        }
        throw new AssertionError("測試 emulator 必須允許 overlay");
    }

    private void runShell(String command) throws Exception {
        try (ParcelFileDescriptor descriptor = instrumentation.getUiAutomation().executeShellCommand(command);
             FileInputStream output = new FileInputStream(descriptor.getFileDescriptor())) {
            while (output.read() != -1) {
                // 讀到 EOF 才代表 shell command 已結束。
            }
        }
    }

    private static String uuid() {
        return UUID.randomUUID().toString();
    }
}
