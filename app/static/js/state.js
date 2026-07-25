// 單頁狀態：目前畫面、進行中的 workout、選中的動作、計時器。
// 重新整理後 workout 從 sessionStorage 續接（同一天的訓練不因手滑斷掉）。

// F24 版本號：顯示在畫面上供辨識手機載入的是哪一版（快取過期會顯示舊版號）。
// ⚠ 這個字串隨 shell 被 SW 快取，改版時務必與 sw.js 的 CACHE_NAME 一起遞增（兩處同步）。
export const APP_VERSION = "v52";

const WORKOUT_KEY = "liftlog.activeWorkout";
const LANG_KEY = "liftlog.lang"; // zh | en

export const state = {
  screen: "home", // setup | home | templateSelect | picker | logger | templates | templateEdit | calendar | body
  workoutId: null,
  template: null, // 開練選中的課表快照 {id, name, exercises}；刪課表不影響進行中訓練
  exercise: null, // {id, name_zh, name_en, is_bodyweight}
  weightKg: 20,
  reps: 8,
  rpe: 6, // F40：累度軸預設「輕鬆」＝6（新組必帶 rpe，不再有未記空狀態）
  setNumber: 1,
  doneSets: [], // 本回合該動作已完成的組（顯示用）
  doneByExercise: {}, // F32 {exerciseId:[sets]}——本次 workout 各動作已做組的鏡射；換動作後回到該動作原樣還原，不被誤標成「上次」
  setCounts: {}, // {exerciseId: 本次 workout 已記組數} —— 回頭選同動作時 set_number 接續
  restStartedAt: null, // ms timestamp；null = 計時器未啟動（＝就緒態，按鈕顯示「完成這組」）
  restHintOverrides: {}, // {exerciseId: 秒}——R10 訓練中臨時調整，僅本次 workout、不寫回課表
  pendingRestSeconds: null, // F15：按「繼續下一組」凍結的休息秒數，寫進下一組後清空（transient，不持久化）
  muscleFilter: null,
  searchQ: "",
  submitting: false,
  error: null,
  queue: { pending: 0, failed: 0 }, // 離線佇列計數（顯示「待同步」標示用）
  queueStatus: {}, // {client_uuid: "pending"|"failed"}——done-list 標示的唯一來源，隨佇列即時推導
};

export function getLang() {
  return localStorage.getItem(LANG_KEY) || "zh";
}

export function toggleLang() {
  localStorage.setItem(LANG_KEY, getLang() === "zh" ? "en" : "zh");
}

export function exerciseName(exercise) {
  return getLang() === "zh" ? exercise.name_zh : exercise.name_en;
}

export function exerciseAlias(exercise) {
  return getLang() === "zh" ? exercise.name_en : exercise.name_zh;
}

export function saveActiveWorkout() {
  sessionStorage.setItem(
    WORKOUT_KEY,
    JSON.stringify({
      workoutId: state.workoutId,
      template: state.template,
      setCounts: state.setCounts, // 續接恢復：重新整理後 set_number 不得與已存組撞號
      doneByExercise: state.doneByExercise, // F32：本次各動作已做組，換動作/重整後還原不丟
      restHintOverrides: state.restHintOverrides, // 臨時調整跟著本次訓練走，重整不丟
    }),
  );
}

export function restoreActiveWorkout() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(WORKOUT_KEY));
    if (saved && saved.workoutId) {
      state.workoutId = saved.workoutId;
      state.template = saved.template || null;
      state.setCounts = saved.setCounts || {};
      state.doneByExercise = saved.doneByExercise || {};
      state.restHintOverrides = saved.restHintOverrides || {};
    }
  } catch {
    /* 壞資料當沒存過 */
  }
}

export function clearActiveWorkout() {
  sessionStorage.removeItem(WORKOUT_KEY);
  state.workoutId = null;
  state.template = null;
  state.doneByExercise = {}; // F32：收工/結束訓練清掉本次各動作組的鏡射
  state.restHintOverrides = {};
}

export function restElapsedSeconds() {
  if (state.restStartedAt === null) return null;
  return Math.round((Date.now() - state.restStartedAt) / 1000);
}

// ---------- R10 參考休息：倒數的基準值 ----------

export const DEFAULT_REST_HINT_SECONDS = 60; // 未設參考值一律預設 60（含臨時動作與自由訓練）

export function restHintFor(exerciseId) {
  const override = state.restHintOverrides[exerciseId];
  if (override != null) return override;
  const item = state.template?.exercises?.find((e) => e.exercise_id === exerciseId);
  return item?.rest_hint_seconds ?? DEFAULT_REST_HINT_SECONDS;
}

export function restRemainingSeconds() {
  // 剩餘秒數（可為負＝超時）；計時器未跑或不在動作內回 null
  const elapsed = restElapsedSeconds();
  if (elapsed === null || !state.exercise) return null;
  return restHintFor(state.exercise.id) - elapsed;
}
