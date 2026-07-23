// lift-log 記錄頁：setup → home →（templateSelect）→ picker → logger，全部由 render() 重繪；
// 課表管理（templates / templateEdit）在 templates.js。

import { api, ApiError, getToken, setToken } from "./api.js";
import { openBody, renderBody } from "./body.js";
import { openCalendar, renderCalendar } from "./calendar.js";
import { customExerciseModal } from "./custom-exercise.js";
import { el, rpePicker, stepper } from "./dom.js";
import {
  detailReturnScreen,
  openExerciseDetail,
  renderExerciseDetail,
} from "./exercise-detail.js";
import {
  cancelRestPush,
  disablePush,
  enablePush,
  pushEnabled,
  pushSupported,
  scheduleRestPush,
} from "./push.js";
import {
  discardFailed,
  enqueueSet,
  flushQueue,
  listQueued,
  queueCounts,
  removeQueued,
} from "./queue.js";
import {
  hasUnsavedTemplate,
  openTemplates,
  renderTemplateEdit,
  renderTemplates,
  restoreTemplateDraft,
  saveTemplateDraft,
} from "./templates.js";
import {
  APP_VERSION,
  clearActiveWorkout,
  exerciseAlias,
  exerciseName,
  getLang,
  restElapsedSeconds,
  restHintFor,
  restRemainingSeconds,
  restoreActiveWorkout,
  saveActiveWorkout,
  state,
  toggleLang,
} from "./state.js";

const root = document.getElementById("app");
let restTicker = null;
let wakeLock = null; // R10：logger 畫面保持螢幕常亮，離開時釋放
let wakeLockPending = false; // request 進行中——完成時要重驗畫面狀態，避免離開後鎖洩漏
let restAlerted = false; // 本段休息是否已提醒過；調長目標後重新武裝
// F16/F19 done-list 行內編輯/單擊刪除（key＝已同步組的 id，未同步組退回 client_uuid）
let editDraft = null; // {key, weight, reps, rpe} 正在行內編輯的草稿

function setRowKey(s) {
  return s.id != null ? `id:${s.id}` : `uuid:${s.client_uuid}`;
}

// ---------- 小工具 ----------

function todayLabel() {
  const now = new Date();
  return `${now.getMonth() + 1}/${now.getDate()}`;
}

function fmtClock(totalSeconds) {
  const m = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const s = String(totalSeconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function fmtRest(remaining) {
  // R10 倒數顯示：到 0 之後轉負數（-00:15＝超時 15 秒），實際量測照舊
  return remaining < 0 ? `-${fmtClock(-remaining)}` : fmtClock(remaining);
}

// F24：畫面角落的版本標記——手機載入哪版一眼可辨（快取過期會顯示舊版號）
function versionTag() {
  return el("div", { class: "version-tag" }, [APP_VERSION]);
}

// ---------- R10 Wake Lock：訓練畫面不鎖屏，倒數提醒才收得到 ----------

async function syncWakeLock() {
  const wanted = () => state.screen === "logger" && document.visibilityState === "visible";
  if (wanted() && wakeLock === null && !wakeLockPending) {
    wakeLockPending = true; // 防並行申請
    try {
      const lock = (await navigator.wakeLock?.request("screen")) ?? null;
      lock?.addEventListener("release", () => {
        if (wakeLock === lock) wakeLock = null; // 系統自行釋放（切頁）——回來時再要一次
      });
      if (wanted()) {
        wakeLock = lock;
      } else {
        lock?.release().catch(() => {}); // 申請期間已離開 logger：就地釋放，不留孤兒鎖
      }
    } catch {
      /* 不支援或被拒：靜默降級，功能照常 */
    } finally {
      wakeLockPending = false;
    }
  } else if (!wanted() && wakeLock !== null) {
    const lock = wakeLock;
    wakeLock = null;
    try {
      await lock.release();
    } catch {
      /* 已被系統釋放 */
    }
  }
}

function showError(message) {
  state.error = message;
  render();
}

async function guard(action) {
  try {
    state.error = null;
    await action();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      stopRestTimer();
      state.screen = "setup";
      state.error = "Token 無效——重新輸入";
      render();
      return;
    }
    showError(err.message);
  }
}

// ---------- 離線佇列（F5）：送不出去先入列，恢復連線自動補傳 ----------

function isOffline(err) {
  return err instanceof ApiError && err.status === 0;
}

async function refreshQueueCounts() {
  // 一次讀取同時推導計數與逐筆狀態——done-list 的 ⏳/⚠ 標示以佇列為唯一事實來源
  const entries = await listQueued();
  state.queue = {
    pending: entries.filter((e) => e.status === "pending").length,
    failed: entries.filter((e) => e.status === "failed").length,
  };
  state.queueStatus = Object.fromEntries(entries.map((e) => [e.client_uuid, e.status]));
}

function renderUnlessTyping() {
  // 背景同步觸發的重繪不得清掉使用者正在輸入的搜尋框（重繪會失焦收鍵盤）；
  // 略過也無妨——標示會在下一次自然重繪時更新
  const active = document.activeElement;
  if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA")) return;
  render();
}

// F32：把佇列生命週期（補傳成功換得 server id、捨棄失敗組）同步到 doneSets 與各動作鏡射並持久化。
// doneByExercise 可能含非當前動作的離線組，故要掃全部項目——否則換動作回來會復活無 id 的舊 payload，
// 之後刪除只移出佇列不刪 server、編輯撞 client_uuid 冪等失效（Codex P1）。
function reconcileDoneSets({ replace, remove } = {}) {
  const mapArr = (arr) =>
    arr
      .map((s) => (replace && replace.has(s.client_uuid) ? replace.get(s.client_uuid) : s))
      .filter((s) => !(remove && remove.has(s.client_uuid)));
  state.doneSets = mapArr(state.doneSets);
  state.doneByExercise = Object.fromEntries(
    Object.entries(state.doneByExercise).map(([id, arr]) => [id, mapArr(arr)]),
  );
  saveActiveWorkout();
}

async function syncQueue() {
  const before = state.queue;
  const synced = await flushQueue(api.logSet);
  // 補傳成功者把含 server id 的回應寫回 doneSets 與鏡射——否則使用者仍停在 logger 時，
  // 該筆缺 id 會被誤判未同步，之後在畫面上刪/改會打不到伺服器（Codex P1）
  if (synced.length > 0) {
    const byUuid = new Map(synced.map((x) => [x.client_uuid, x.saved]));
    reconcileDoneSets({ replace: byUuid });
  }
  await refreshQueueCounts();
  const changed =
    synced.length > 0 ||
    before.pending !== state.queue.pending ||
    before.failed !== state.queue.failed;
  if (changed) renderUnlessTyping();
}

function syncStatusLine() {
  const { pending, failed } = state.queue;
  if (pending === 0 && failed === 0) return [];
  const parts = [];
  if (pending > 0) parts.push(el("span", { class: "sync-pending" }, [`⏳ 待同步 ${pending} 組`]));
  if (failed > 0) {
    parts.push(
      el(
        "button",
        {
          class: "btn btn-danger sync-failed",
          onclick: () =>
            guard(async () => {
              const discarded = new Set(await discardFailed());
              // 捨棄＝這些組沒進 server——從清單與鏡射一併移除（F32 P1），不能讓它們看起來像已同步
              reconcileDoneSets({ remove: discarded });
              await refreshQueueCounts();
              render();
            }),
        },
        [`⚠ 同步失敗 ${failed} 組（點此捨棄）`],
      ),
    );
  }
  return [el("div", { class: "sync-line" }, parts)];
}

// ---------- setup ----------

function renderSetup() {
  const input = el("input", {
    type: "password",
    placeholder: "API token",
    autocomplete: "off",
  });
  const save = async () => {
    setToken(input.value.trim());
    await loadExercises(""); // 驗證 token 可用，順便預載動作庫
    state.screen = "home";
    render();
  };
  return el("section", { class: "screen setup" }, [
    el("div", { class: "mark" }, ["🏋️"]),
    el("h1", {}, ["lift-log"]),
    el("p", {}, ["輸入 API token 開始使用（存在這支手機上）"]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    input,
    el("button", { class: "btn btn-primary", onclick: () => guard(save) }, ["連線"]),
    versionTag(),
  ]);
}

// ---------- home ----------

async function goPicker() {
  if (pickerExercises.length === 0) await loadExercises("");
  state.screen = "picker";
  render();
}

async function startWorkout(template) {
  const workout = await api.createWorkout(template ? { template_id: template.id } : {});
  state.workoutId = workout.id;
  state.template = template; // 課表快照跟著這次訓練走，之後刪課表不受影響
  saveActiveWorkout();
  await goPicker();
}

function renderHome() {
  const start = async () => {
    if (state.workoutId) {
      await goPicker(); // 訓練開著：直接回去（課表已隨 workout 還原）
      return;
    }
    templateChoices = await api.listTemplates();
    if (templateChoices.length === 0) {
      await startWorkout(null);
      return;
    }
    state.screen = "templateSelect";
    render();
  };
  return el("section", { class: "screen" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, ["lift-log"]),
      el("span", { class: "date" }, [todayLabel()]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...syncStatusLine(),
    el("p", { class: "today-summary" }, [
      state.workoutId ? "今天的訓練還開著——繼續。" : "還沒開始。按下去，就是今天的第一組。",
    ]),
    el(
      "button",
      { class: "btn btn-primary home-start", onclick: () => guard(start) },
      [state.workoutId ? "繼續訓練" : "開練"],
    ),
    el(
      "button",
      {
        class: "btn",
        onclick: () =>
          guard(async () => {
            await openTemplates();
            state.screen = "templates";
            render();
          }),
      },
      ["📋 課表"],
    ),
    el(
      "button",
      {
        class: "btn",
        onclick: () =>
          guard(async () => {
            await openCalendar();
            state.screen = "calendar";
            render();
          }),
      },
      ["📅 日曆"],
    ),
    el(
      "button",
      {
        class: "btn",
        onclick: () =>
          guard(async () => {
            await openBody();
            state.screen = "body";
            render();
          }),
      },
      ["⚖️ 體重"],
    ),
    // F31：休息結束推播開關（不支援的瀏覽器不顯示）
    ...(pushSupported()
      ? [
          el(
            "button",
            {
              class: `btn push-toggle${pushEnabled() ? " on" : ""}`,
              onclick: () =>
                guard(async () => {
                  if (pushEnabled()) {
                    await disablePush();
                    render();
                    return;
                  }
                  const res = await enablePush();
                  if (res.ok) render();
                  else showError(res.reason);
                }),
            },
            [pushEnabled() ? "🔔 休息提醒：開" : "🔔 休息提醒：關"],
          ),
        ]
      : []),
    versionTag(),
  ]);
}

// ---------- templateSelect（開練：挑今日課表） ----------

let templateChoices = [];

function renderTemplateSelect() {
  return el("section", { class: "screen" }, [
    el("header", { class: "topbar" }, [el("h1", {}, ["今天練哪份？"])]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    el("div", { class: "exercise-list" }, [
      ...templateChoices.map((template) =>
        el(
          "button",
          { class: "btn exercise-item", onclick: () => guard(() => startWorkout(template)) },
          [
            el("span", {}, [template.name]),
            el("span", { class: "sub" }, [`${template.exercises.length} 動作`]),
          ],
        ),
      ),
      el(
        "button",
        { class: "btn exercise-item", onclick: () => guard(() => startWorkout(null)) },
        [
          el("span", {}, ["自由訓練"]),
          el("span", { class: "sub" }, ["不用課表"]),
        ],
      ),
    ]),
    el("button", { class: "btn btn-ghost", onclick: () => { state.screen = "home"; render(); } }, ["← 回首頁"]),
  ]);
}

// ---------- picker ----------

let pickerExercises = [];
let customFormOpen = false; // F10 自訂動作視窗是否開啟（picker）

async function loadExercises(q) {
  pickerExercises = await api.searchExercises(q || "");
}

function openCustomForm() {
  customFormOpen = true;
  render();
}

// 收工／結束訓練：只清 client 狀態回首頁；已記錄的組在 server（SSOT），佇列未同步的之後仍補傳進這個 workout。
// logger 的「收工」與 picker 的「結束訓練」共用（module 級 function 宣告會 hoist，logger 內引用不受順序影響）。
function endWorkout() {
  stopRestTimer();
  state.pendingRestSeconds = null;
  editDraft = null;
  clearActiveWorkout();
  state.setCounts = {};
  state.exercise = null;
  state.screen = "home";
  render();
}

// F10 picker 的自訂動作視窗（共用 customExerciseModal）。建立成功 → reload 動作庫並關窗，
// 新動作即出現在清單可直接記錄；離線刷新失敗用建立回傳值補進清單當 fallback（Codex P2）。
function pickerCustomModal() {
  const groups = [...new Set(pickerExercises.map((e) => e.muscle_group))];
  return customExerciseModal({
    groups,
    onCreated: (created) => {
      customFormOpen = false;
      state.searchQ = "";
      state.muscleFilter = null;
      guard(async () => {
        try {
          await loadExercises("");
        } catch {
          pickerExercises = [...pickerExercises, created];
        }
        render();
      });
    },
    onCancel: () => { customFormOpen = false; render(); },
    onFatal: (err) => guard(() => Promise.reject(err)), // 401 交全域 guard 導回 setup
  });
}

// F32：把目前動作的完成組鏡射進 doneByExercise，換動作後回到該動作可原樣還原（同一次訓練內）。
function rememberDoneSets() {
  if (!state.exercise) return;
  state.doneByExercise = { ...state.doneByExercise, [state.exercise.id]: state.doneSets };
}

async function pickExercise(exercise) {
  state.exercise = exercise;
  state.rpe = null;
  state.doneSets = [];
  state.setNumber = (state.setCounts[exercise.id] || 0) + 1; // 回頭選同動作時接續編號

  // F32：同一次訓練已做過這個動作 → 還原本次的組，不重抓「上次」
  //（last-sets 取「最近一次 workout」＝今天這次，會把本次的組誤標成上次、done-list 也空掉）
  let resumed = state.doneByExercise[exercise.id];
  // P2：v31→v32 升級時舊 session 無鏡射，但 setCounts>0 代表本次做過 → 從伺服器回填一次，
  // 否則跨部署的進行中訓練仍會把本次組誤標成「上次」（Codex P2）。離線回填失敗就退回原流程。
  const missingMirror = !Array.isArray(resumed) || resumed.length === 0;
  if (missingMirror && (state.setCounts[exercise.id] || 0) > 0 && state.workoutId) {
    try {
      const detail = await api.workoutDetail(state.workoutId);
      const grouped = {};
      for (const s of detail.sets) (grouped[s.exercise_id] ??= []).push(s);
      // 既有鏡射優先（可能含尚未上 server 的離線組），只補伺服器有、鏡射缺的動作
      state.doneByExercise = { ...grouped, ...state.doneByExercise };
      saveActiveWorkout();
      resumed = state.doneByExercise[exercise.id];
    } catch {
      /* 離線/失敗：退回下方 lastSets 流程 */
    }
  }
  if (Array.isArray(resumed) && resumed.length > 0) {
    state.doneSets = resumed.map((s) => ({ ...s }));
    const lastSet = state.doneSets[state.doneSets.length - 1];
    state.weightKg = lastSet.weight_kg; // 續接本次：預設帶本次最後一組
    state.reps = lastSet.reps;
    // 「上次」仍要顯示——但查的是**前一次** workout（排除本次），不是把本次組誤標成上次。
    // 查不到前一次（第一次做這個動作）才退回顯示本次摘要。離線就略過參考。
    let prev = [];
    try {
      prev = await api.lastSets(exercise.id, state.workoutId);
    } catch (err) {
      if (!isOffline(err)) throw err; // 401/5xx 交給 guard（導回 setup／顯示錯誤），不當成查無上次
      /* 離線：略過上次參考，done-list 仍是本次的組 */
    }
    if (state.exercise !== exercise) return; // await 期間已換動作/結束訓練：丟棄過期結果，別把畫面拉回 logger
    state.lastHint =
      prev.length > 0
        ? `上次  ${prev.map((s) => `${s.weight_kg}×${s.reps}`).join("  ")}`
        : `本次  ${state.doneSets.map((s) => `${s.weight_kg}×${s.reps}`).join("  ")}`;
    state.screen = "logger";
    render();
    return;
  }

  let last = [];
  let offline = false;
  try {
    // 排除進行中的 workout：即使本次剛做過，「上次」也指前一次訓練（F32）
    last = await api.lastSets(exercise.id, state.workoutId);
  } catch (err) {
    if (!isOffline(err)) throw err; // 離線拿不到「上次」——退而求其次，不擋記錄
    offline = true;
  }
  if (last.length > 0) {
    state.weightKg = last[0].weight_kg;
    state.reps = last[0].reps;
    state.lastHint = `上次  ${last.map((s) => `${s.weight_kg}×${s.reps}`).join("  ")}`;
  } else if (offline) {
    // 離線：沿用本次已排隊的同動作組數當預設，沒有就用通用預設；不假裝是「第一次做」
    const queued = (await listQueued()).filter(
      (e) =>
        e.status === "pending" &&
        e.workout_id === state.workoutId &&
        e.payload.exercise_id === exercise.id,
    );
    if (queued.length > 0) {
      const newest = queued[queued.length - 1].payload;
      state.weightKg = newest.weight_kg;
      state.reps = newest.reps;
      state.lastHint = `本次（待同步）  ${queued
        .map((e) => `${e.payload.weight_kg}×${e.payload.reps}`)
        .join("  ")}`;
    } else {
      state.weightKg = exercise.is_bodyweight ? 0 : 20;
      state.reps = 8;
      state.lastHint = "離線中——載不到上次紀錄";
    }
  } else {
    state.weightKg = exercise.is_bodyweight ? 0 : 20;
    state.reps = 8;
    state.lastHint = null;
  }
  if (state.exercise !== exercise) return; // await（lastSets/listQueued）期間已離開/換動作：丟棄過期結果
  state.screen = "logger";
  render();
}

// F38：開動作詳情頁（picker／logger 兩處入口共用）；記住來源畫面供返回
function openDetail(exercise, from) {
  return guard(async () => {
    await openExerciseDetail(exercise, from);
    state.screen = "exerciseDetail";
    render();
  });
}

function exerciseButtons() {
  const shown = state.muscleFilter
    ? pickerExercises.filter((e) => e.muscle_group === state.muscleFilter)
    : pickerExercises;
  return shown.map((exercise) =>
    // F38：主鍵（選這動作開始記錄）＋📈 詳情入口分成兩顆並排鈕，點📈不誤觸開始記錄
    el("div", { class: "exercise-row" }, [
      el(
        "button",
        { class: "btn exercise-item", onclick: () => guard(() => pickExercise(exercise)) },
        [
          el("span", {}, [exerciseName(exercise)]),
          el("span", { class: "sub" }, [exerciseAlias(exercise)]),
        ],
      ),
      el(
        "button",
        { class: "btn detail-link", "aria-label": "動作表現", onclick: () => openDetail(exercise, "picker") },
        ["📈"],
      ),
    ]),
  );
}

function templateMenu() {
  if (!state.template) return [];
  return [
    el("div", { class: "menu-head" }, [`今日菜單 · ${state.template.name}`]),
    el("div", { class: "exercise-list menu-list" },
      state.template.exercises.map((item) => {
        const done = state.setCounts[item.exercise_id] || 0;
        return el(
          "button",
          {
            class: `btn exercise-item${done >= item.default_sets ? " menu-done" : ""}`,
            onclick: () =>
              guard(() =>
                pickExercise({
                  id: item.exercise_id,
                  name_zh: item.name_zh,
                  name_en: item.name_en,
                  muscle_group: item.muscle_group,
                  is_bodyweight: item.is_bodyweight,
                }),
              ),
          },
          [
            el("span", {}, [exerciseName(item)]),
            el("span", { class: `sub${done > 0 ? " lit" : ""}` }, [
              `${done}/${item.default_sets} 組`,
            ]),
          ],
        );
      }),
    ),
    el("div", { class: "menu-head" }, ["臨時加動作"]),
  ];
}

function renderPicker() {
  const groups = [...new Set(pickerExercises.map((e) => e.muscle_group))];
  // F23：pick-list＝臨時加動作清單，固定高度可捲動（不含今日菜單 .menu-list）
  const list = el("div", { class: "exercise-list pick-list" }, exerciseButtons());

  return el("section", { class: "screen picker" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, [state.template ? "今日菜單" : "選動作"]),
      el(
        "button",
        { class: "btn btn-ghost chip", onclick: () => { toggleLang(); render(); } },
        [getLang() === "zh" ? "EN" : "中"],
      ),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...templateMenu(),
    el("input", {
      type: "search",
      placeholder: "搜尋（中英皆可）",
      value: state.searchQ,
      // 只更新清單、不整頁重繪——重繪會清空輸入框並讓鍵盤失焦
      oninput: (e) => {
        state.searchQ = e.target.value;
        guard(async () => {
          await loadExercises(state.searchQ);
          list.replaceChildren(...exerciseButtons());
        });
      },
    }),
    el("div", { class: "chips" },
      groups.map((g) =>
        el(
          "button",
          {
            class: `chip${state.muscleFilter === g ? " on" : ""}`,
            onclick: () => {
              state.muscleFilter = state.muscleFilter === g ? null : g;
              render();
            },
          },
          [g],
        ),
      ),
    ),
    list,
    el("button", { class: "btn add-custom-ex", onclick: openCustomForm }, ["＋ 自訂動作"]),
    el("div", { class: "picker-foot" }, [
      el("button", { class: "btn btn-ghost", onclick: () => { state.screen = "home"; render(); } }, ["← 回首頁"]),
      // F29：直接從今日菜單結束訓練，不必先進 logger 才收工（與 logger「收工」同一動作）
      el("button", { class: "btn btn-danger", onclick: endWorkout }, ["結束訓練"]),
    ]),
    // F10：自訂動作懸浮視窗（overlay，蓋在整個選動作畫面上）
    ...(customFormOpen ? [pickerCustomModal()] : []),
  ]);
}

// ---------- logger ----------

function startRestTimer() {
  state.restStartedAt = Date.now();
  restAlerted = false;
  // F31：排定「休息結束」推播（切到別的 app 也收得到）；未開通知＝no-op
  if (state.exercise) scheduleRestPush(restHintFor(state.exercise.id));
  if (restTicker) clearInterval(restTicker);
  restTicker = setInterval(() => {
    const led = document.querySelector(".rest-led");
    if (!led) return;
    const remaining = restRemainingSeconds();
    if (remaining === null) return;
    led.querySelector(".digits").textContent = fmtRest(remaining);
    led.classList.toggle("over", remaining <= 0); // 與震動同門檻：到 0 那一刻就變色
    if (!restAlerted && remaining <= 0) {
      restAlerted = true;
      navigator.vibrate?.([200, 100, 200]); // iOS Safari 不支援——只有視覺提示
    }
  }, 1000);
}

function stopRestTimer() {
  if (restTicker) clearInterval(restTicker);
  restTicker = null;
  state.restStartedAt = null;
  cancelRestPush(); // F31：休息被使用者結束（繼續下一組/換動作/收工）→ 取消未觸發的推播
}

function cycleRestHint(exerciseId) {
  const picks = [60, 90, 120, 180];
  const current = restHintFor(exerciseId);
  if (!picks.includes(current)) picks.unshift(current); // 課表自訂值（如 100s）留在循環裡
  const next = picks[(picks.indexOf(current) + 1) % picks.length];
  state.restHintOverrides = { ...state.restHintOverrides, [exerciseId]: next };
  saveActiveWorkout();
  const remaining = restRemainingSeconds();
  if ((remaining ?? -1) > 0) restAlerted = false; // 目標調長回到未到點：重新武裝提醒
  // F31：休息進行中改秒數 → 依新剩餘時間重排推播，否則後端仍照舊秒數推（Codex P2）
  if (state.restStartedAt !== null) {
    if (remaining !== null && remaining > 0) scheduleRestPush(remaining);
    else cancelRestPush();
  }
}

function renderLogger() {
  const exercise = state.exercise;

  const logSet = async () => {
    if (state.submitting) return; // 防手機雙擊重複送出
    state.submitting = true;
    try {
      const payload = {
        client_uuid: crypto.randomUUID(),
        exercise_id: exercise.id,
        set_number: state.setNumber,
        weight_kg: state.weightKg,
        reps: state.reps,
        ...(state.rpe ? { rpe: state.rpe } : {}),
        // F15：rest_seconds 來自按「繼續下一組」凍結的值（第一組無、故不帶）
        ...(state.pendingRestSeconds != null ? { rest_seconds: state.pendingRestSeconds } : {}),
      };
      let saved;
      try {
        saved = await api.logSet(state.workoutId, payload);
      } catch (err) {
        if (!isOffline(err)) throw err;
        await enqueueSet(state.workoutId, payload); // 離線：入列緩衝，恢復連線自動補傳
        saved = payload; // 標示由 state.queueStatus 推導，不另存旗標
        await refreshQueueCounts();
      }
      // 到這裡才代表這組已保住（線上成功 or 離線入列成功）——此時才清凍結休息值；
      // 若上面丟錯（非離線錯誤或入列失敗），pendingRestSeconds 保留，重試的 payload 仍帶 rest_seconds
      state.pendingRestSeconds = null;
      state.doneSets.push(saved);
      state.setCounts[exercise.id] = state.setNumber;
      state.setNumber += 1;
      state.rpe = null;
      rememberDoneSets(); // F32：換動作後回到此動作可還原本次組
      saveActiveWorkout(); // setCounts/doneByExercise 持久化：重新整理後編號續接、組不丟
      startRestTimer(); // 招牌時刻：LED 亮起＝已記錄
    } finally {
      state.submitting = false;
    }
    render();
  };

  // F15：休息態按「繼續下一組」——凍結本次休息（含超時的絕對值）給下一組、停倒數、回就緒態
  const continueNext = () => {
    state.pendingRestSeconds = restElapsedSeconds();
    stopRestTimer();
    render();
  };

  const finish = () => {
    stopRestTimer();
    state.pendingRestSeconds = null; // 換動作：未用的凍結休息值不跨動作帶
    editDraft = null; // 離開 logger 清編輯草稿，否則殘留會讓下個動作的 scrollable 失效（F20/Codex P2）
    state.exercise = null;
    state.screen = "picker";
    render();
  };

  // ---------- F16 done-list 行內編輯/刪除 ----------
  const replaceInDone = (target, next) => {
    state.doneSets = state.doneSets.map((x) => (x === target ? next : x));
  };

  const deleteDoneSet = async (s) => {
    if (s.id != null) {
      try {
        await api.deleteSet(s.id); // 已同步：軟刪
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err; // 404＝已刪，視為成功（防連點重送）
      }
    } else {
      await removeQueued(s.client_uuid); // 未同步：移出佇列
      await refreshQueueCounts();
    }
    state.doneSets = state.doneSets.filter((x) => x !== s);
    // 同步本動作完成組數（否則課表選單仍顯示 3/3、menu-done 誤標）＋續接編號避開缺口（Codex P2）
    state.setCounts = { ...state.setCounts, [state.exercise.id]: state.doneSets.length };
    state.setNumber = state.doneSets.reduce((m, x) => Math.max(m, x.set_number), 0) + 1;
    rememberDoneSets(); // F32：刪組後鏡射同步，換動作後還原不含已刪組
    saveActiveWorkout();
    render();
  };

  const saveEditDoneSet = async (s) => {
    const { weight: w, reps: r, rpe } = editDraft; // 值由 steppers 就地維護，邊界已保證
    if (s.id != null) {
      const updated = await api.updateSet(s.id, {
        weight_kg: w,
        reps: r,
        ...(rpe ? { rpe } : {}),
        ...(s.rest_seconds != null ? { rest_seconds: s.rest_seconds } : {}),
      });
      replaceInDone(s, updated); // 原位 PATCH
    } else {
      const payload = { ...s, weight_kg: w, reps: r, rpe }; // 未同步：覆蓋佇列同 client_uuid
      await enqueueSet(state.workoutId, payload);
      replaceInDone(s, payload);
    }
    editDraft = null;
    rememberDoneSets(); // F32：編輯後鏡射同步，換動作後還原帶回修改值
    saveActiveWorkout();
    render();
  };

  const doneRow = (s) => {
    const key = setRowKey(s);
    if (editDraft && editDraft.key === key) {
      return el("div", { class: "done-row editing" }, [
        el("div", { class: "edit-head" }, [`編輯 #${s.set_number}`]),
        el("div", { class: "steppers" }, [
          stepper(exercise.is_bodyweight ? "負重 KG" : "KG", editDraft.weight, [
            ["−2.5", -2.5],
            ["+2.5", +2.5],
          ], (d) => { editDraft.weight = Math.max(0, Math.round((editDraft.weight + d) * 10) / 10); }, render),
          stepper("REPS", editDraft.reps, [
            ["−1", -1],
            ["+1", +1],
          ], (d) => { editDraft.reps = Math.max(1, editDraft.reps + d); }, render),
        ]),
        rpePicker(editDraft.rpe, (v) => { editDraft.rpe = v; }, render),
        el("div", { class: "edit-actions" }, [
          el("button", { class: "btn btn-primary sm save-edit", onclick: () => guard(() => saveEditDoneSet(s)) }, ["儲存"]),
          el("button", { class: "btn btn-ghost sm", onclick: () => { editDraft = null; render(); } }, ["取消"]),
        ]),
      ]);
    }
    const queued = state.queueStatus[s.client_uuid]; // pending | failed | undefined（已同步）
    const mark = queued === "pending" ? " ⏳" : queued === "failed" ? " ⚠" : "";
    return el("div", { class: `done-row${queued ? ` ${queued}` : ""}` }, [
      el("span", {}, [`#${s.set_number}${mark}`]),
      el("span", { class: "n" }, [
        `${s.weight_kg} kg × ${s.reps}${s.rpe ? `  @${s.rpe}` : ""}`,
      ]),
      el("button", {
        class: "btn icon-btn edit-set",
        onclick: () => {
          editDraft = { key, weight: s.weight_kg, reps: s.reps, rpe: s.rpe ?? null };
          render();
        },
      }, ["✎"]),
      el("button", {
        // F19：單擊即刪（軟刪／未同步移出佇列，資料非真的消失），不再兩段式確認
        class: "btn icon-btn del-set",
        onclick: () => guard(() => deleteDoneSet(s)),
      }, ["🗑"]),
    ]);
  };

  return el("section", { class: "screen logger" }, [
    el("header", { class: "exercise-head" }, [
      el("div", { class: "exercise-head-name" }, [
        el("h2", {}, [exerciseName(exercise)]),
        el("span", { class: "alias" }, [exerciseAlias(exercise)]),
      ]),
      // F38：練到一半查當前動作歷史；返回不丟進行中訓練
      el("button", {
        class: "btn detail-link logger-detail", "aria-label": "動作表現",
        onclick: () => openDetail(exercise, "logger"),
      }, ["📈"]),
    ]),
    el("div", { class: "last-hint" }, [state.lastHint || "第一次做這個動作"]),
    el("div", { class: "rest-hint-row" }, [
      el(
        "button",
        {
          class: "btn chip rest-hint",
          // 點擊循環 60→90→120→180（課表自訂值也留在循環內）；僅本次訓練，不寫回課表
          onclick: () => {
            cycleRestHint(exercise.id);
            render();
          },
        },
        [`⏱ 休息 ${restHintFor(exercise.id)}s`],
      ),
    ]),
    el(
      "div",
      {
        class: `rest-led${state.restStartedAt ? " on" : ""}${
          (restRemainingSeconds() ?? 1) <= 0 ? " over" : ""
        }`,
      },
      [
        el("span", { class: "label" }, ["REST"]),
        el("span", { class: "digits" }, [
          state.restStartedAt
            ? fmtRest(restRemainingSeconds())
            : fmtClock(restHintFor(exercise.id)),
        ]),
      ],
    ),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...syncStatusLine(),
    // F20：新→舊排序（最新在最上）；組數 > 2 時固定高度內部捲動（編輯中不限高，讓編輯表單完整可見）
    el("div", {
      class: `done-list${state.doneSets.length > 2 && !editDraft ? " scrollable" : ""}`,
    }, [...state.doneSets].reverse().map(doneRow)),
    el("div", { class: "steppers" }, [
      stepper(exercise.is_bodyweight ? "負重 KG" : "KG", state.weightKg, [
        ["−2.5", -2.5],
        ["+2.5", +2.5],
      ], (d) => { state.weightKg = Math.max(0, Math.round((state.weightKg + d) * 10) / 10); }, render),
      stepper("REPS", state.reps, [
        ["−1", -1],
        ["+1", +1],
      ], (d) => { state.reps = Math.max(1, state.reps + d); }, render),
    ]),
    rpePicker(state.rpe, (v) => { state.rpe = v; }, render),
    el(
      "button",
      {
        // F15 兩態切換：就緒態（未在休息）＝記錄；休息態＝繼續下一組（停倒數）
        class: `btn btn-primary log-btn${state.restStartedAt ? " resting" : ""}`,
        ...(state.submitting ? { disabled: "" } : {}),
        onclick: () => guard(state.restStartedAt ? continueNext : logSet),
      },
      [state.restStartedAt ? "繼續下一組" : "✓ 完成這組"],
    ),
    el("div", { class: "logger-foot" }, [
      el("button", { class: "btn", onclick: finish }, ["換動作"]),
      el("button", { class: "btn btn-danger", onclick: endWorkout }, ["收工"]),
    ]),
  ]);
}

// ---------- render ----------

function render() {
  const screens = {
    setup: renderSetup,
    home: renderHome,
    templateSelect: renderTemplateSelect,
    picker: renderPicker,
    logger: renderLogger,
    templates: () =>
      renderTemplates(
        render,
        () => {
          state.screen = "home";
          render();
        },
        guard,
      ),
    templateEdit: () => renderTemplateEdit(render, guard),
    calendar: () =>
      renderCalendar(
        render,
        () => {
          state.screen = "home";
          render();
        },
        guard,
      ),
    body: () =>
      renderBody(
        render,
        () => {
          state.screen = "home";
          render();
        },
        guard,
      ),
    exerciseDetail: () =>
      renderExerciseDetail(
        render,
        () => {
          state.screen = detailReturnScreen(); // F38：返回來源畫面（picker／logger），狀態不丟
          render();
        },
        guard,
      ),
  };
  root.replaceChildren(screens[state.screen]());
  syncWakeLock(); // fire-and-forget：logger 畫面取得、其他畫面釋放
}

// ---------- 啟動 ----------

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {
    /* SW 註冊失敗不影響線上使用 */
  });
  // F14 部署自動到位：新 SW 接管（controllerchange）就自動重載一次，開 app 即是新版。
  // 「首次安裝」的初次接管不重載（頁面本來就已是最新，多刷一次多餘）——但只跳過那一次；
  // 之後任何一次接管（部署新版）都要重載，否則首訪者若不關頁面，下次部署就更新不到。
  const hadController = Boolean(navigator.serviceWorker.controller);
  let skippedInitialClaim = false;
  let refreshing = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (refreshing) return; // 防 reload 循環：每次接管只 reload 一次
    if (!hadController && !skippedInitialClaim) {
      skippedInitialClaim = true; // 首裝的初次接管跳過，但下次部署的接管仍會重載
      return;
    }
    refreshing = true;
    // 若課表未儲存，beforeunload 提示可能讓使用者取消重載、頁面存活——復原 latch，
    // 否則之後的接管都被忽略、F14 自動更新永久失效（Codex P2）。reload 成功時頁面已卸載，此計時器不會執行
    setTimeout(() => { refreshing = false; }, 3000);
    location.reload();
  });
}
// 課表編輯有未儲存變更時，重整/關閉分頁/離開前跳瀏覽器原生警告，避免手滑丟失編輯。
// 只在編輯畫面且草稿與進場基準不同才攔截——其他畫面（記錄每組即時寫入、表單 POST 即存）無未存資料。
window.addEventListener("beforeunload", (e) => {
  saveTemplateDraft(); // F30：卸載前先存草稿（手機上 beforeunload 提示常不顯示，但這行仍會執行）
  if (hasUnsavedTemplate()) {
    e.preventDefault();
    e.returnValue = ""; // Chrome 需設 returnValue 才觸發原生確認框
  }
});
window.addEventListener("online", () => guard(syncQueue)); // 恢復連線：自動補傳佇列
document.addEventListener("visibilitychange", () => {
  syncWakeLock();
  if (document.hidden) saveTemplateDraft(); // F30：切背景/OS 準備殺分頁前存草稿（手機最可靠的存檔時機）
});

restoreActiveWorkout();
if (!getToken()) {
  state.screen = "setup";
  render();
} else {
  restoreTemplateDraft(); // F30：有未存的課表草稿就還原進編輯畫面（比 beforeunload 提示可靠）
  render();
  guard(loadExercises); // 預載動作庫，token 失效會導回 setup
  guard(syncQueue); // 開站補傳上次離線留下的佇列
}
