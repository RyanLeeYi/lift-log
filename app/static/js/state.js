// 單頁狀態：目前畫面、進行中的 workout、選中的動作、計時器。
// F90：進行中的 workout 存 localStorage（原本是 sessionStorage）。sessionStorage 是分頁級的，
// 分頁一關或 app 被系統回收就整份消失，首頁退回「開始訓練」→ 按下去另建一場 workout、
// 組號從 1 重來，同一天同一場訓練被切成兩筆。localStorage 撐得過回收與重開機。

// F24 版本號：顯示在畫面上供辨識手機載入的是哪一版（快取過期會顯示舊版號）。
// ⚠ 這個字串隨 shell 被 SW 快取，改版時務必與 sw.js 的 CACHE_NAME 一起遞增（兩處同步）。
export const APP_VERSION = "v102";

const WORKOUT_KEY = "liftlog.activeWorkout";
const LANG_KEY = "liftlog.lang"; // zh | en

export const state = {
  screen: "home", // setup | home | templateSelect | picker | logger | templates | templateEdit | calendar | body
  workoutId: null,
  // F90 ②：這場 workout **自己**的日期（伺服器給的），不是「上次存檔的時間」。
  // 練過午夜時兩者會分岔——用存檔時間的話，跨日後再記一組就會把昨天那場的日期改寫成今天，
  // 於是重載後把昨天的訓練當成今天的續接下去，組全部寫進昨天（Codex P1）。
  workoutDate: null,
  template: null, // 開練選中的課表快照 {id, name, exercises}；刪課表不影響進行中訓練
  exercise: null, // {id, name_zh, name_en, is_bodyweight}
  weightKg: 20,
  reps: 8,
  rpe: 6, // F40：累度軸預設「輕鬆」＝6（新組必帶 rpe，不再有未記空狀態）
  setNumber: 1,
  doneSets: [], // 本回合該動作已完成的組（顯示用）
  doneByExercise: {}, // F32 {exerciseId:[sets]}——本次 workout 各動作已做組的鏡射；換動作後回到該動作原樣還原，不被誤標成「上次」
  // {exerciseId: 本次 workout 已**完成的組數**}——menuCounts() 的課表進度（X/Y 組）用它。
  // ⚠ 這不是組號：刪掉中間某組後兩者會分岔，下一組的編號一律走 app.js 的 nextSetNumber()。
  setCounts: {},
  restStartedAt: null, // ms timestamp；null = 計時器未啟動（＝就緒態，按鈕顯示「完成這組」）
  // F71：休息時間改成「累計計時中的時間」，不能再用 now - restStartedAt 直接算——
  // 暫停期間不計入（acceptance ③），而 rest_seconds 是會寫進訓練資料的欄位。
  restAccumulatedMs: 0, // 先前各段「計時中」的總和
  restResumedAt: null, // 這一段計時開始的時間戳；null = 目前暫停中
  restTargetSeconds: null, // F70：這輪休息的目標秒數（休息開始時快照；改秒數時同步）——換動作後倒數基準不跳
  // F66 ④：存過休息但還原不了（過舊或壞資料）。畫面要講出來，不得靜默沒有倒數。
  // 生命週期：還原時設起 → logger 顯示 → 離開 logger／開新一輪休息／換一場訓練時清掉。
  // 不持久化——它描述的是「這次還原」發生了什麼，不是訓練的狀態。
  restRestoreDropped: false,
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
export function todayIso() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function saveActiveWorkout() {
  // F66：休息狀態變動時也會呼叫這支，而那些路徑（結束訓練、登出）可能已經沒有 workout 了。
  // 沒有 workout 就沒有東西該被續接——寫下去只會留一份 restore 一定會忽略的殘骸。
  if (!state.workoutId) return;
  localStorage.setItem(
    WORKOUT_KEY,
    JSON.stringify({
      workoutId: state.workoutId,
      // F90 ②：存這場 workout 自己的日期。不知道時（舊資料遷移過來的）才退回今天，
      // 但**不要**每次存檔都重寫成今天——那正是跨午夜會出事的原因。
      date: state.workoutDate ?? todayIso(),
      template: state.template,
      setCounts: state.setCounts, // 續接恢復：重新整理後 set_number 不得與已存組撞號
      doneByExercise: state.doneByExercise, // F32：本次各動作已做組，換動作/重整後還原不丟
      restHintOverrides: state.restHintOverrides, // 臨時調整跟著本次訓練走，重整不丟
      // F66 ①：休息倒數也要活過 app 被回收。四個欄位缺一都算不出剩餘秒數——
      // startedAt 判時效、accumulatedMs＋resumedAt 是 F71 的累計制、targetSeconds 是 F70 的目標快照。
      rest: restSnapshot(),
    }),
  );
}

/** F66 ①：休息狀態的持久化快照；沒在休息回 null。 */
function restSnapshot() {
  if (state.restStartedAt === null) return null;
  return {
    startedAt: state.restStartedAt,
    accumulatedMs: state.restAccumulatedMs,
    resumedAt: state.restResumedAt, // null＝暫停中（⑤ 還原後仍要是暫停態）
    targetSeconds: state.restTargetSeconds,
  };
}

/**
 * F66 ②④⑤：把快照還原回 state，回傳「有沒有還原成功」。
 *
 * ⑥ 這支刻意不碰 workout 的任何欄位，也不被 workout 的還原結果影響——
 * 兩者各自獨立，一邊失敗不影響另一邊。
 *
 * ⑤ 為什麼「回收期間不計入」不必特別處理：暫停時 `resumedAt` 是 null，
 * restElapsedSeconds() 只算 accumulatedMs；跑著時 resumedAt 是時間戳，
 * 經過的真實時間本來就該算進去（②）。兩條語意由同一個算式自然得出。
 */
function restoreRestSnapshot(rest) {
  if (!rest || typeof rest !== "object") return false;
  if (typeof rest.startedAt !== "number") return false;
  // ④ 資料過舊就不還原：12 小時前開始的休息還原出來只會是一個荒謬的超時數字。
  if (Date.now() - rest.startedAt > REST_STALE_AFTER_MS) return false;
  // 差值為負＝startedAt 在未來。裝置時鐘往回調（跨時區、手動改時間）會讓上面那道
  // 門檻失效，而經過時間變負數會算出「比目標還多」的剩餘秒數，排出一個很久以後才響的鬧鐘。
  if (Date.now() < rest.startedAt) return false;
  // targetSeconds 缺了就**當壞資料**，不要退成 null 硬還原（review MEDIUM-4）：
  // 那會做出一個永遠停在 0:01、不會響、也不顯示 ④ 提示的假倒數——正是 ④ 禁止的靜默失敗。
  // 合法的快照一定有它（startRestTimer 沒有動作時也會退 DEFAULT_REST_HINT_SECONDS）。
  if (typeof rest.targetSeconds !== "number") return false;
  // 同理，accumulatedMs 壞掉會把已累計的秒數靜默歸零，違反 ⑤。
  if (typeof rest.accumulatedMs !== "number") return false;
  if (rest.resumedAt !== null && typeof rest.resumedAt !== "number") return false;
  state.restStartedAt = rest.startedAt;
  state.restAccumulatedMs = rest.accumulatedMs;
  state.restResumedAt = rest.resumedAt;
  state.restTargetSeconds = rest.targetSeconds;
  return true;
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
    state.workoutDate = saved.date || null; // 由 confirmActiveWorkout 用伺服器的 detail.date 覆蓋校正
    state.template = saved.template || null;
    state.setCounts = saved.setCounts || {};
    state.doneByExercise = saved.doneByExercise || {};
    state.restHintOverrides = saved.restHintOverrides || {};
    // F66 ⑥：休息倒數獨立還原。放在最後、且不讓它的結果影響上面任何一行——
    // rest 區段壞掉時只是「這次沒有倒數」，不該連整場訓練一起丟掉。
    if (saved.rest) {
      state.restRestoreDropped = !restoreRestSnapshot(saved.rest);
    }
  } catch {
    /* 壞資料當沒存過 */
  }
}

export function clearActiveWorkout() {
  localStorage.removeItem(WORKOUT_KEY);
  sessionStorage.removeItem(WORKOUT_KEY); // 遷移期的殘留也一併清掉
  state.workoutId = null;
  state.workoutDate = null;
  state.template = null;
  state.setCounts = {}; // F90：不清會讓下一場的組號從上一場接續下去
  state.doneByExercise = {}; // F32：收工/結束訓練清掉本次各動作組的鏡射
  state.restHintOverrides = {};
  state.restRestoreDropped = false; // F66：換一場訓練，上一場的還原失敗提示不該跟著走
}

// F66 ④：距休息開始超過這個時間就不還原倒數（訓練本身仍依 F90 還原）。
// 12 小時是簽核凍結的門檻——健身房不會休息這麼久，超過就是「開著沒收工過夜」那種情況。
export const REST_STALE_AFTER_MS = 12 * 60 * 60 * 1000;

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
