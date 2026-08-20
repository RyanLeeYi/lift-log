package com.ryanleeyi.liftlog;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONException;
import org.json.JSONObject;

import java.text.ParsePosition;
import java.text.SimpleDateFormat;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
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

    /** 唯讀 domain snapshot；不接受 table、column 或 SQL 參數。 */
    @PluginMethod
    public void snapshot(PluginCall call) {
        try {
            call.resolve(asJsObject(store().snapshot()));
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void createExercise(PluginCall call) {
        try {
            JSONObject result = store().createExercise(
                requireUuid(call, "syncId"),
                requireText(call, "nameZh", 1, 120),
                optionalText(call, "nameEn", 120),
                optionalText(call, "muscleGroup", 60),
                Boolean.TRUE.equals(call.getBoolean("isBodyweight", false)),
                requireMode(call),
                requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(result));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void createWorkout(PluginCall call) {
        try {
            String syncId = requireUuid(call, "syncId");
            store().createWorkout(
                syncId,
                requireDate(call),
                optionalPositive(call, "templateId"),
                optionalText(call, "note", 2000),
                optionalUuid(call, "ownerDeviceId"),
                requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(store().workout(syncId)));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void saveTemplate(PluginCall call) {
        try {
            Integer id = optionalPositive(call, "id");
            JSONObject result = store().saveTemplate(
                id,
                id == null ? requireUuid(call, "syncId") : null,
                requireText(call, "name", 1, 120),
                requireTemplateExercises(call),
                requireWeekdays(call),
                requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(result));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void deleteTemplate(PluginCall call) {
        mutateVoid(call, () -> store().deleteTemplate(
            requirePositive(call, "id"), requireUuid(call, "mutationId")
        ));
    }

    @PluginMethod
    public void addSet(PluginCall call) {
        try {
            String syncId = requireUuid(call, "syncId");
            Integer reps = optionalInt(call, "reps");
            Integer durationSeconds = optionalInt(call, "durationSeconds");
            validateSetMode(reps, durationSeconds);
            Integer rpe = optionalInt(call, "rpe");
            Integer restSeconds = optionalInt(call, "restSeconds");
            validateSetOptionals(rpe, restSeconds);
            store().addSet(
                syncId,
                requireText(call, "clientUuid", 8, 200),
                requirePositive(call, "workoutId"),
                requirePositive(call, "exerciseId"),
                optionalPositive(call, "setNumber"),
                requireNonNegativeDouble(call, "weightKg"),
                reps,
                durationSeconds,
                rpe,
                restSeconds,
                requirePositive(call, "leaseGeneration"),
                requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(store().set(syncId)));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void updateSet(PluginCall call) {
        try {
            Integer reps = optionalInt(call, "reps");
            Integer durationSeconds = optionalInt(call, "durationSeconds");
            validateSetMode(reps, durationSeconds);
            Integer rpe = optionalInt(call, "rpe");
            Integer restSeconds = optionalInt(call, "restSeconds");
            validateSetOptionals(rpe, restSeconds);
            JSONObject result = store().updateSet(
                requirePositive(call, "id"),
                requireNonNegativeDouble(call, "weightKg"),
                reps,
                durationSeconds,
                rpe,
                restSeconds,
                requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(result));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void deleteSet(PluginCall call) {
        mutateVoid(call, () -> store().deleteSet(
            requirePositive(call, "id"), requireUuid(call, "mutationId")
        ));
    }

    @PluginMethod
    public void endWorkout(PluginCall call) {
        try {
            JSONObject result = store().endWorkout(
                requirePositive(call, "id"), requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(result));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void deleteWorkout(PluginCall call) {
        mutateVoid(call, () -> store().deleteWorkout(
            requirePositive(call, "id"), requireUuid(call, "mutationId")
        ));
    }

    @PluginMethod
    public void saveBodyMetric(PluginCall call) {
        try {
            Double fat = call.getDouble("bodyFatPct");
            if (fat != null && (!Double.isFinite(fat) || fat <= 0 || fat >= 100)) {
                throw new IllegalArgumentException("bodyFatPct 必須大於 0 且小於 100");
            }
            JSONObject result = store().saveBodyMetric(
                requireUuid(call, "syncId"),
                requireDate(call),
                requireRangeDouble(call, "weightKg", 30, 300),
                fat,
                requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(result));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void deleteBodyMetric(PluginCall call) {
        mutateVoid(call, () -> store().deleteBodyMetric(
            requireDate(call), requireUuid(call, "mutationId")
        ));
    }

    @PluginMethod
    public void saveDailyStatus(PluginCall call) {
        try {
            Integer sleep = optionalInt(call, "sleepQuality");
            if (sleep != null && (sleep < 1 || sleep > 5)) {
                throw new IllegalArgumentException("sleepQuality 必須介於 1 到 5");
            }
            JSONObject result = store().saveDailyStatus(
                requireUuid(call, "syncId"),
                requireDate(call),
                requireRangeInt(call, "energy", 1, 5),
                sleep,
                optionalText(call, "note", 2000),
                requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(result));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    @PluginMethod
    public void deleteDailyStatus(PluginCall call) {
        mutateVoid(call, () -> store().deleteDailyStatus(
            requireDate(call), requireUuid(call, "mutationId")
        ));
    }

    @PluginMethod
    public void putSetting(PluginCall call) {
        try {
            String key = requireText(call, "key", 1, 64);
            String value = requireText(call, "value", 1, 200);
            if (!"weekly_target_days".equals(key) || !value.matches("[1-7]")) {
                throw new IllegalArgumentException("weekly_target_days 必須是 1 到 7");
            }
            JSONObject result = store().putSetting(
                key,
                value,
                requireUuid(call, "syncId"),
                requireUuid(call, "mutationId")
            );
            SyncScheduler.kick(getContext());
            call.resolve(asJsObject(result));
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    /** F148：登出／刪帳後把本機清空——WebView 端只能整包觸發，不能挑表清。 */
    @PluginMethod
    public void wipe(PluginCall call) {
        try {
            store().wipeAllLocalData();
            call.resolve();
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
        return requireText(call, key, minLength, Integer.MAX_VALUE);
    }

    private static String requireText(PluginCall call, String key, int minLength, int maxLength) {
        String value = call.getString(key);
        if (value == null || value.trim().length() < minLength || value.trim().length() > maxLength) {
            throw new IllegalArgumentException(key + " 缺少或長度不合法");
        }
        return value.trim();
    }

    private static String optionalText(PluginCall call, String key, int maxLength) {
        String value = call.getString(key);
        if (value == null || value.trim().isEmpty()) return null;
        if (value.trim().length() > maxLength) throw new IllegalArgumentException(key + " 太長");
        return value.trim();
    }

    private static int requirePositive(PluginCall call, String key) {
        Integer value = call.getInt(key);
        if (value == null || value <= 0) throw new IllegalArgumentException(key + " 必須大於 0");
        return value;
    }

    private static Integer optionalPositive(PluginCall call, String key) {
        Integer value = call.getInt(key);
        if (value == null) return null;
        if (value <= 0) throw new IllegalArgumentException(key + " 必須大於 0");
        return value;
    }

    private static int requireRangeInt(PluginCall call, String key, int min, int max) {
        Integer value = call.getInt(key);
        if (value == null || value < min || value > max) {
            throw new IllegalArgumentException(key + " 必須介於 " + min + " 到 " + max);
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

    private static double requireRangeDouble(
        PluginCall call, String key, double min, double max
    ) {
        Double value = call.getDouble(key);
        if (value == null || !Double.isFinite(value) || value < min || value > max) {
            throw new IllegalArgumentException(key + " 超出允許範圍");
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

    private static void validateSetOptionals(Integer rpe, Integer restSeconds) {
        if (rpe != null && (rpe < 1 || rpe > 10)) {
            throw new IllegalArgumentException("rpe 必須介於 1 到 10");
        }
        if (restSeconds != null && restSeconds < 0) {
            throw new IllegalArgumentException("restSeconds 不得小於 0");
        }
    }

    /** F159：次數型與時間型互斥且必須擇一——哪一種由呼叫端（依動作 mode）決定，這裡只擋格式。 */
    private static void validateSetMode(Integer reps, Integer durationSeconds) {
        if ((reps == null) == (durationSeconds == null)) {
            throw new IllegalArgumentException("reps 與 durationSeconds 必須擇一且僅擇一");
        }
        if (reps != null && reps <= 0) throw new IllegalArgumentException("reps 必須大於 0");
        if (durationSeconds != null && durationSeconds <= 0) {
            throw new IllegalArgumentException("durationSeconds 必須大於 0");
        }
    }

    private static String requireMode(PluginCall call) {
        String value = call.getString("mode", "reps");
        if (!"reps".equals(value) && !"time".equals(value)) {
            throw new IllegalArgumentException("mode 必須是 reps 或 time");
        }
        return value;
    }

    private static JSArray requireTemplateExercises(PluginCall call) {
        JSArray items = call.getArray("exercises");
        if (items == null || items.length() == 0) {
            throw new IllegalArgumentException("exercises 至少需要一個動作");
        }
        Set<Integer> ids = new HashSet<>();
        for (int index = 0; index < items.length(); index++) {
            JSObject item;
            try {
                item = JSObject.fromJSONObject(items.getJSONObject(index));
            } catch (JSONException error) {
                throw new IllegalArgumentException("exercises 格式不合法", error);
            }
            Integer exerciseId = item.getInteger("exerciseId");
            Integer defaultSets = item.getInteger("defaultSets");
            Integer rest = item.getInteger("restHintSeconds");
            if (exerciseId == null || exerciseId <= 0 || !ids.add(exerciseId)) {
                throw new IllegalArgumentException("exerciseId 缺少、重複或不合法");
            }
            if (defaultSets == null || defaultSets <= 0) {
                throw new IllegalArgumentException("defaultSets 必須大於 0");
            }
            if (rest != null && (rest < 15 || rest > 600)) {
                throw new IllegalArgumentException("restHintSeconds 必須介於 15 到 600");
            }
        }
        return items;
    }

    private static JSArray requireWeekdays(PluginCall call) {
        JSArray days = call.getArray("weekdays", new JSArray());
        Set<Integer> unique = new HashSet<>();
        for (int index = 0; index < days.length(); index++) {
            int day;
            try {
                day = days.getInt(index);
            } catch (JSONException error) {
                throw new IllegalArgumentException("weekdays 格式不合法", error);
            }
            if (day < 1 || day > 7 || !unique.add(day)) {
                throw new IllegalArgumentException("weekdays 必須是 1 到 7 且不得重複");
            }
        }
        return days;
    }

    private static JSObject asJsObject(JSONObject value) {
        try {
            return JSObject.fromJSONObject(value);
        } catch (JSONException error) {
            throw new IllegalArgumentException("LocalStore 回傳格式不合法", error);
        }
    }

    private void mutateVoid(PluginCall call, Runnable mutation) {
        try {
            mutation.run();
            SyncScheduler.kick(getContext());
            call.resolve();
        } catch (IllegalArgumentException error) {
            rejectArgument(call, error);
        } catch (RuntimeException error) {
            rejectStore(call, error);
        }
    }

    private static void rejectArgument(PluginCall call, IllegalArgumentException error) {
        call.reject(error.getMessage(), "INVALID_ARGUMENT", error);
    }

    private static void rejectStore(PluginCall call, RuntimeException error) {
        call.reject("LocalStore 無法完成操作", "LOCAL_STORE_ERROR", error);
    }
}
