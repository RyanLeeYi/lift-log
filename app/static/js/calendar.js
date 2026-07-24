// 日曆 heatmap：CSS grid 月視圖、5 級深淺（依當月最大噸位分四檔）、點日看明細。

import { api, ApiError } from "./api.js";
import { el, rpePicker, stepper } from "./dom.js";
import { exerciseAlias, exerciseName, getLang, state } from "./state.js";

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
  statusEdit: false, // F18：當日狀態行內編輯中
  statusDraft: null, // F18：{energy, sleep_quality, note} 狀態編輯草稿
  expandedEx: new Set(), // F34：目前展開的 exercise_id（空＝全收合，切日/切月重置）
  addOpen: false, // F41：就地補記表單是否展開（切日重置）
  addExercise: null, // F41：補記表單已選要記的動作（null＝還在搜尋選動作）
  addSearch: "", // F41：動作搜尋字串
  addDraft: null, // F41：新組草稿 {weight, reps, rpe}（選定動作後建立）
};

// F41：本地「今天」ISO（與格子 dateStr 同格式、同時區）——未來日不給補記入口
function calToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

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

// keepExpanded：刪/改後重載當日用（F34 收合狀態要留著，否則刪一組整塊自己收起來）；
// 使用者切日/切月一律不帶＝重置為全收合
async function selectDay(dateStr, keepExpanded = false) {
  cal.selected = dateStr;
  cal.editSetId = null; // 換日/重載時清掉行內編輯與多選的殘留態
  cal.editDraft = null;
  cal.selectMode = false;
  cal.selectedIds = [];
  cal.statusEdit = false;
  cal.statusDraft = null;
  // F41：切日/切月一律收掉補記表單；keepExpanded（刪/改/補記後重載當日）則保留，
  // 讓「記完連續記下一組」不被自身刷新中斷（同 expandedEx 的保留邏輯）。
  if (!keepExpanded) {
    cal.expandedEx = new Set();
    cal.addOpen = false;
    cal.addExercise = null;
    cal.addSearch = "";
    cal.addDraft = null;
  }
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

// F18：當日狀態存檔（同日覆蓋）／硬刪
async function saveStatus(rerender) {
  const d = cal.statusDraft;
  const payload = { date: cal.selected, energy: d.energy };
  if (d.sleep_quality != null) payload.sleep_quality = d.sleep_quality;
  const note = (d.note || "").trim();
  if (note) payload.note = note;
  await api.logDailyStatus(payload); // POST 同日覆蓋（既有 upsert）
  cal.statusEdit = false;
  await refreshMonthAndDay(); // selectDay 會重載當日 status
  rerender();
}

async function deleteStatus(rerender) {
  try {
    await api.deleteDailyStatus(cal.selected); // 硬刪
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) throw err; // 404＝已刪，視為成功（防連點）
  }
  await refreshMonthAndDay();
  rerender();
}

// 1–5 量表按鈕；clearable 時再點同值＝清為 null
function scaleButtons(value, apply, rerender, clearable = false) {
  return el("div", { class: "scale-pick" },
    [1, 2, 3, 4, 5].map((n) =>
      el("button", {
        class: value === n ? "on" : "",
        onclick: () => { apply(clearable && value === n ? null : n); rerender(); },
      }, [String(n)]),
    ),
  );
}

function statusRow(guard, rerender) {
  if (!cal.status) return [];
  const s = cal.status;
  if (cal.statusEdit) {
    const d = cal.statusDraft;
    return [
      el("div", { class: "cal-status editing" }, [
        el("div", { class: "status-field" }, [
          el("span", { class: "lbl" }, ["精力"]),
          scaleButtons(d.energy, (v) => { if (v != null) d.energy = v; }, rerender), // 必填不可清
        ]),
        el("div", { class: "status-field" }, [
          el("span", { class: "lbl" }, ["睡眠"]),
          scaleButtons(d.sleep_quality, (v) => { d.sleep_quality = v; }, rerender, true),
        ]),
        el("input", {
          class: "status-note", placeholder: "備註（選填）", value: d.note || "",
          oninput: (e) => { d.note = e.target.value; },
        }),
        el("div", { class: "edit-actions" }, [
          el("button", { class: "btn btn-primary sm", onclick: () => guard(() => saveStatus(rerender)) }, ["儲存"]),
          el("button", { class: "btn btn-ghost sm", onclick: () => { cal.statusEdit = false; rerender(); } }, ["取消"]),
        ]),
      ]),
    ];
  }
  const parts = [`精力 ${s.energy}/5`];
  if (s.sleep_quality != null) parts.push(`睡眠 ${s.sleep_quality}/5`);
  return [
    el("div", { class: "cal-status" }, [
      el("span", { class: "txt" }, [parts.join("  ")]),
      ...(s.note ? [el("span", { class: "note" }, [s.note])] : []),
      el("button", {
        class: "btn icon-btn status-edit",
        onclick: () => {
          cal.statusEdit = true;
          cal.statusDraft = { energy: s.energy, sleep_quality: s.sleep_quality, note: s.note };
          rerender();
        },
      }, ["✎"]),
      el("button", {
        // F18：單擊即刪（硬刪），無兩段式確認
        class: "btn icon-btn status-del",
        onclick: () => guard(() => deleteStatus(rerender)),
      }, ["🗑"]),
    ]),
  ];
}

// F16：刪/改後重載當月熱力圖（噸位會變）＋當日明細，且不丟目前選中的日
async function refreshMonthAndDay() {
  cal.days = (await api.calendarStats(cal.year, cal.month)).days;
  // 寫入傳輸中使用者可能已切月（loadMonth 把 selected 設 null）——別讓 selectDay(null)
  // 打出 start=null&end=null 的 400；沒選日就只更新熱力圖（Codex P2）
  if (cal.selected) await selectDay(cal.selected, true);
}

async function deleteSet(s, rerender) {
  try {
    await api.deleteSet(s.id); // 日曆的組都來自 server，一律走軟刪 API（無離線佇列）
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) throw err; // 404＝已刪，視為成功（防連點）
  }
  await refreshMonthAndDay();
  rerender();
}

// F19：批次刪除已勾選的組——後端無批次端點，逐筆軟刪
async function batchDeleteSelected(rerender) {
  try {
    for (const id of cal.selectedIds) {
      try {
        await api.deleteSet(id);
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err; // 已刪的跳過；真錯誤上拋
      }
    }
  } finally {
    // 不論中途成功幾筆或遇錯，都以 server 現況重載——避免畫面與伺服器不一致
    cal.selectMode = false;
    cal.selectedIds = [];
    await refreshMonthAndDay();
    rerender();
  }
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
        cal.editDraft = { weight: s.weight_kg, reps: s.reps, rpe: s.rpe ?? 6 };
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

// F34：收合摘要用的「最重組」——weight_kg 最大者，平手取 reps 多者
function topSet(sets) {
  return sets.reduce((a, b) =>
    b.weight_kg > a.weight_kg || (b.weight_kg === a.weight_kg && b.reps > a.reps) ? b : a,
  );
}

// F41：就地補記——送一組到「選中日」的 workout（該日無則以選中日新建），全程不碰 state.workoutId。
async function addSet(rerender) {
  const d = cal.addDraft;
  const ex = cal.addExercise;
  // 目標 workout：該日已有就附加、沒有就以選中日新建（不影響今天進行中的 workout）
  let workoutId = cal.detail[0]?.workout.id;
  if (workoutId == null) {
    workoutId = (await api.createWorkout({ date: cal.selected })).id;
  }
  // set_number＝該動作在此 workout 既有未軟刪組數＋1（cal.detail 只含未軟刪組）
  const existing = cal.detail
    .filter((x) => x.workout.id === workoutId)
    .flatMap((x) => x.sets)
    .filter((s) => s.exercise_id === ex.id).length;
  await api.logSet(workoutId, {
    client_uuid: crypto.randomUUID(),
    exercise_id: ex.id,
    set_number: existing + 1,
    weight_kg: d.weight,
    reps: d.reps,
    rpe: d.rpe,
  });
  // 量測值保留當起點、累度軸回預設輕鬆；動作保留供連續記下一組。刷新熱力圖＋當日明細（keepExpanded）。
  cal.addDraft = { weight: d.weight, reps: d.reps, rpe: 6 };
  await refreshMonthAndDay();
  rerender();
}

// F41：補記入口與表單。未來日不給入口；選中日今天或過去才顯示。
function addBlock(guard, rerender) {
  if (!cal.selected || cal.selectMode) return []; // 多選批次刪除模式不夾雜新增
  if (cal.selected > calToday()) return []; // 未來日期不可補記
  if (!cal.addOpen) {
    return [
      el("button", {
        class: "btn cal-add-toggle",
        onclick: () => { cal.addOpen = true; rerender(); },
      }, ["＋ 新增動作"]),
    ];
  }
  if (!cal.addExercise) {
    // 搜尋選動作：清單就地 replaceChildren 更新，不呼叫 rerender——否則每打一字整頁重繪、輸入框失焦
    const listBox = el("div", { class: "exercise-list cal-add-list" }, []);
    const paintList = () => {
      const q = cal.addSearch.trim().toLowerCase();
      const all = Object.values(cal.exerciseById || {});
      const shown = (q
        ? all.filter((e) =>
            (e.name_zh || "").toLowerCase().includes(q) || (e.name_en || "").toLowerCase().includes(q))
        : all).slice(0, 30);
      listBox.replaceChildren(...shown.map((exx) =>
        el("button", {
          class: "btn exercise-item",
          onclick: () => {
            cal.addExercise = exx;
            cal.addDraft = { weight: 20, reps: 8, rpe: 6 };
            rerender();
          },
        }, [el("span", {}, [exerciseName(exx)]), el("span", { class: "sub" }, [exerciseAlias(exx)])])));
    };
    const search = el("input", {
      class: "cal-add-search", placeholder: "搜尋動作…", value: cal.addSearch,
      oninput: (e) => { cal.addSearch = e.target.value; paintList(); },
    });
    paintList();
    return [
      el("div", { class: "cal-add" }, [
        el("div", { class: "cal-add-head" }, [
          el("span", {}, ["新增動作"]),
          el("button", {
            class: "btn btn-ghost sm",
            onclick: () => { cal.addOpen = false; cal.addSearch = ""; rerender(); },
          }, ["取消"]),
        ]),
        search,
        listBox,
      ]),
    ];
  }
  // 已選動作：steppers ＋ 累度軸 ＋ 記這組（可連續記）
  const d = cal.addDraft;
  return [
    el("div", { class: "cal-add recording" }, [
      el("div", { class: "cal-add-head" }, [
        el("span", { class: "ex-name" }, [exerciseName(cal.addExercise)]),
        el("button", {
          class: "btn btn-ghost sm",
          onclick: () => { cal.addExercise = null; cal.addDraft = null; rerender(); },
        }, ["換動作"]),
      ]),
      el("div", { class: "steppers" }, [
        stepper(cal.addExercise.is_bodyweight ? "負重 KG" : "KG", d.weight,
          [["−2.5", -2.5], ["+2.5", +2.5]],
          (delta) => { d.weight = Math.max(0, Math.round((d.weight + delta) * 10) / 10); }, rerender),
        stepper("REPS", d.reps, [["−1", -1], ["+1", +1]],
          (delta) => { d.reps = Math.max(1, d.reps + delta); }, rerender),
      ]),
      rpePicker(d.rpe, (v) => { d.rpe = v; }, rerender),
      el("div", { class: "cal-add-actions" }, [
        el("button", { class: "btn btn-primary cal-add-log", onclick: () => guard(() => addSet(rerender)) }, ["記這組"]),
        el("button", {
          class: "btn btn-ghost sm cal-add-done",
          onclick: () => {
            cal.addOpen = false; cal.addExercise = null; cal.addDraft = null; cal.addSearch = "";
            rerender();
          },
        }, ["完成"]),
      ]),
    ]),
  ];
}

function detailRows(guard, rerender) {
  if (!cal.selected) return [];
  if (cal.detail.length === 0) {
    // 休息日也可能記了當日狀態（R9：不依附 workout）；F41：休息日也能就地補記
    return [
      el("p", { class: "cal-empty" }, [`${cal.selected}：休息日`]),
      ...statusRow(guard, rerender),
      ...addBlock(guard, rerender),
    ];
  }
  const tonnage = cal.days[cal.selected];
  // F19：有組才顯示「選取」入口（進多選批次刪除）
  // F34：入口從獨立一列的 .cal-select-bar 收進 head 右側，不再獨占一列
  const hasSets = cal.detail.some((d) => d.sets.length > 0);
  const rows = [
    el("div", { class: "cal-detail-head" }, [
      el("span", {}, [cal.selected]),
      el("span", { class: "n" }, [
        // 純自體重日噸位可為 0，仍要顯示
        tonnage !== undefined ? `噸位 ${Math.round(tonnage).toLocaleString()} kg` : "",
      ]),
      ...(hasSets
        ? [
            cal.selectMode
              ? el("button", {
                  class: "btn btn-ghost sm cal-select-cancel",
                  onclick: () => { cal.selectMode = false; cal.selectedIds = []; rerender(); },
                }, ["取消"])
              : el("button", {
                  class: "btn btn-ghost sm cal-select-toggle",
                  onclick: () => { cal.selectMode = true; cal.editSetId = null; rerender(); },
                }, ["☑ 選取"]),
          ]
        : []),
    ]),
    ...statusRow(guard, rerender),
  ];
  // F16：每個動作一個標題列，其下每組獨立一列可編輯/刪除
  // F33（Codex P2）：跨當日所有 workouts 先彙整同動作的組，再一個動作一個區塊——
  // 否則同日多 workout 含相同動作會產生多個同名區塊，違反「一個動作一個視覺區塊」
  const grouped = new Map();
  for (const { sets } of cal.detail) {
    for (const s of sets) {
      if (!grouped.has(s.exercise_id)) grouped.set(s.exercise_id, []);
      grouped.get(s.exercise_id).push(s);
    }
  }
  for (const [exerciseId, groupSets] of grouped) {
    const exercise = cal.exerciseById?.[exerciseId];
    // F34：選取模式強制展開（否則無組可勾），但不動 expandedEx——退出多選自然恢復先前收合狀態
    const showSets = cal.selectMode || cal.expandedEx.has(exerciseId);
    const top = topSet(groupSets);
    // F33：動作標頭＋其組收進一個琥珀脊區塊（取代舊的帳本橫線分隔）
    rows.push(
      el("div", { class: `cal-ex-block${showSets ? " expanded" : ""}` }, [
        el("div", {
          class: "cal-detail-ex",
          // 選取模式下標頭不可點：畫面已強制展開，點了只會偷改看不見的收合狀態
          ...(cal.selectMode ? {} : {
            onclick: () => {
              if (showSets) cal.expandedEx.delete(exerciseId);
              else cal.expandedEx.add(exerciseId);
              rerender();
            },
          }),
        }, [
          el("span", { class: "ex-name" }, [exercise ? exerciseName(exercise) : `#${exerciseId}`]),
          el("span", { class: "ex-sum" }, [
            `${groupSets.length}組 · 最重 ${top.weight_kg}×${top.reps}`,
          ]),
          el("span", { class: "ex-caret" }, [showSets ? "▾" : "▸"]),
        ]),
        ...(showSets ? groupSets.map((s) => calSetRow(s, guard, rerender)) : []),
      ]),
    );
  }
  if (cal.selectMode) {
    rows.push(
      el("div", { class: "cal-batch-bar" }, [
        el("button", {
          // F34：批次刪除條改琥珀填色（btn-primary），停用態靠 :disabled 淡化
          class: "btn btn-primary cal-batch-del",
          ...(cal.selectedIds.length === 0 ? { disabled: "" } : {}),
          onclick: () => guard(() => batchDeleteSelected(rerender)),
        }, [`刪除選取 (${cal.selectedIds.length})`]),
      ]),
    );
  }
  rows.push(...addBlock(guard, rerender)); // F41：補記入口（未來日/多選模式自動不顯示）
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
