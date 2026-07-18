// 日曆 heatmap：CSS grid 月視圖、5 級深淺（依當月最大噸位分四檔）、點日看明細。

import { api } from "./api.js";
import { el, rpePicker, stepper } from "./dom.js";
import { exerciseName, getLang, state } from "./state.js";

// 本模組自己的畫面狀態（不進全域 state：換畫面即重置無妨）
const cal = {
  year: new Date().getFullYear(),
  month: new Date().getMonth() + 1, // 1-12
  days: {}, // {"YYYY-MM-DD": tonnage}
  selected: null, // "YYYY-MM-DD"
  detail: [], // [{workout, sets}]
  status: null, // 當日狀態 {energy, sleep_quality, note}（F9；沒記就是 null）
  exerciseById: null, // 進日曆時載一次，點日不重抓
  editSetId: null, // F16：日曆明細正在行內編輯的 set id
  editDraft: null, // {weight, reps, rpe} 編輯草稿（steppers 就地維護）
  selectMode: false, // F19：多選批次刪除模式
  selectedIds: [], // F19：多選模式下已勾選的 set id
};

async function loadMonth() {
  const data = await api.calendarStats(cal.year, cal.month);
  cal.days = data.days;
  cal.selected = null;
  cal.detail = [];
}

export async function openCalendar() {
  // 每次從首頁進來回到「今天」的月份
  cal.year = new Date().getFullYear();
  cal.month = new Date().getMonth() + 1;
  cal.exerciseById = Object.fromEntries(
    (await api.searchExercises("")).map((e) => [e.id, e]),
  );
  await loadMonth();
}

function level(tonnage, max) {
  // 0 = 沒練；1–4 依當月最大值等分
  if (!tonnage || max <= 0) return 0;
  return Math.min(4, Math.ceil((tonnage / max) * 4));
}

function monthLabel() {
  return `${cal.year}年${cal.month}月`;
}

function shiftMonth(delta) {
  let m = cal.month + delta;
  let y = cal.year;
  if (m < 1) { m = 12; y -= 1; }
  if (m > 12) { m = 1; y += 1; }
  cal.year = y;
  cal.month = m;
}

async function selectDay(dateStr) {
  cal.selected = dateStr;
  cal.editSetId = null; // 換日/重載時清掉行內編輯與多選的殘留態
  cal.editDraft = null;
  cal.selectMode = false;
  cal.selectedIds = [];
  const [workouts, statuses] = await Promise.all([
    api.listWorkouts(dateStr, dateStr),
    api.listDailyStatus(dateStr, dateStr),
  ]);
  cal.status = statuses[0] || null;
  cal.detail = await Promise.all(
    workouts.map(async (w) => ({
      workout: w,
      sets: (await api.workoutDetail(w.id)).sets,
    })),
  );
}

function statusRow() {
  if (!cal.status) return [];
  const s = cal.status;
  const parts = [`精力 ${s.energy}/5`];
  if (s.sleep_quality != null) parts.push(`睡眠 ${s.sleep_quality}/5`);
  return [
    el("div", { class: "cal-status" }, [
      el("span", {}, [parts.join("  ")]),
      ...(s.note ? [el("span", { class: "note" }, [s.note])] : []),
    ]),
  ];
}

// F16：刪/改後重載當月熱力圖（噸位會變）＋當日明細，且不丟目前選中的日
async function refreshMonthAndDay() {
  cal.days = (await api.calendarStats(cal.year, cal.month)).days;
  await selectDay(cal.selected);
}

async function deleteSet(s, rerender) {
  await api.deleteSet(s.id); // 日曆的組都來自 server，一律走軟刪 API（無離線佇列）
  await refreshMonthAndDay();
  rerender();
}

// F19：批次刪除已勾選的組——後端無批次端點，逐筆軟刪
async function batchDeleteSelected(rerender) {
  for (const id of cal.selectedIds) {
    await api.deleteSet(id);
  }
  cal.selectMode = false;
  cal.selectedIds = [];
  await refreshMonthAndDay();
  rerender();
}

async function saveEditSet(s, rerender) {
  const { weight: w, reps: r, rpe } = cal.editDraft; // 值由 steppers 就地維護，邊界已保證
  await api.updateSet(s.id, {
    weight_kg: w,
    reps: r,
    ...(rpe ? { rpe } : {}),
    ...(s.rest_seconds != null ? { rest_seconds: s.rest_seconds } : {}),
  });
  cal.editSetId = null;
  cal.editDraft = null;
  await refreshMonthAndDay();
  rerender();
}

function calSetRow(s, guard, rerender) {
  if (cal.editSetId === s.id) {
    const d = cal.editDraft;
    return el("div", { class: "cal-detail-row editing" }, [
      el("div", { class: "edit-head" }, [`編輯 #${s.set_number}`]),
      el("div", { class: "steppers" }, [
        stepper("KG", d.weight, [["−2.5", -2.5], ["+2.5", +2.5]],
          (delta) => { d.weight = Math.max(0, Math.round((d.weight + delta) * 10) / 10); }, rerender),
        stepper("REPS", d.reps, [["−1", -1], ["+1", +1]],
          (delta) => { d.reps = Math.max(1, d.reps + delta); }, rerender),
      ]),
      rpePicker(d.rpe, (v) => { d.rpe = v; }, rerender),
      el("div", { class: "edit-actions" }, [
        el("button", { class: "btn btn-primary sm", onclick: () => guard(() => saveEditSet(s, rerender)) }, ["儲存"]),
        el("button", { class: "btn btn-ghost sm", onclick: () => { cal.editSetId = null; cal.editDraft = null; rerender(); } }, ["取消"]),
      ]),
    ]);
  }
  if (cal.selectMode) {
    // F19 多選：整列可點切換勾選，隱藏編輯/刪除單擊鈕
    const checked = cal.selectedIds.includes(s.id);
    return el("div", {
      class: `cal-detail-row set selectable${checked ? " selected" : ""}`,
      onclick: () => {
        cal.selectedIds = checked
          ? cal.selectedIds.filter((x) => x !== s.id)
          : [...cal.selectedIds, s.id];
        rerender();
      },
    }, [
      el("span", { class: "check" }, [checked ? "☑" : "☐"]),
      el("span", { class: "setno" }, [`#${s.set_number}`]),
      el("span", { class: "n" }, [`${s.weight_kg}×${s.reps}${s.rpe ? `@${s.rpe}` : ""}`]),
    ]);
  }
  return el("div", { class: "cal-detail-row set" }, [
    el("span", { class: "setno" }, [`#${s.set_number}`]),
    el("span", { class: "n" }, [`${s.weight_kg}×${s.reps}${s.rpe ? `@${s.rpe}` : ""}`]),
    el("button", {
      class: "btn icon-btn edit-set",
      onclick: () => {
        cal.editSetId = s.id;
        cal.editDraft = { weight: s.weight_kg, reps: s.reps, rpe: s.rpe ?? null };
        rerender();
      },
    }, ["✎"]),
    el("button", {
      // F19：單擊即刪（軟刪），不再兩段式確認
      class: "btn icon-btn del-set",
      onclick: () => guard(() => deleteSet(s, rerender)),
    }, ["🗑"]),
  ]);
}

function detailRows(guard, rerender) {
  if (!cal.selected) return [];
  if (cal.detail.length === 0) {
    // 休息日也可能記了當日狀態（R9：不依附 workout）
    return [el("p", { class: "cal-empty" }, [`${cal.selected}：休息日`]), ...statusRow()];
  }
  const tonnage = cal.days[cal.selected];
  const rows = [
    el("div", { class: "cal-detail-head" }, [
      el("span", {}, [cal.selected]),
      el("span", { class: "n" }, [
        // 純自體重日噸位可為 0，仍要顯示
        tonnage !== undefined ? `噸位 ${Math.round(tonnage).toLocaleString()} kg` : "",
      ]),
    ]),
    ...statusRow(),
  ];
  // F19：有組才顯示「選取」入口（進多選批次刪除）
  const hasSets = cal.detail.some((d) => d.sets.length > 0);
  if (hasSets) {
    rows.push(
      el("div", { class: "cal-select-bar" }, [
        cal.selectMode
          ? el("button", {
              class: "btn btn-ghost sm cal-select-cancel",
              onclick: () => { cal.selectMode = false; cal.selectedIds = []; rerender(); },
            }, ["取消"])
          : el("button", {
              class: "btn btn-ghost sm cal-select-toggle",
              onclick: () => { cal.selectMode = true; cal.editSetId = null; rerender(); },
            }, ["選取"]),
      ]),
    );
  }
  for (const { sets } of cal.detail) {
    // F16：每個動作一個標題列，其下每組獨立一列可編輯/刪除
    const grouped = new Map();
    for (const s of sets) {
      if (!grouped.has(s.exercise_id)) grouped.set(s.exercise_id, []);
      grouped.get(s.exercise_id).push(s);
    }
    for (const [exerciseId, groupSets] of grouped) {
      const exercise = cal.exerciseById?.[exerciseId];
      rows.push(
        el("div", { class: "cal-detail-ex" }, [exercise ? exerciseName(exercise) : `#${exerciseId}`]),
      );
      for (const s of groupSets) rows.push(calSetRow(s, guard, rerender));
    }
  }
  if (cal.selectMode) {
    rows.push(
      el("div", { class: "cal-batch-bar" }, [
        el("button", {
          class: "btn btn-danger cal-batch-del",
          ...(cal.selectedIds.length === 0 ? { disabled: "" } : {}),
          onclick: () => guard(() => batchDeleteSelected(rerender)),
        }, [`刪除選取 (${cal.selectedIds.length})`]),
      ]),
    );
  }
  return rows;
}

export function renderCalendar(rerender, goHome, guard) {
  const first = new Date(cal.year, cal.month - 1, 1);
  const daysInMonth = new Date(cal.year, cal.month, 0).getDate();
  const leadBlanks = (first.getDay() + 6) % 7; // 週一起始
  const max = Math.max(0, ...Object.values(cal.days));

  const cells = [];
  const weekdays = getLang() === "zh"
    ? ["一", "二", "三", "四", "五", "六", "日"]
    : ["M", "T", "W", "T", "F", "S", "S"];
  for (const w of weekdays) cells.push(el("div", { class: "cal-wd" }, [w]));
  for (let i = 0; i < leadBlanks; i++) cells.push(el("div", {}));
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${cal.year}-${String(cal.month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const lv = level(cal.days[dateStr], max);
    cells.push(
      el(
        "button",
        {
          class: `cal-day lv${lv}${cal.selected === dateStr ? " sel" : ""}`,
          "aria-label": dateStr,
          onclick: () =>
            guard(async () => {
              await selectDay(dateStr);
              rerender();
            }),
        },
        [String(d)],
      ),
    );
  }

  const changeMonth = (delta) =>
    guard(async () => {
      shiftMonth(delta);
      await loadMonth();
      rerender();
    });

  return el("section", { class: "screen calendar" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, ["日曆"]),
      el("div", { class: "cal-nav" }, [
        el("button", { class: "btn btn-ghost chip", onclick: () => changeMonth(-1) }, ["◀"]),
        el("span", { class: "cal-month" }, [monthLabel()]),
        el("button", { class: "btn btn-ghost chip", onclick: () => changeMonth(+1) }, ["▶"]),
      ]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    el("div", { class: "cal-grid" }, cells),
    el("div", { class: "cal-legend" }, [
      el("span", {}, ["少"]),
      ...[0, 1, 2, 3, 4].map((lv) => el("span", { class: `cal-swatch lv${lv}` })),
      el("span", {}, ["多"]),
    ]),
    el("div", { class: "cal-detail" }, detailRows(guard, rerender)),
    el("button", { class: "btn btn-ghost", onclick: goHome }, ["← 回首頁"]),
  ]);
}
