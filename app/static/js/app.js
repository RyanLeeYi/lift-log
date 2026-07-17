// lift-log 記錄頁：setup → home →（templateSelect）→ picker → logger，全部由 render() 重繪；
// 課表管理（templates / templateEdit）在 templates.js。

import { api, ApiError, getToken, setToken } from "./api.js";
import { openCalendar, renderCalendar } from "./calendar.js";
import { el } from "./dom.js";
import { openTemplates, renderTemplateEdit, renderTemplates } from "./templates.js";
import {
  clearActiveWorkout,
  exerciseAlias,
  exerciseName,
  getLang,
  restElapsedSeconds,
  restoreActiveWorkout,
  saveActiveWorkout,
  state,
  toggleLang,
} from "./state.js";

const root = document.getElementById("app");
let restTicker = null;

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
  const last = await api.lastSets(exercise.id);
  if (last.length > 0) {
    state.weightKg = last[0].weight_kg;
    state.reps = last[0].reps;
    state.lastHint = last.map((s) => `${s.weight_kg}×${s.reps}`).join("  ");
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
  if (restTicker) clearInterval(restTicker);
  restTicker = setInterval(() => {
    const digits = document.querySelector(".rest-led .digits");
    if (digits) digits.textContent = fmtClock(restElapsedSeconds());
  }, 1000);
}

function stopRestTimer() {
  if (restTicker) clearInterval(restTicker);
  restTicker = null;
  state.restStartedAt = null;
}

function stepper(name, value, steps, apply) {
  return el("div", { class: "stepper" }, [
    el("span", { class: "name" }, [name]),
    el("output", {}, [String(value)]),
    el("div", { class: "pair" },
      steps.map(([label, delta]) =>
        el("button", { class: "btn", onclick: () => { apply(delta); render(); } }, [label]),
      ),
    ),
  ]);
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
        ...(restElapsedSeconds() !== null ? { rest_seconds: restElapsedSeconds() } : {}),
      };
      const saved = await api.logSet(state.workoutId, payload);
      state.doneSets.push(saved);
      state.setCounts[exercise.id] = state.setNumber;
      state.setNumber += 1;
      state.rpe = null;
      startRestTimer(); // 招牌時刻：LED 亮起＝已記錄
    } finally {
      state.submitting = false;
    }
    render();
  };

  const finish = () => {
    stopRestTimer();
    state.exercise = null;
    state.screen = "picker";
    render();
  };

  const endWorkout = () => {
    stopRestTimer();
    clearActiveWorkout();
    state.setCounts = {};
    state.exercise = null;
    state.screen = "home";
    render();
  };

  return el("section", { class: "screen logger" }, [
    el("header", { class: "exercise-head" }, [
      el("h2", {}, [exerciseName(exercise)]),
      el("span", { class: "alias" }, [exerciseAlias(exercise)]),
    ]),
    el("div", { class: "last-hint" }, [
      state.lastHint ? `上次  ${state.lastHint}` : "第一次做這個動作",
    ]),
    el("div", { class: `rest-led${state.restStartedAt ? " on" : ""}` }, [
      el("span", { class: "label" }, ["REST"]),
      el("span", { class: "digits" }, [
        state.restStartedAt ? fmtClock(restElapsedSeconds()) : "00:00",
      ]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    el("div", { class: "done-list" },
      state.doneSets.map((s) =>
        el("div", { class: "done-row" }, [
          el("span", {}, [`#${s.set_number}`]),
          el("span", { class: "n" }, [
            `${s.weight_kg} kg × ${s.reps}${s.rpe ? `  @${s.rpe}` : ""}`,
          ]),
        ]),
      ),
    ),
    el("div", { class: "steppers" }, [
      stepper(exercise.is_bodyweight ? "負重 KG" : "KG", state.weightKg, [
        ["−2.5", -2.5],
        ["+2.5", +2.5],
      ], (d) => { state.weightKg = Math.max(0, Math.round((state.weightKg + d) * 10) / 10); }),
      stepper("REPS", state.reps, [
        ["−1", -1],
        ["+1", +1],
      ], (d) => { state.reps = Math.max(1, state.reps + d); }),
    ]),
    el("div", { class: "rpe-row" }, [
      el("span", { class: "name" }, ["RPE"]),
      el("div", { class: "rpe" },
        [6, 7, 8, 9, 10].map((n) =>
          el(
            "button",
            {
              class: state.rpe === n ? "on" : "",
              onclick: () => { state.rpe = state.rpe === n ? null : n; render(); },
            },
            [String(n)],
          ),
        ),
      ),
    ]),
    el(
      "button",
      {
        class: "btn btn-primary log-btn",
        ...(state.submitting ? { disabled: "" } : {}),
        onclick: () => guard(logSet),
      },
      ["✓ 完成這組"],
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
  };
  root.replaceChildren(screens[state.screen]());
}

// ---------- 啟動 ----------

restoreActiveWorkout();
if (!getToken()) {
  state.screen = "setup";
  render();
} else {
  render();
  guard(loadExercises); // 預載動作庫，token 失效會導回 setup
}
