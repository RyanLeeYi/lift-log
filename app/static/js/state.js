// 單頁狀態：目前畫面、進行中的 workout、選中的動作、計時器。
// F90：進行中的 workout 存 localStorage（原本是 sessionStorage）。sessionStorage 是分頁級的，
// 分頁一關或 app 被系統回收就整份消失，首頁退回「開始訓練」→ 按下去另建一場 workout、
// 組號從 1 重來，同一天同一場訓練被切成兩筆。localStorage 撐得過回收與重開機。

// F24 版本號：顯示在畫面上供辨識手機載入的是哪一版（快取過期會顯示舊版號）。
// ⚠ 這個字串隨 shell 被 SW 快取，改版時務必與 sw.js 的 CACHE_NAME 一起遞增（兩處同步）。
export const APP_VERSION = "v91";

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
  // F71：休息時間改成「累計計時中的時間」，不能再用 now - restStartedAt 直接算——
  // 暫停期間不計入（acceptance ③），而 rest_seconds 是會寫進訓練資料的欄位。
  restAccumulatedMs: 0, // 先前各段「計時中」的總和
  restResumedAt: null, // 這一段計時開始的時間戳；null = 目前暫停中
  restTargetSeconds: null, // F70：這輪休息的目標秒數（休息開始時快照；改秒數時同步）——換動作後倒數基準不跳
  lastRef: null, // F84：上次提示卡的結構化資料 {date, weight, reps}；沒有歷史時為 null
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

/** 本地日期 YYYY-MM-DD。刻意不用 toISOString——那是 UTC，台灣早上八點前會算成昨天。 */
function todayIso() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function saveActiveWorkout() {
  localStorage.setItem(
    WORKOUT_KEY,
    JSON.stringify({
      workoutId: state.workoutId,
      date: todayIso(), // F90 ②：跨日不續接的判斷依據
      template: state.template,
      setCounts: state.setCounts, // 續接恢復：重新整理後 set_number 不得與已存組撞號
      doneByExercise: state.doneByExercise, // F32：本次各動作已做組，換動作/重整後還原不丟
      restHintOverrides: state.restHintOverrides, // 臨時調整跟著本次訓練走，重整不丟
    }),
  );
}

/**
 * F90 ①②：同步還原本地狀態。
 *
 * 這裡**只**做本地能判斷的事（有沒有、是不是今天）。「伺服器上還在不在」是非同步的，
 * 由 app.js 的 confirmActiveWorkout() 接手——render() 是同步的，把網路請求塞進來會讓
 * 首頁在啟動時空一拍。
 */
export function restoreActiveWorkout() {
  try {
    // F90 遷移：舊版把狀態存在 sessionStorage。改版當下正在訓練的人重整後不該被丟掉，
    // 所以 localStorage 沒有、sessionStorage 有的話搬過來一次。
    let raw = localStorage.getItem(WORKOUT_KEY);
    if (!raw) {
      const legacy = sessionStorage.getItem(WORKOUT_KEY);
      if (legacy) {
        localStorage.setItem(WORKOUT_KEY, legacy);
        sessionStorage.removeItem(WORKOUT_KEY);
        raw = legacy;
      }
    }
    const saved = JSON.parse(raw);
    if (!saved || !saved.workoutId) return;
    // ②：不做跨日續接。沒有 date 的是遷移前存的，當成今天（那份本來就是本分頁的）。
    if (saved.date && saved.date !== todayIso()) {
      clearActiveWorkout();
      return;
    }
    state.workoutId = saved.workoutId;
    state.template = saved.template || null;
    state.setCounts = saved.setCounts || {};
    state.doneByExercise = saved.doneByExercise || {};
    state.restHintOverrides = saved.restHintOverrides || {};
  } catch {
    /* 壞資料當沒存過 */
  }
}

export function clearActiveWorkout() {
  localStorage.removeItem(WORKOUT_KEY);
  sessionStorage.removeItem(WORKOUT_KEY); // 遷移期的殘留也一併清掉
  state.workoutId = null;
  state.template = null;
  state.setCounts = {}; // F90：不清會讓下一場的組號從上一場接續下去
  state.doneByExercise = {}; // F32：收工/結束訓練清掉本次各動作組的鏡射
  state.restHintOverrides = {};
}

// F71 ③：只算「計時中」的時間，暫停的那幾段不計入。
export function restElapsedSeconds() {
  if (state.restStartedAt === null) return null;
  const running = state.restResumedAt === null ? 0 : Date.now() - state.restResumedAt;
  return Math.round((state.restAccumulatedMs + running) / 1000);
}

export function restPaused() {
  return state.restStartedAt !== null && state.restResumedAt === null;
}

/** F71 ②：暫停——把這一段累加起來，之後 restElapsedSeconds 就不再往前走。 */
export function pauseRest() {
  if (state.restStartedAt === null || state.restResumedAt === null) return;
  state.restAccumulatedMs += Date.now() - state.restResumedAt;
  state.restResumedAt = null;
}

/** F71 ②：繼續——開新的一段，從剩餘秒數接續（不重頭算）。 */
export function resumeRest() {
  if (state.restStartedAt === null || state.restResumedAt !== null) return;
  state.restResumedAt = Date.now();
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
  // 剩餘秒數（可為負＝超時）；計時器未跑回 null
  const elapsed = restElapsedSeconds();
  if (elapsed === null) return null;
  // F70：目標秒數在休息開始時就快照下來（restTargetSeconds），不再每次都問「當前動作」——
  // 休息中換動作時 state.exercise 會變成別的動作甚至 null，跟著問就會讓倒數基準跳掉，
  // 或整個算不出來（那正是 ① 之前做不到的原因）。改秒數時 cycleRestHint 會同步這個快照。
  const target = state.restTargetSeconds
    ?? (state.exercise ? restHintFor(state.exercise.id) : null);
  if (target === null) return null;
  return target - elapsed;
}
