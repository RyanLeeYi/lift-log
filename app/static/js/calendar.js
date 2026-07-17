// 日曆 heatmap：CSS grid 月視圖、5 級深淺（依當月最大噸位分四檔）、點日看明細。

import { api } from "./api.js";
import { exerciseName, getLang, state } from "./state.js";

// 本模組自己的畫面狀態（不進全域 state：換畫面即重置無妨）
const cal = {
  year: new Date().getFullYear(),
  month: new Date().getMonth() + 1, // 1-12
  days: {}, // {"YYYY-MM-DD": tonnage}
  selected: null, // "YYYY-MM-DD"
  detail: [], // [{workout, sets}]
  exerciseById: null, // 進日曆時載一次，點日不重抓
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
  const workouts = await api.listWorkouts(dateStr, dateStr);
  cal.detail = await Promise.all(
    workouts.map(async (w) => ({
      workout: w,
      sets: (await api.workoutDetail(w.id)).sets,
    })),
  );
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function detailRows() {
  if (!cal.selected) return [];
  if (cal.detail.length === 0) {
    return [el("p", { class: "cal-empty" }, [`${cal.selected}：休息日`])];
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
  ];
  for (const { sets } of cal.detail) {
    // 依動作分組顯示：深蹲 80×8 80×8 85×6
    const grouped = new Map();
    for (const s of sets) {
      if (!grouped.has(s.exercise_id)) grouped.set(s.exercise_id, []);
      grouped.get(s.exercise_id).push(s);
    }
    for (const [exerciseId, groupSets] of grouped) {
      const exercise = cal.exerciseById?.[exerciseId];
      rows.push(
        el("div", { class: "cal-detail-row" }, [
          el("span", {}, [exercise ? exerciseName(exercise) : `#${exerciseId}`]),
          el("span", { class: "n" }, [
            groupSets
              .map((s) => `${s.weight_kg}×${s.reps}${s.rpe ? `@${s.rpe}` : ""}`)
              .join("  "),
          ]),
        ]),
      );
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
    el("div", { class: "cal-detail" }, detailRows()),
    el("button", { class: "btn btn-ghost", onclick: goHome }, ["← 回首頁"]),
  ]);
}
