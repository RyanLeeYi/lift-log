// Web 版走 REST；Android 核心 domain 走原生 LocalStore，網路只留給更新與推播等非 domain 功能。

import { apiBase, isNativeApp } from "./env.js";
import { getNativeAccessToken, getWebCsrfToken, restoreNativeSession } from "./auth.js";

const TOKEN_KEY = "liftlog.token";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

/**
 * F146：有 web session 就走 cookie＋CSRF header，沒有才退回舊的 Bearer token。
 * 兩條路併存是刻意的——舊的單一 token 仍是既有 e2e 與尚未改用 Google 登入的入口。
 */
export function authHeaders(body, { csrf = getWebCsrfToken(), token } = {}) {
  const contentType = body ? { "Content-Type": "application/json" } : {};
  // 有 web session 就不必碰 localStorage——順帶讓這個函式在沒有 DOM 的地方也能測
  if (csrf) {
    return { headers: { "X-CSRF-Token": csrf, ...contentType }, credentials: "include" };
  }
  return { headers: { Authorization: `Bearer ${token ?? getToken()}`, ...contentType } };
}

async function request(method, path, body, bearerToken = getToken()) {
  let resp;
  try {
    resp = await fetch(apiBase() + path, {
      method,
      ...authHeaders(body, { token: bearerToken }),
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "連不上伺服器——檢查網路後再試一次");
  }
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(resp.status, data.error || `HTTP ${resp.status}`);
  return data;
}

const localStore = () => globalThis.Capacitor?.Plugins?.LocalStore;
let localReady = null;

async function localCall(method, payload = {}) {
  const store = localStore();
  if (!store?.[method]) throw new ApiError(503, "這個 APK 不支援本地資料庫，請更新 App");
  localReady ??= store.initialize();
  await localReady;
  try {
    return await store[method](payload);
  } catch (error) {
    throw new ApiError(500, error?.message || "本地資料庫操作失敗");
  }
}

const nativeOr = (local, remote) => (isNativeApp() ? local() : remote());
const uuid = () => crypto.randomUUID();
const todayIso = () => {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
};
const byId = (rows) => new Map(rows.map((row) => [row.id, row]));
// F105 ①：時間型的組（reps 為 null）一律不進噸位——同一條規則，離線與後端各自算一次會漂移。
const volumeFor = (weightKg, reps) => (reps != null ? weightKg * reps : 0);

async function snapshot() {
  return localCall("snapshot");
}

function workoutOut(workout) {
  if (!workout) throw new ApiError(404, "找不到訓練");
  return {
    id: workout.id,
    date: workout.date,
    template_id: workout.template_id,
    note: workout.note,
    created_at: workout.created_at,
    ended_at: workout.ended_at,
    template_snapshot: workout.template_snapshot ?? null,
  };
}

function setOut(set) {
  return {
    id: set.id,
    client_uuid: set.client_uuid,
    workout_id: set.workout_id,
    exercise_id: set.exercise_id,
    set_number: set.set_number,
    weight_kg: set.weight_kg,
    reps: set.reps,
    // F105：次數型為 null、時間型有值；本機資料若還沒帶這欄（F105 之前寫入的）視為 null。
    duration_seconds: set.duration_seconds ?? null,
    rpe: set.rpe,
    rest_seconds: set.rest_seconds,
  };
}

async function localExercises(q = "", hasData = false) {
  const data = await snapshot();
  const needle = q.trim().toLocaleLowerCase();
  const used = new Set(data.sets.map((set) => set.exercise_id));
  // F105：省略＝次數型，與後端 ExerciseCreate 預設一致（本機舊資料未帶 mode 時的退回值）。
  return data.exercises.filter((exercise) => {
    if (hasData && !used.has(exercise.id)) return false;
    return !needle || exercise.name_zh.toLocaleLowerCase().includes(needle)
      || exercise.name_en.toLocaleLowerCase().includes(needle);
  }).map((exercise) => ({ ...exercise, mode: exercise.mode ?? "reps" }));
}

async function localTemplates() {
  const data = await snapshot();
  const workouts = byId(data.workouts);
  return data.templates.map((template) => {
    const sessions = data.sets
      .filter((set) => workouts.get(set.workout_id)?.template_id === template.id)
      .reduce((map, set) => {
        const workout = workouts.get(set.workout_id);
        const row = map.get(set.workout_id) ?? { date: workout.date, id: workout.id, volume: 0 };
        row.volume += volumeFor(set.weight_kg, set.reps);
        map.set(set.workout_id, row);
        return map;
      }, new Map());
    const latest = [...sessions.values()].sort((a, b) =>
      a.date.localeCompare(b.date) || a.id - b.id).at(-1);
    return {
      id: template.id,
      name: template.name,
      weekdays: template.weekdays,
      exercises: template.exercises,
      last_used_date: latest?.date ?? null,
      last_volume_kg: latest ? Math.round(latest.volume * 10) / 10 : null,
    };
  });
}

async function localLastSets(exerciseId, excludeWorkoutId = null) {
  const data = await snapshot();
  const workouts = byId(data.workouts);
  const candidates = data.sets.filter((set) =>
    set.exercise_id === exerciseId && set.workout_id !== excludeWorkoutId);
  if (!candidates.length) return [];
  const latest = candidates.map((set) => workouts.get(set.workout_id))
    .filter(Boolean).sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id).at(-1);
  return candidates.filter((set) => set.workout_id === latest.id)
    .sort((a, b) => a.set_number - b.set_number)
    .map((set) => ({ ...setOut(set), workout_date: latest.date }));
}

async function localWorkoutDetail(workoutId) {
  const data = await snapshot();
  const workout = data.workouts.find((row) => row.id === workoutId);
  return {
    ...workoutOut(workout),
    sets: data.sets.filter((set) => set.workout_id === workoutId)
      .sort((a, b) => a.set_number - b.set_number).map(setOut),
  };
}

const emptyPrs = () => ({
  top_weight: null,
  top_set_volume: null,
  top_est_1rm: null,
  top_session_volume: null,
  top_set_duration: null,
  top_session_duration_seconds: null,
});

// F105 ⑤：時間型只有兩項 PR（最長單組秒數、單次訓練總秒數）——估計 1RM 對「撐幾秒」沒有意義。
function timePrs(rows) {
  const timed = rows.filter((row) => row.duration_seconds != null);
  if (!timed.length) return emptyPrs();
  const longest = timed.reduce((best, row) => row.duration_seconds > best.duration_seconds ? row : best);
  const perWorkout = new Map();
  for (const row of timed) {
    perWorkout.set(row.workout_id, (perWorkout.get(row.workout_id) ?? 0) + row.duration_seconds);
  }
  return {
    ...emptyPrs(),
    top_set_duration: { weight_kg: longest.weight_kg, reps: null, duration_seconds: longest.duration_seconds },
    top_session_duration_seconds: Math.max(...perWorkout.values()),
  };
}

function repsPrs(rows) {
  const counted = rows.filter((row) => row.reps != null);
  if (!counted.length) return emptyPrs();
  const topWeight = counted.reduce((best, row) => row.weight_kg > best.weight_kg ? row : best);
  const topVolume = counted.reduce((best, row) =>
    row.weight_kg * row.reps > best.weight_kg * best.reps ? row : best);
  const perWorkout = new Map();
  for (const row of counted) {
    perWorkout.set(row.workout_id, (perWorkout.get(row.workout_id) ?? 0) + row.weight_kg * row.reps);
  }
  return {
    ...emptyPrs(),
    top_weight: { weight_kg: topWeight.weight_kg, reps: topWeight.reps, duration_seconds: null },
    top_set_volume: { weight_kg: topVolume.weight_kg, reps: topVolume.reps, duration_seconds: null },
    // Epley：w × (1 + reps/30)
    top_est_1rm: Math.max(...counted.map((row) => row.weight_kg * (1 + row.reps / 30))),
    top_session_volume: Math.max(...perWorkout.values()),
  };
}

async function localExerciseHistory(exerciseId, from, to) {
  const data = await snapshot();
  const exercise = data.exercises.find((row) => row.id === exerciseId);
  if (!exercise) throw new ApiError(404, "找不到動作");
  const workouts = byId(data.workouts);
  const all = data.sets.filter((set) => set.exercise_id === exerciseId);
  const sessions = new Map();
  for (const set of all) {
    const workout = workouts.get(set.workout_id);
    if (!workout || workout.date < from || workout.date > to) continue;
    const session = sessions.get(workout.id) ?? { workout_id: workout.id, date: workout.date, sets: [] };
    session.sets.push({
      id: set.id,
      set_number: set.set_number,
      weight_kg: set.weight_kg,
      reps: set.reps,
      duration_seconds: set.duration_seconds ?? null,
      rpe: set.rpe,
    });
    sessions.set(workout.id, session);
  }
  const dates = all.map((row) => workouts.get(row.workout_id)?.date).filter(Boolean).sort();
  return {
    // F105：全期（不限 from/to）PR，依動作 mode 分流——四項不看區間，用區間值填會是靜默的謊。
    prs: !all.length ? emptyPrs() : exercise.mode === "time" ? timePrs(all) : repsPrs(all),
    sessions: [...sessions.values()].sort((a, b) => a.date.localeCompare(b.date) || a.workout_id - b.workout_id),
    first_session_date: dates[0] ?? null,
  };
}

async function localCalendar(year, month) {
  const data = await snapshot();
  const workouts = byId(data.workouts);
  const exercises = byId(data.exercises);
  const latestWeight = [...data.body_metrics].sort((a, b) => a.date.localeCompare(b.date)).at(-1)?.weight_kg;
  const prefix = `${year}-${String(month).padStart(2, "0")}`;
  // F105 ④：days 從單一噸位數字改成 {tonnage_kg, duration_seconds, sets_count}——
  // 熱力圖分級改吃 sets_count（兩種模式共有；時間型不進噸位，只吃噸位的日子會被畫成沒練）。
  const days = {};
  for (const set of data.sets) {
    const date = workouts.get(set.workout_id)?.date;
    if (!date?.startsWith(prefix)) continue;
    const day = days[date] ?? (days[date] = { tonnage_kg: 0, duration_seconds: 0, sets_count: 0 });
    const bodyweight = exercises.get(set.exercise_id)?.is_bodyweight ? latestWeight ?? 0 : 0;
    day.tonnage_kg += volumeFor(set.weight_kg + bodyweight, set.reps);
    day.duration_seconds += set.duration_seconds ?? 0;
    day.sets_count += 1;
  }
  return { year, month, days };
}

function weekStart(date) {
  const day = new Date(`${date}T12:00:00`);
  const iso = day.getDay() || 7;
  day.setDate(day.getDate() - iso + 1);
  return day;
}

function dateIso(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

async function localScheduleToday() {
  const data = await snapshot();
  const today = todayIso();
  const weekday = new Date(`${today}T12:00:00`).getDay() || 7;
  const start = weekStart(today);
  const week = Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return dateIso(day);
  });
  const workouts = byId(data.workouts);
  const trained = new Set(data.sets.map((set) => workouts.get(set.workout_id)?.date).filter(Boolean));
  const sessions = data.workouts.map((workout) => {
    const sets = data.sets.filter((set) => set.workout_id === workout.id);
    return { workout, sets };
  }).filter(({ workout, sets }) => workout.date <= today && sets.length)
    .sort((a, b) => a.workout.date.localeCompare(b.workout.date) || a.workout.id - b.workout.id);
  const last = sessions.at(-1);
  const template = last ? data.templates.find((row) => row.id === last.workout.template_id) : null;
  const target = Number(data.settings.find((row) => row.key === "weekly_target_days")?.value ?? 4);
  return {
    date: today,
    weekday,
    templates: data.templates.filter((row) => row.weekdays.includes(weekday)).map((row) => ({
      id: row.id,
      name: row.name,
      exercise_count: row.exercises.length,
      set_count: row.exercises.reduce((sum, item) => sum + item.default_sets, 0),
    })),
    last_workout: last ? {
      date: last.workout.date,
      template_name: template?.name ?? null,
      set_count: last.sets.length,
      volume_kg: Math.round(last.sets.reduce((sum, set) =>
        sum + volumeFor(set.weight_kg, set.reps), 0) * 10) / 10,
    } : null,
    weekly_target_days: target,
    week_done_days: week.filter((day) => trained.has(day)).length,
    week_days: week.map((day) => trained.has(day)),
  };
}

const localApi = {
  searchExercises: (q) => localExercises(q, false),
  createExercise: (payload) => localCall("createExercise", {
    syncId: uuid(), mutationId: uuid(), nameZh: payload.name_zh,
    nameEn: payload.name_en, muscleGroup: payload.muscle_group,
    isBodyweight: Boolean(payload.is_bodyweight),
    // F105：省略＝次數型，與後端 ExerciseCreate 預設一致。
    mode: payload.mode ?? "reps",
  }),
  exercisesWithData: () => localExercises("", true),
  lastSets: localLastSets,
  createWorkout: (payload = {}) => localCall("createWorkout", {
    syncId: uuid(), mutationId: uuid(), date: payload.date ?? todayIso(),
    templateId: payload.template_id, note: payload.note, leaseGeneration: 1,
  }),
  listTemplates: localTemplates,
  createTemplate: (payload) => localCall("saveTemplate", {
    syncId: uuid(), mutationId: uuid(), name: payload.name,
    weekdays: payload.weekdays ?? [],
    exercises: payload.exercises.map((item) => ({
      exerciseId: item.exercise_id,
      defaultSets: item.default_sets,
      restHintSeconds: item.rest_hint_seconds,
    })),
  }),
  updateTemplate: (id, payload) => localCall("saveTemplate", {
    id, mutationId: uuid(), name: payload.name, weekdays: payload.weekdays ?? [],
    exercises: payload.exercises.map((item) => ({
      exerciseId: item.exercise_id,
      defaultSets: item.default_sets,
      restHintSeconds: item.rest_hint_seconds,
    })),
  }),
  deleteTemplate: (id) => localCall("deleteTemplate", { id, mutationId: uuid() }),
  logSet: (workoutId, payload) => localCall("addSet", {
    syncId: uuid(), mutationId: uuid(), workoutId, exerciseId: payload.exercise_id,
    clientUuid: payload.client_uuid, setNumber: payload.set_number,
    weightKg: payload.weight_kg, reps: payload.reps,
    // F105：兩者互斥且擇一，同 SetCreate（強制放在動作對應的 store 實作，這裡只轉遞欄位）。
    durationSeconds: payload.duration_seconds, rpe: payload.rpe,
    restSeconds: payload.rest_seconds, leaseGeneration: 1,
  }),
  updateSet: (id, payload) => localCall("updateSet", {
    id, mutationId: uuid(), weightKg: payload.weight_kg, reps: payload.reps,
    durationSeconds: payload.duration_seconds,
    rpe: payload.rpe, restSeconds: payload.rest_seconds,
  }),
  deleteSet: (id) => localCall("deleteSet", { id, mutationId: uuid() }),
  exerciseHistory: localExerciseHistory,
  workoutDetail: localWorkoutDetail,
  endWorkout: (id) => localCall("endWorkout", { id, mutationId: uuid() }),
  deleteWorkout: (id) => localCall("deleteWorkout", { id, mutationId: uuid() }),
  listWorkouts: async (start, end) => (await snapshot()).workouts
    .filter((row) => (!start || row.date >= start) && (!end || row.date <= end))
    .map(workoutOut),
  calendarStats: localCalendar,
  listBodyMetrics: async (range) => (await snapshot()).body_metrics
    .filter((row) => !range || row.date >= range.from && row.date <= range.to),
  bodyMetricBounds: async () => {
    const rows = (await snapshot()).body_metrics;
    const dates = rows.map((row) => row.date).sort();
    const fat = rows.filter((row) => row.body_fat_pct != null).map((row) => row.date).sort();
    return { weight_first: dates[0] ?? null, fat_first: fat[0] ?? null, last: dates.at(-1) ?? null };
  },
  logBodyMetric: (payload) => localCall("saveBodyMetric", {
    syncId: uuid(), mutationId: uuid(), date: payload.date ?? todayIso(),
    weightKg: payload.weight_kg, bodyFatPct: payload.body_fat_pct,
  }),
  deleteBodyMetric: (date) => localCall("deleteBodyMetric", { date, mutationId: uuid() }),
  listDailyStatus: async (start, end) => (await snapshot()).daily_status
    .filter((row) => (!start || row.date >= start) && (!end || row.date <= end)),
  logDailyStatus: (payload) => localCall("saveDailyStatus", {
    syncId: uuid(), mutationId: uuid(), date: payload.date ?? todayIso(), energy: payload.energy,
    sleepQuality: payload.sleep_quality, note: payload.note,
  }),
  deleteDailyStatus: (date) => localCall("deleteDailyStatus", { date, mutationId: uuid() }),
  lastSetValues: async (ids, excludeWorkoutId) => {
    const values = [];
    for (const id of ids) {
      const rows = await localLastSets(id, excludeWorkoutId);
      const last = rows.at(-1);
      if (last) values.push({
        exercise_id: id, weight_kg: last.weight_kg, reps: last.reps,
        duration_seconds: last.duration_seconds,
      });
    }
    return values;
  },
  scheduleToday: localScheduleToday,
  getSetting: async (key) => ({
    key,
    value: (await snapshot()).settings.find((row) => row.key === key)?.value
      ?? (key === "weekly_target_days" ? "4" : null),
  }),
  putSetting: (key, value) => localCall("putSetting", {
    key, value: String(value), syncId: uuid(), mutationId: uuid(),
  }),
};

export const api = {
  searchExercises: (q) => nativeOr(() => localApi.searchExercises(q), () =>
    request("GET", q ? `/api/exercises?q=${encodeURIComponent(q)}` : "/api/exercises")),
  createExercise: (payload) => nativeOr(() => localApi.createExercise(payload), () =>
    request("POST", "/api/exercises", payload)),
  exercisesWithData: () => nativeOr(localApi.exercisesWithData, () =>
    request("GET", "/api/exercises?has_data=true")),
  lastSets: (id, exclude) => nativeOr(() => localApi.lastSets(id, exclude), () =>
    request("GET", exclude != null
      ? `/api/exercises/${id}/last-sets?exclude_workout=${exclude}`
      : `/api/exercises/${id}/last-sets`)),
  createWorkout: (payload = {}) => nativeOr(() => localApi.createWorkout(payload), () =>
    request("POST", "/api/workouts", payload)),
  listTemplates: () => nativeOr(localApi.listTemplates, () => request("GET", "/api/templates")),
  createTemplate: (payload) => nativeOr(() => localApi.createTemplate(payload), () =>
    request("POST", "/api/templates", payload)),
  updateTemplate: (id, payload) => nativeOr(() => localApi.updateTemplate(id, payload), () =>
    request("PUT", `/api/templates/${id}`, payload)),
  deleteTemplate: (id) => nativeOr(() => localApi.deleteTemplate(id), () =>
    request("DELETE", `/api/templates/${id}`)),
  logSet: (workoutId, payload) => nativeOr(() => localApi.logSet(workoutId, payload), () =>
    request("POST", `/api/workouts/${workoutId}/sets`, payload)),
  updateSet: (id, payload) => nativeOr(() => localApi.updateSet(id, payload), () =>
    request("PATCH", `/api/sets/${id}`, payload)),
  deleteSet: (id) => nativeOr(() => localApi.deleteSet(id), () => request("DELETE", `/api/sets/${id}`)),
  exerciseHistory: (id, from, to) => nativeOr(() => localApi.exerciseHistory(id, from, to), () =>
    request("GET", `/api/exercises/${id}/history?from=${from}&to=${to}`)),
  workoutDetail: (id) => nativeOr(() => localApi.workoutDetail(id), () =>
    request("GET", `/api/workouts/${id}`)),
  endWorkout: (id) => nativeOr(() => localApi.endWorkout(id), () =>
    request("POST", `/api/workouts/${id}/end`)),
  deleteWorkout: (id) => nativeOr(() => localApi.deleteWorkout(id), () =>
    request("DELETE", `/api/workouts/${id}`)),
  listWorkouts: (start, end) => nativeOr(() => localApi.listWorkouts(start, end), () =>
    request("GET", `/api/workouts?start=${start}&end=${end}`)),
  calendarStats: (year, month) => nativeOr(() => localApi.calendarStats(year, month), () =>
    request("GET", `/api/stats/calendar?year=${year}&month=${month}`)),
  listBodyMetrics: (range) => {
    if (range && !(range.from && range.to)) throw new Error("listBodyMetrics: range 需要同時有 from 與 to");
    return nativeOr(() => localApi.listBodyMetrics(range), () => request("GET",
      range ? `/api/body-metrics?start=${range.from}&end=${range.to}` : "/api/body-metrics"));
  },
  bodyMetricBounds: () => nativeOr(localApi.bodyMetricBounds, () => request("GET", "/api/body-metrics/range")),
  logBodyMetric: (payload) => nativeOr(() => localApi.logBodyMetric(payload), () =>
    request("POST", "/api/body-metrics", payload)),
  deleteBodyMetric: (date) => nativeOr(() => localApi.deleteBodyMetric(date), () =>
    request("DELETE", `/api/body-metrics/${date}`)),
  listDailyStatus: (start, end) => nativeOr(() => localApi.listDailyStatus(start, end), () =>
    request("GET", `/api/daily-status?start=${start}&end=${end}`)),
  logDailyStatus: (payload) => nativeOr(() => localApi.logDailyStatus(payload), () =>
    request("POST", "/api/daily-status", payload)),
  deleteDailyStatus: (date) => nativeOr(() => localApi.deleteDailyStatus(date), () =>
    request("DELETE", `/api/daily-status/${date}`)),
  appLatest: async () => {
    if (isNativeApp()) await restoreNativeSession();
    return request(
      "GET", "/api/app/latest", undefined,
      isNativeApp() ? getNativeAccessToken() : getToken(),
    );
  },
  lastSetValues: (ids, exclude) => nativeOr(() => localApi.lastSetValues(ids, exclude), () =>
    request("GET", `/api/exercises/last-set-values?ids=${ids.join(",")}`
      + (exclude ? `&exclude_workout=${exclude}` : ""))),
  scheduleToday: () => nativeOr(localApi.scheduleToday, () => request("GET", "/api/schedule/today")),
  getSetting: (key) => nativeOr(() => localApi.getSetting(key), () => request("GET", `/api/settings/${key}`)),
  putSetting: (key, value) => nativeOr(() => localApi.putSetting(key, value), () =>
    request("PUT", `/api/settings/${key}`, { value: String(value) })),
  pushPublicKey: () => request("GET", "/api/push/public-key"),
  pushSubscribe: (sub) => request("POST", "/api/push/subscribe", sub),
  scheduleRest: (seconds) => request("POST", "/api/push/rest-timer", { seconds }),
  cancelRest: () => request("POST", "/api/push/rest-timer/cancel"),
  // F148：匯出／刪帳一律真的打 server（不分 native/web，兩邊都是同一組 Google 帳號 API）。
  exportAccount: async (idToken, nonceValue) => {
    if (isNativeApp()) await restoreNativeSession();
    return request(
      "POST", "/api/account/export", { id_token: idToken, nonce: nonceValue },
      isNativeApp() ? getNativeAccessToken() : getToken(),
    );
  },
  deleteAccount: async (idToken, nonceValue, confirm) => {
    if (isNativeApp()) await restoreNativeSession();
    return request(
      "POST", "/api/account/delete", { id_token: idToken, nonce: nonceValue, confirm },
      isNativeApp() ? getNativeAccessToken() : getToken(),
    );
  },
  // F148：只有原生有本機 domain DB 需要清；web 沒有對應本機副本可清。
  wipeLocalData: () => localCall("wipe"),
  // F158：MCP token 是控制庫資料，不分 native／web 都是走真的 REST（沒有本機副本要同步）。
  // 同 exportAccount／deleteAccount：native 要帶 Google access token，不能落回 request() 預設的
  // getToken()（legacy 單一 token）——legacy scope 連 _user_id() 那關都過不了，會 401 把人踢回登入頁。
  listMcpTokens: async () => {
    if (isNativeApp()) await restoreNativeSession();
    return request(
      "GET", "/api/mcp-tokens/", undefined, isNativeApp() ? getNativeAccessToken() : getToken(),
    );
  },
  createMcpToken: async (payload) => {
    if (isNativeApp()) await restoreNativeSession();
    return request(
      "POST", "/api/mcp-tokens/", payload, isNativeApp() ? getNativeAccessToken() : getToken(),
    );
  },
  revokeMcpToken: async (id) => {
    if (isNativeApp()) await restoreNativeSession();
    return request(
      "DELETE", `/api/mcp-tokens/${id}`, undefined,
      isNativeApp() ? getNativeAccessToken() : getToken(),
    );
  },
};
