// lift-log 記錄頁：setup → home →（templateSelect）→ picker → logger，全部由 render() 重繪；
// 課表管理（templates / templateEdit）在 templates.js。

import { api, ApiError, getToken, setToken } from "./api.js";
import { openBody, renderBody } from "./body.js";
import { openCalendar, renderCalendar } from "./calendar.js";
import { el, rpePicker, stepper } from "./dom.js";
import {
  discardFailed,
  enqueueSet,
  flushQueue,
  listQueued,
  queueCounts,
  removeQueued,
} from "./queue.js";
import { openTemplates, renderTemplateEdit, renderTemplates } from "./templates.js";
import {
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

async function syncQueue() {
  const before = state.queue;
  const synced = await flushQueue(api.logSet);
  // 補傳成功者把含 server id 的回應寫回 doneSets——否則使用者仍停在 logger 時，
  // 該筆缺 id 會被誤判未同步，之後在畫面上刪/改會打不到伺服器（Codex P1）
  if (synced.length > 0) {
    const byUuid = new Map(synced.map((x) => [x.client_uuid, x.saved]));
    state.doneSets = state.doneSets.map((s) => byUuid.get(s.client_uuid) ?? s);
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
              // 捨棄＝這些組沒進 server——從清單移除，不能讓它們看起來像已同步
              state.doneSets = state.doneSets.filter((s) => !discarded.has(s.client_uuid));
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

async function loadExercises(q) {
  pickerExercises = await api.searchExercises(q || "");
}

async function pickExercise(exercise) {
  state.exercise = exercise;
  state.rpe = null;
  state.doneSets = [];
  state.setNumber = (state.setCounts[exercise.id] || 0) + 1; // 回頭選同動作時接續編號
  let last = [];
  let offline = false;
  try {
    last = await api.lastSets(exercise.id);
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
  state.screen = "logger";
  render();
}

function exerciseButtons() {
  const shown = state.muscleFilter
    ? pickerExercises.filter((e) => e.muscle_group === state.muscleFilter)
    : pickerExercises;
  return shown.map((exercise) =>
    el(
      "button",
      { class: "btn exercise-item", onclick: () => guard(() => pickExercise(exercise)) },
      [
        el("span", {}, [exerciseName(exercise)]),
        el("span", { class: "sub" }, [exerciseAlias(exercise)]),
      ],
    ),
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
  const list = el("div", { class: "exercise-list" }, exerciseButtons());

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
    el("button", { class: "btn btn-ghost", onclick: () => { state.screen = "home"; render(); } }, ["← 回首頁"]),
  ]);
}

// ---------- logger ----------

function startRestTimer() {
  state.restStartedAt = Date.now();
  restAlerted = false;
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
}

function cycleRestHint(exerciseId) {
  const picks = [60, 90, 120, 180];
  const current = restHintFor(exerciseId);
  if (!picks.includes(current)) picks.unshift(current); // 課表自訂值（如 100s）留在循環裡
  const next = picks[(picks.indexOf(current) + 1) % picks.length];
  state.restHintOverrides = { ...state.restHintOverrides, [exerciseId]: next };
  saveActiveWorkout();
  if ((restRemainingSeconds() ?? -1) > 0) restAlerted = false; // 目標調長回到未到點：重新武裝提醒
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
      saveActiveWorkout(); // setCounts 持久化：重新整理後編號續接
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
    state.exercise = null;
    state.screen = "picker";
    render();
  };

  const endWorkout = () => {
    // 收工只清 client 狀態；佇列裡未同步的組之後仍會補傳進這個 workout（server 是 SSOT）
    stopRestTimer();
    state.pendingRestSeconds = null;
    clearActiveWorkout();
    state.setCounts = {};
    state.exercise = null;
    state.screen = "home";
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
      el("h2", {}, [exerciseName(exercise)]),
      el("span", { class: "alias" }, [exerciseAlias(exercise)]),
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
    location.reload();
  });
}
window.addEventListener("online", () => guard(syncQueue)); // 恢復連線：自動補傳佇列
// 切走再回來時系統會自動釋放 wake lock——回到可見就重新申請
document.addEventListener("visibilitychange", () => syncWakeLock());

restoreActiveWorkout();
if (!getToken()) {
  state.screen = "setup";
  render();
} else {
  render();
  guard(loadExercises); // 預載動作庫，token 失效會導回 setup
  guard(syncQueue); // 開站補傳上次離線留下的佇列
}
