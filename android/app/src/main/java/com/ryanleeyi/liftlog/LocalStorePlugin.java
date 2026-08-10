package com.ryanleeyi.liftlog;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.text.ParsePosition;
import java.text.SimpleDateFormat;
import java.util.Locale;
import java.util.UUID;

/** WebView 只能呼叫具型別的 LocalStore 操作，不能送任意 SQL。 */
@CapacitorPlugin(name = "LocalStore")
public class LocalStorePlugin extends Plugin {
    @PluginMethod
    public void initialize(PluginCall call) {
        try {
            LocalStore store = store();
            int schemaVersion = store.ensureReady();
            int seeded = store.seedExercises();
            JSObject result = new JSObject();
            result.put("schemaVersion", schemaVersion);
            result.put("seededExercises", seeded);
            result.put("pendingMutations", store.pendingMutationCount());
            call.resolve(result);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void createWorkout(PluginCall call) {
        try {
            String syncId = requireUuid(call, "syncId");
            String mutationId = requireUuid(call, "mutationId");
            String date = requireDate(call);
            String templateSyncId = optionalUuid(call, "templateSyncId");
            String ownerDeviceId = optionalUuid(call, "ownerDeviceId");
            String note = call.getString("note");
            store().createWorkout(
                syncId, date, templateSyncId, note, ownerDeviceId, mutationId
            );
            call.resolve();
        } catch (IllegalArgumentException error) {
            call.reject(error.getMessage(), "INVALID_ARGUMENT", error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void addSet(PluginCall call) {
        try {
            String syncId = requireUuid(call, "syncId");
            String mutationId = requireUuid(call, "mutationId");
            String workoutSyncId = requireUuid(call, "workoutSyncId");
            String exerciseSyncId = requireUuid(call, "exerciseSyncId");
            String clientUuid = requireText(call, "clientUuid", 8);
            int setNumber = requirePositive(call, "setNumber");
            double weightKg = requireNonNegativeDouble(call, "weightKg");
            int reps = requirePositive(call, "reps");
            Integer rpe = optionalInt(call, "rpe");
            Integer restSeconds = optionalInt(call, "restSeconds");
            int leaseGeneration = requirePositive(call, "leaseGeneration");
            if (rpe != null && (rpe < 1 || rpe > 10)) {
                throw new IllegalArgumentException("rpe 必須介於 1 到 10");
            }
            if (restSeconds != null && restSeconds < 0) {
                throw new IllegalArgumentException("restSeconds 不得小於 0");
            }
            store().addSet(
                syncId,
                clientUuid,
                workoutSyncId,
                exerciseSyncId,
                setNumber,
                weightKg,
                reps,
                rpe,
                restSeconds,
                leaseGeneration,
                mutationId
            );
            call.resolve();
        } catch (IllegalArgumentException error) {
            call.reject(error.getMessage(), "INVALID_ARGUMENT", error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void status(PluginCall call) {
        try {
            JSObject result = new JSObject();
            result.put("schemaVersion", store().ensureReady());
            result.put("pendingMutations", store().pendingMutationCount());
            call.resolve(result);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    private LocalStore store() {
        return LocalStore.getInstance(getContext());
    }

    private static String requireUuid(PluginCall call, String key) {
        String value = requireText(call, key, 1);
        try {
            return UUID.fromString(value).toString();
        } catch (IllegalArgumentException error) {
            throw new IllegalArgumentException(key + " 必須是 UUID", error);
        }
    }

    private static String optionalUuid(PluginCall call, String key) {
        String value = call.getString(key);
        if (value == null || value.trim().isEmpty()) return null;
        try {
            return UUID.fromString(value).toString();
        } catch (IllegalArgumentException error) {
            throw new IllegalArgumentException(key + " 必須是 UUID", error);
        }
    }

    private static String requireText(PluginCall call, String key, int minLength) {
        String value = call.getString(key);
        if (value == null || value.trim().length() < minLength) {
            throw new IllegalArgumentException(key + " 缺少或太短");
        }
        return value.trim();
    }

    private static int requirePositive(PluginCall call, String key) {
        Integer value = call.getInt(key);
        if (value == null || value <= 0) {
            throw new IllegalArgumentException(key + " 必須大於 0");
        }
        return value;
    }

    private static double requireNonNegativeDouble(PluginCall call, String key) {
        Double value = call.getDouble(key);
        if (value == null || !Double.isFinite(value) || value < 0) {
            throw new IllegalArgumentException(key + " 必須是大於等於 0 的有限數字");
        }
        return value;
    }

    private static Integer optionalInt(PluginCall call, String key) {
        return call.getInt(key);
    }

    private static String requireDate(PluginCall call) {
        String value = requireText(call, "date", 10);
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT);
        format.setLenient(false);
        ParsePosition position = new ParsePosition(0);
        if (format.parse(value, position) == null || position.getIndex() != value.length()) {
            throw new IllegalArgumentException("date 必須是有效的 YYYY-MM-DD");
        }
        return value;
    }

    private static void rejectStore(PluginCall call, RuntimeException error) {
        call.reject("LocalStore 無法完成操作", "LOCAL_STORE_ERROR", error);
    }
}
