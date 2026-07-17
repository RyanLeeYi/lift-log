// 單頁狀態：目前畫面、進行中的 workout、選中的動作、計時器。
// 重新整理後 workout 從 sessionStorage 續接（同一天的訓練不因手滑斷掉）。

const WORKOUT_KEY = "liftlog.activeWorkout";
const LANG_KEY = "liftlog.lang"; // zh | en

export const state = {
  screen: "home", // setup | home | picker | logger
  workoutId: null,
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
  sessionStorage.setItem(WORKOUT_KEY, JSON.stringify({ workoutId: state.workoutId }));
}

export function restoreActiveWorkout() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(WORKOUT_KEY));
    if (saved && saved.workoutId) state.workoutId = saved.workoutId;
  } catch {
    /* 壞資料當沒存過 */
  }
}

export function clearActiveWorkout() {
  sessionStorage.removeItem(WORKOUT_KEY);
  state.workoutId = null;
}

export function restElapsedSeconds() {
  if (state.restStartedAt === null) return null;
  return Math.round((Date.now() - state.restStartedAt) / 1000);
}
