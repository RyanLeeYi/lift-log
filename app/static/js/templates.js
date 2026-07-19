// 課表管理：列表（templates）與編輯器（templateEdit）兩個畫面。
// 課表 = 名稱＋動作順序＋每動作預設組數；刪除採兩段確認（避免 modal）。

import { api } from "./api.js";
import { customExerciseModal } from "./custom-exercise.js";
import { el } from "./dom.js";
import { exerciseAlias, exerciseName, state } from "./state.js";

// R10 參考休息：快選值與範圍（與後端 schema 的 15–600 一致）
const REST_QUICK_PICKS = [60, 90, 120, 180];
const REST_HINT_MIN = 15;
const REST_HINT_MAX = 600;

// 本模組自己的畫面狀態（不進全域 state：離開課表畫面即重置無妨）
const tpl = {
  list: [], // GET /api/templates 結果
  editing: null, // {id|null, name, items: [{exercise_id, name_zh, name_en, muscle_group, is_bodyweight, default_sets}]}
  confirmDeleteId: null, // 兩段刪除：第一下記 id、第二下才真刪
  adding: false, // 編輯器內是否開啟「加動作」懸浮視窗
  addingCustom: false, // F25：加動作視窗內是否再開「自訂動作」建立視窗（疊在上層）
  selectedAdd: null, // F21：懸浮視窗內單選中的動作物件（null＝未選）
  muscleFilter: null, // F22：加動作視窗的部位篩選（null＝全部）
  itemsScrollTop: 0, // F21：編輯課表動作清單的捲動位置（整頁重繪後還原，避免每次編輯跳回頂端）
  exercises: [], // 加動作面板的動作庫清單
  searchQ: "",
  searchSeq: 0, // 搜尋回應排序：舊回應晚到不得覆蓋新結果
  busy: false, // 儲存/刪除進行中——防手機雙擊重複送出
};

export async function openTemplates() {
  tpl.list = await api.listTemplates();
  tpl.confirmDeleteId = null;
}

function startEditor(template) {
  tpl.editing = template
    ? {
        id: template.id,
        name: template.name,
        items: template.exercises.map((e) => ({ ...e })),
      }
    : { id: null, name: "", items: [] };
  tpl.adding = false;
  tpl.addingCustom = false;
  tpl.selectedAdd = null;
  tpl.muscleFilter = null;
  tpl.itemsScrollTop = 0;
  tpl.searchQ = "";
  tpl.confirmLeave = false;
  tpl.savedSnapshot = templateSnapshot(tpl.editing); // 進編輯當下的基準，用來判斷未儲存變更
}

// 課表草稿的可比較快照（只取會存進後端的欄位）——判斷「未儲存變更」用
function templateSnapshot(editing) {
  return JSON.stringify({
    name: (editing.name || "").trim(),
    items: editing.items.map((i) => ({
      exercise_id: i.exercise_id,
      default_sets: i.default_sets,
      rest_hint_seconds: i.rest_hint_seconds ?? null,
    })),
  });
}

// 目前是否在課表編輯畫面且草稿與進場基準不同（供 beforeunload 判斷是否攔截）
export function hasUnsavedTemplate() {
  return (
    state.screen === "templateEdit" &&
    tpl.editing != null &&
    templateSnapshot(tpl.editing) !== tpl.savedSnapshot
  );
}

// F30 自動存草稿＋還原：編輯課表未存的內容存 localStorage（比 sessionStorage 多撐「關閉分頁/被 OS 殺掉再開」），
// 開 app 時還原回編輯畫面；存檔成功或離開編輯即清。只有「被中斷」才會留著草稿。
const DRAFT_KEY = "liftlog.templateDraft";

export function saveTemplateDraft() {
  if (state.screen !== "templateEdit" || tpl.editing == null) return; // 非編輯畫面不動草稿
  if (!hasUnsavedTemplate()) {
    // 改動又改回基準＝沒有要恢復的內容，清掉先前存的草稿，否則重整會復活已撤銷的改動（Codex P2）
    clearTemplateDraft();
    return;
  }
  try {
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ editing: tpl.editing, savedSnapshot: tpl.savedSnapshot }),
    );
  } catch {
    /* localStorage 滿/停用：略過，草稿存不了不影響正常編輯 */
  }
}

function clearTemplateDraft() {
  try {
    localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* 略過 */
  }
}

// 開 app 時呼叫：有草稿就還原進編輯畫面並回 true；否則 false。壞資料一律清掉不擋啟動。
export function restoreTemplateDraft() {
  let raw;
  try {
    raw = localStorage.getItem(DRAFT_KEY);
  } catch {
    return false;
  }
  if (!raw) return false;
  try {
    const { editing, savedSnapshot } = JSON.parse(raw);
    // 嚴格驗證：欄位型別要能安全撐過 templateSnapshot/itemRow 首次 render，否則寧可丟棄也不要卡住啟動（Codex P2）
    const okItem = (it) =>
      it != null &&
      typeof it === "object" &&
      typeof it.exercise_id === "number" &&
      typeof it.default_sets === "number" &&
      typeof it.name_zh === "string" &&
      typeof it.name_en === "string" &&
      typeof it.muscle_group === "string";
    if (
      !editing ||
      typeof editing.name !== "string" ||
      !Array.isArray(editing.items) ||
      !editing.items.every(okItem)
    ) {
      throw new Error("bad draft");
    }
    tpl.editing = editing;
    tpl.savedSnapshot = savedSnapshot ?? templateSnapshot({ name: "", items: [] });
    tpl.adding = false;
    tpl.addingCustom = false;
    tpl.confirmLeave = false;
    tpl.selectedAdd = null;
    tpl.muscleFilter = null;
    tpl.itemsScrollTop = 0;
    tpl.searchQ = "";
    state.screen = "templateEdit";
    return true;
  } catch {
    clearTemplateDraft();
    return false;
  }
}

// ---------- 列表畫面 ----------

function templateRow(template, rerender, guard, openEditor) {
  const totalSets = template.exercises.reduce((sum, e) => sum + (e.default_sets || 0), 0);
  return el("div", { class: "tpl-row" }, [
    el("div", { class: "tpl-head" }, [
      el("span", { class: "tpl-name" }, [template.name]),
      // 份量摘要：動作數＋總組數，一眼看出這份課表的量（mono 對齊數字）
      el("span", { class: "tpl-meta" }, [`${template.exercises.length} 動作 · ${totalSets} 組`]),
    ]),
    // 動作以 tag 呈現（帶 ×組數），比「·」串接更好掃視
    el(
      "div",
      { class: "tpl-tags" },
      template.exercises.map((e) =>
        el("span", { class: "tpl-tag" }, [
          el("span", { class: "t-name" }, [exerciseName(e)]),
          el("span", { class: "t-sets" }, [`×${e.default_sets}`]),
        ]),
      ),
    ),
    el("div", { class: "tpl-actions" }, [
      el("button", { class: "btn chip", onclick: () => openEditor(template) }, ["編輯"]),
      // F28：點刪除跳確認視窗（顯示課表名稱），取代原本易誤觸的兩段式紅鍵
      el(
        "button",
        { class: "btn chip", onclick: () => { tpl.confirmDeleteId = template.id; rerender(); } },
        ["刪除"],
      ),
    ]),
  ]);
}

// F28：刪除課表的確認視窗（自訂 modal、顯示課表名稱，不用瀏覽器 confirm）
function deleteTemplateModal(rerender, guard) {
  const template = tpl.list.find((t) => t.id === tpl.confirmDeleteId);
  const close = () => { tpl.confirmDeleteId = null; rerender(); };
  if (!template) { tpl.confirmDeleteId = null; return el("div", { style: "display:none" }); }
  const doDelete = async () => {
    if (tpl.busy) return; // 防雙擊
    tpl.busy = true;
    try {
      await api.deleteTemplate(template.id);
      await openTemplates(); // 重載列表（同時清 confirmDeleteId）
    } finally {
      tpl.busy = false;
    }
    rerender();
  };
  return el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    [
      el("div", { class: "modal confirm-modal" }, [
        el("div", { class: "modal-head" }, ["刪除課表"]),
        el("p", { class: "confirm-text" }, [`確定刪除「${template.name}」？刪除後無法復原。`]),
        el("div", { class: "modal-actions" }, [
          el("button", { class: "btn btn-danger", onclick: () => guard(doDelete) }, ["刪除"]),
          el("button", { class: "btn btn-ghost", onclick: close }, ["取消"]),
        ]),
      ]),
    ],
  );
}

export function renderTemplates(rerender, goHome, guard) {
  const openEditor = (template) => {
    startEditor(template);
    state.screen = "templateEdit";
    rerender();
  };
  return el("section", { class: "screen templates" }, [
    el("header", { class: "topbar" }, [el("h1", {}, ["課表"])]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...(tpl.list.length === 0
      ? [el("p", { class: "tpl-empty" }, ["還沒有課表。建一份，開練就能一鍵帶出菜單。"])]
      : tpl.list.map((t) => templateRow(t, rerender, guard, openEditor))),
    el("button", { class: "btn btn-primary", onclick: () => openEditor(null) }, ["＋ 新課表"]),
    el("button", { class: "btn btn-ghost", onclick: goHome }, ["← 回首頁"]),
    // F28：刪除確認視窗
    ...(tpl.confirmDeleteId != null ? [deleteTemplateModal(rerender, guard)] : []),
  ]);
}

// ---------- 編輯器畫面 ----------

async function loadPickable(q) {
  const seq = ++tpl.searchSeq;
  const result = await api.searchExercises(q || "");
  if (seq !== tpl.searchSeq) return false; // 已有更新的查詢在跑：丟棄這批舊結果
  tpl.exercises = result;
  return true;
}

function itemRow(item, index, rerender) {
  const items = tpl.editing.items;
  const swap = (i, j) => {
    const next = [...items];
    [next[i], next[j]] = [next[j], next[i]];
    tpl.editing = { ...tpl.editing, items: next };
    rerender();
  };
  const setSets = (delta) => {
    const next = items.map((it, i) =>
      i === index ? { ...it, default_sets: Math.max(1, it.default_sets + delta) } : it,
    );
    tpl.editing = { ...tpl.editing, items: next };
    rerender();
  };
  const setRest = (value, { inPlace = false } = {}) => {
    const next = items.map((it, i) =>
      i === index ? { ...it, rest_hint_seconds: value } : it,
    );
    tpl.editing = { ...tpl.editing, items: next };
    if (inPlace) {
      // blur 觸發的 change 不整頁重繪：重繪會換掉「儲存課表」按鈕，吃掉同一下點擊
      row.replaceWith(itemRow(next[index], index, rerender));
    } else {
      rerender();
    }
  };
  const row = el("div", { class: "tpl-item" }, [
    // 名稱獨立一行（中英並列，別名不再被擠到換行）
    el("div", { class: "tpl-item-name" }, [
      el("span", { class: "n-zh" }, [exerciseName(item)]),
      el("span", { class: "n-alias" }, [exerciseAlias(item)]),
    ]),
    // 控制列：組數 stepper 靠左、排序/刪除靠右（刪除遠離 stepper，不易誤觸）
    el("div", { class: "tpl-item-controls" }, [
      el("div", { class: "tpl-item-sets" }, [
        el("button", { class: "btn chip", onclick: () => setSets(-1) }, ["−"]),
        el("span", { class: "n" }, [`${item.default_sets} 組`]),
        el("button", { class: "btn chip", onclick: () => setSets(+1) }, ["＋"]),
      ]),
      el("div", { class: "tpl-item-move" }, [
        el(
          "button",
          { class: "btn chip", ...(index === 0 ? { disabled: "" } : {}),
            onclick: () => swap(index, index - 1) },
          ["↑"],
        ),
        el(
          "button",
          { class: "btn chip", ...(index === items.length - 1 ? { disabled: "" } : {}),
            onclick: () => swap(index, index + 1) },
          ["↓"],
        ),
        el(
          "button",
          {
            class: "btn chip btn-danger tpl-item-del",
            onclick: () => {
              tpl.editing = { ...tpl.editing, items: items.filter((_, i) => i !== index) };
              rerender();
            },
          },
          ["✕"],
        ),
      ]),
    ]),
    el("div", { class: "tpl-item-rest" }, [
      el("span", { class: "sub" }, ["休息"]),
      ...REST_QUICK_PICKS.map((s) =>
        el(
          "button",
          {
            // 再點一次已選中的快選＝清除（回到未設定，訓練時用預設 60s）
            class: `btn chip${item.rest_hint_seconds === s ? " on" : ""}`,
            onclick: () => setRest(item.rest_hint_seconds === s ? null : s),
          },
          [`${s}s`],
        ),
      ),
      el("input", {
        type: "number",
        class: "rest-custom",
        min: String(REST_HINT_MIN),
        max: String(REST_HINT_MAX),
        placeholder: "自訂",
        value: item.rest_hint_seconds ?? "",
        // oninput：即時把值寫進草稿（不重繪、不 clamp），讓「未儲存判斷」涵蓋尚未失焦的輸入——
        // 否則 Chrome 先觸發 beforeunload 才 change，打了值直接重整會漏警告、值遺失（Codex P2）
        oninput: (e) => {
          const raw = e.target.value.trim();
          const n = Number.parseInt(raw, 10);
          const value = raw === "" || Number.isNaN(n) ? null : n;
          tpl.editing = {
            ...tpl.editing,
            items: tpl.editing.items.map((it, i) =>
              i === index ? { ...it, rest_hint_seconds: value } : it,
            ),
          };
        },
        // onchange（blur/enter）：最終 clamp 到合法範圍＋就地重繪（chip 高亮同步）
        onchange: (e) => {
          const raw = e.target.value.trim();
          const n = Number.parseInt(raw, 10);
          const value =
            raw === "" || Number.isNaN(n)
              ? null
              : Math.min(REST_HINT_MAX, Math.max(REST_HINT_MIN, n));
          setRest(value, { inPlace: true });
        },
      }),
    ]),
  ]);
  return row;
}

function addModal(rerender, guard) {
  // 已在課表裡的動作不再列出——一個動作只出現一次（進度以 exercise_id 計數）；F22 再依部位篩選
  const pickable = () => {
    const added = new Set(tpl.editing.items.map((it) => it.exercise_id));
    return tpl.exercises.filter(
      (e) =>
        !added.has(e.id) &&
        (tpl.muscleFilter === null || e.muscle_group === tpl.muscleFilter),
    );
  };
  const close = () => { tpl.adding = false; tpl.selectedAdd = null; rerender(); };
  const confirmAdd = () => {
    const ex = tpl.selectedAdd;
    if (!ex) return;
    tpl.editing = {
      ...tpl.editing,
      items: [
        ...tpl.editing.items,
        {
          exercise_id: ex.id,
          name_zh: ex.name_zh,
          name_en: ex.name_en,
          muscle_group: ex.muscle_group,
          is_bodyweight: ex.is_bodyweight,
          default_sets: 3,
          rest_hint_seconds: null,
        },
      ],
    };
    tpl.adding = false;
    tpl.selectedAdd = null;
    rerender();
  };
  const confirmBtn = el(
    "button",
    {
      class: "btn btn-primary modal-confirm",
      ...(tpl.selectedAdd == null ? { disabled: "" } : {}),
      onclick: () => guard(confirmAdd),
    },
    ["確定加入"],
  );
  const buttons = () =>
    pickable().map((exercise) =>
      el(
        "button",
        {
          // F21：點動作只「選中」（單選，再點別的換選中），按「確定加入」才真的加進課表。
          // 就地切換 .selected＋啟用確認鈕，不整頁重繪——否則長清單捲到下面選取後會跳回頂端（Codex P2）
          class: `btn exercise-item${tpl.selectedAdd?.id === exercise.id ? " selected" : ""}`,
          onclick: (e) => {
            tpl.selectedAdd = exercise;
            list.querySelectorAll(".exercise-item.selected").forEach((b) =>
              b.classList.remove("selected"),
            );
            e.currentTarget.classList.add("selected");
            confirmBtn.disabled = false;
          },
        },
        [
          el("span", {}, [exerciseName(exercise)]),
          el("span", { class: "sub" }, [exerciseAlias(exercise)]),
        ],
      ),
    );
  const list = el("div", { class: "exercise-list scrollable" }, buttons());
  // F22：部位篩選 chips（同 logger picker）——部位取自目前搜尋結果的動作庫
  const groups = [...new Set(tpl.exercises.map((e) => e.muscle_group))];
  const chips = el(
    "div",
    { class: "chips" },
    groups.map((g) =>
      el(
        "button",
        {
          class: `chip${tpl.muscleFilter === g ? " on" : ""}`,
          // 就地更新 chip 高亮＋清單，不整頁重繪——否則會與進行中的搜尋 callback（更新舊 list 節點）競態（Codex P2）
          onclick: () => {
            tpl.muscleFilter = tpl.muscleFilter === g ? null : g;
            if (tpl.selectedAdd && !pickable().some((x) => x.id === tpl.selectedAdd.id)) {
              tpl.selectedAdd = null;
              confirmBtn.disabled = true;
            }
            chips
              .querySelectorAll(".chip")
              .forEach((c) => c.classList.toggle("on", c.textContent === tpl.muscleFilter));
            list.replaceChildren(...buttons());
          },
        },
        [g],
      ),
    ),
  );
  return el(
    "div",
    // 點遮罩空白處＝取消（不加入）
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    [
      el("div", { class: "modal tpl-add-modal" }, [
        el("div", { class: "modal-head" }, ["加動作"]),
        el("input", {
          type: "search",
          placeholder: "搜尋動作（中英皆可）",
          value: tpl.searchQ,
          // 只更新清單、不整頁重繪——重繪會清空輸入框並讓鍵盤失焦
          oninput: (e) => {
            tpl.searchQ = e.target.value;
            guard(async () => {
              const fresh = await loadPickable(tpl.searchQ);
              if (!fresh) return;
              // 選取項目若被新搜尋結果排除，清掉選取並停用確認鈕（否則會加入畫面看不到的動作，Codex P2）
              if (tpl.selectedAdd && !pickable().some((x) => x.id === tpl.selectedAdd.id)) {
                tpl.selectedAdd = null;
                confirmBtn.disabled = true;
              }
              list.replaceChildren(...buttons());
            });
          },
        }),
        chips,
        list,
        // F25：找不到動作時就地建自訂動作（疊一層自訂視窗在加動作視窗上）
        el(
          "button",
          {
            class: "btn add-custom-ex",
            onclick: () => { tpl.addingCustom = true; rerender(); },
          },
          ["＋ 自訂動作"],
        ),
        el("div", { class: "modal-actions" }, [
          confirmBtn,
          el("button", { class: "btn btn-ghost modal-cancel", onclick: close }, ["取消"]),
        ]),
      ]),
    ],
  );
}

// F25：課表編輯內的自訂動作視窗（共用 customExerciseModal，疊在加動作視窗上）。
// 建立成功 → 重載可選清單、預選剛建立的動作（清部位/搜尋篩選確保它可見），回到加動作視窗。
function templateCustomModal(rerender, guard) {
  const groups = [...new Set(tpl.exercises.map((e) => e.muscle_group))];
  return customExerciseModal({
    groups,
    onCreated: (created) => {
      tpl.addingCustom = false;
      tpl.muscleFilter = null;
      tpl.searchQ = "";
      guard(async () => {
        try {
          await loadPickable(""); // 重載讓新動作進可選清單
        } catch {
          // 刷新失敗 fallback：動作已建立成功，用回傳值補進清單，避免清單沒它、重試撞重複（Codex P2，同 picker）
          tpl.exercises = [...tpl.exercises, created];
        }
        tpl.selectedAdd = created; // 預選剛建立的，使用者可直接「確定加入」
        rerender();
      });
    },
    onCancel: () => { tpl.addingCustom = false; rerender(); },
    onFatal: (err) => guard(() => Promise.reject(err)),
  });
}

export function renderTemplateEdit(rerender, guard) {
  const editing = tpl.editing;
  const nameInput = el("input", {
    type: "text",
    placeholder: "課表名稱（練腿日、上半身日⋯）",
    value: editing.name,
    oninput: (e) => {
      tpl.editing = { ...tpl.editing, name: e.target.value };
    },
  });

  const backToList = async () => {
    clearTemplateDraft(); // 離開編輯＝草稿階段結束（存檔成功也走這裡）
    await openTemplates();
    state.screen = "templates";
    rerender();
  };

  const save = async () => {
    if (tpl.busy) return; // 防雙擊：同一份課表不重複建立
    const payload = {
      name: tpl.editing.name.trim(),
      exercises: tpl.editing.items.map(({ exercise_id, default_sets, rest_hint_seconds }) => ({
        exercise_id,
        default_sets,
        rest_hint_seconds: rest_hint_seconds ?? null,
      })),
    };
    if (!payload.name) throw new Error("課表要有名稱");
    if (payload.exercises.length === 0) throw new Error("課表至少要有一個動作");
    tpl.busy = true;
    try {
      if (editing.id === null) await api.createTemplate(payload);
      else await api.updateTemplate(editing.id, payload);
    } finally {
      tpl.busy = false;
    }
    await backToList();
  };

  // 整頁重繪會重置捲動位置——存/還原 scrollTop，讓下方動作的組數/休息/排序可連續編輯不跳頂（Codex P2）
  // F21（2026-07-19 調整）：清單約 2 個動作高，超過 2 個才固定高度捲動
  const scrollable = editing.items.length > 2;
  const itemsNode = el(
    "div",
    {
      class: `tpl-items${scrollable ? " scrollable" : ""}`,
      onscroll: (e) => { tpl.itemsScrollTop = e.target.scrollTop; },
    },
    editing.items.map((item, i) => itemRow(item, i, rerender)),
  );
  if (scrollable) {
    requestAnimationFrame(() => { itemsNode.scrollTop = tpl.itemsScrollTop; });
  }

  saveTemplateDraft(); // F30：每次重繪（結構性變更後）自動存草稿；即時輸入的名稱/休息由 app.js 的 visibility/beforeunload 補存

  return el("section", { class: "screen template-edit" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, [editing.id === null ? "新課表" : "編輯課表"]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    nameInput,
    // F21：動作清單固定高度（約 1 個動作高）＋內部捲動，儲存/加動作按鈕不被推走
    itemsNode,
    el(
      "button",
      {
        class: "btn",
        onclick: () =>
          guard(async () => {
            tpl.searchQ = ""; // 每次開窗都從完整清單開始（免得上次無結果的搜尋字讓重開變空白）
            tpl.muscleFilter = null;
            await loadPickable("");
            tpl.selectedAdd = null;
            tpl.adding = true;
            rerender();
          }),
      },
      ["＋ 加動作"],
    ),
    el("button", { class: "btn btn-primary", onclick: () => guard(save) }, ["儲存課表"]),
    el(
      "button",
      {
        class: "btn btn-ghost",
        // F27：有未儲存變更時先跳自訂確認視窗（不用瀏覽器 confirm，沿用 app 慣例）
        onclick: () => {
          if (hasUnsavedTemplate()) { tpl.confirmLeave = true; rerender(); }
          else guard(backToList);
        },
      },
      ["← 課表列表"],
    ),
    // F21：加動作懸浮視窗（overlay，蓋在整個編輯畫面上）
    ...(tpl.adding ? [addModal(rerender, guard)] : []),
    // F25：自訂動作視窗疊在加動作視窗上層
    ...(tpl.addingCustom ? [templateCustomModal(rerender, guard)] : []),
    // F27：未儲存變更時點「← 課表列表」的離開確認視窗
    ...(tpl.confirmLeave ? [leaveConfirmModal(rerender, guard, backToList)] : []),
  ]);
}

// F27：離開課表編輯的未儲存確認視窗（自訂 modal，不用瀏覽器 confirm）
function leaveConfirmModal(rerender, guard, backToList) {
  const stay = () => { tpl.confirmLeave = false; rerender(); };
  return el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) stay(); } },
    [
      el("div", { class: "modal confirm-modal" }, [
        el("div", { class: "modal-head" }, ["有未儲存的變更"]),
        el("p", { class: "confirm-text" }, ["離開會捨棄這次編輯，確定嗎？"]),
        el("div", { class: "modal-actions" }, [
          el(
            "button",
            {
              class: "btn btn-danger",
              onclick: () => { tpl.confirmLeave = false; guard(backToList); },
            },
            ["捨棄並離開"],
          ),
          el("button", { class: "btn btn-ghost", onclick: stay }, ["繼續編輯"]),
        ]),
      ]),
    ],
  );
}
