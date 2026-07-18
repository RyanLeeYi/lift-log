// 日曆 heatmap：CSS grid 月視圖、5 級深淺（依當月最大噸位分四檔）、點日看明細。

import { api } from "./api.js";
import { el } from "./dom.js";
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
  confirmDelSetId: null, // F16：兩段式刪除中的 set id
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
  cal.editSetId = null; // 換日/重載時清掉行內編輯與刪除確認的殘留態
  cal.confirmDelSetId = null;
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
  cal.confirmDelSetId = null;
  await refreshMonthAndDay();
  rerender();
}

async function saveEditSet(s, rerender) {
  const w = Math.round(Number(document.querySelector(".cal-edit-weight").value) * 10) / 10;
  const r = Math.trunc(Number(document.querySelector(".cal-edit-reps").value));
  const rpeRaw = document.querySelector(".cal-edit-rpe").value.trim();
  const rpe = rpeRaw ? Math.trunc(Number(rpeRaw)) : null;
  if (!(w >= 0) || !(r >= 1) || (rpe !== null && (rpe < 1 || rpe > 10))) {
    state.error = "重量/次數/RPE 不正確";
    rerender();
    return;
  }
  await api.updateSet(s.id, {
    weight_kg: w,
    reps: r,
    ...(rpe ? { rpe } : {}),
    ...(s.rest_seconds != null ? { rest_seconds: s.rest_seconds } : {}),
  });
  cal.editSetId = null;
  state.error = null;
  await refreshMonthAndDay();
  rerender();
}

function calSetRow(s, guard, rerender) {
  if (cal.editSetId === s.id) {
    return el("div", { class: "cal-detail-row editing" }, [
      el("input", {
        type: "number", class: "cal-edit-weight", step: "0.5",
        inputmode: "decimal", value: String(s.weight_kg),
      }),
      el("input", {
        type: "number", class: "cal-edit-reps", step: "1",
        inputmode: "numeric", value: String(s.reps),
      }),
      el("input", {
        type: "number", class: "cal-edit-rpe", step: "1", min: "1", max: "10",
        inputmode: "numeric", placeholder: "RPE", value: s.rpe ? String(s.rpe) : "",
      }),
      el("button", { class: "btn btn-primary sm", onclick: () => guard(() => saveEditSet(s, rerender)) }, ["儲存"]),
      el("button", { class: "btn btn-ghost sm", onclick: () => { cal.editSetId = null; state.error = null; rerender(); } }, ["取消"]),
    ]);
  }
  if (cal.confirmDelSetId === s.id) {
    return el("div", { class: "cal-detail-row confirm-del" }, [
      el("span", { class: "setno" }, [`#${s.set_number}`]),
      el("span", { class: "n" }, ["確定刪除？"]),
      el("button", { class: "btn btn-danger sm", onclick: () => guard(() => deleteSet(s, rerender)) }, ["刪除"]),
      el("button", { class: "btn btn-ghost sm", onclick: () => { cal.confirmDelSetId = null; rerender(); } }, ["取消"]),
    ]);
  }
  return el("div", { class: "cal-detail-row set" }, [
    el("span", { class: "setno" }, [`#${s.set_number}`]),
    el("span", { class: "n" }, [`${s.weight_kg}×${s.reps}${s.rpe ? `@${s.rpe}` : ""}`]),
    el("button", {
      class: "btn icon-btn edit-set",
      onclick: () => { cal.editSetId = s.id; cal.confirmDelSetId = null; state.error = null; rerender(); },
    }, ["✎"]),
    el("button", {
      class: "btn icon-btn del-set",
      onclick: () => { cal.confirmDelSetId = s.id; cal.editSetId = null; rerender(); },
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
