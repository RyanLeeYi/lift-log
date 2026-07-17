// 單頁狀態：目前畫面、進行中的 workout、選中的動作、計時器。
// 重新整理後 workout 從 sessionStorage 續接（同一天的訓練不因手滑斷掉）。

const WORKOUT_KEY = "liftlog.activeWorkout";
const LANG_KEY = "liftlog.lang"; // zh | en

export const state = {
  screen: "home", // setup | home | templateSelect | picker | logger | templates | templateEdit | calendar | body
  workoutId: null,
  template: null, // 開練選中的課表快照 {id, name, exercises}；刪課表不影響進行中訓練
  exercise: null, // {id, name_zh, name_en, is_bodyweight}
  weightKg: 20,
  reps: 8,
  rpe: null,
  setNumber: 1,
  doneSets: [], // 本回合該動作已完成的組（顯示用）
  setCounts: {}, // {exerciseId: 本次 workout 已記組數} —— 回頭選同動作時 set_number 接續
  restStartedAt: null, // ms timestamp；null = 計時器未啟動
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
    }
  } catch {
    /* 壞資料當沒存過 */
  }
}

export function clearActiveWorkout() {
  sessionStorage.removeItem(WORKOUT_KEY);
  state.workoutId = null;
  state.template = null;
}

export function restElapsedSeconds() {
  if (state.restStartedAt === null) return null;
  return Math.round((Date.now() - state.restStartedAt) / 1000);
}
