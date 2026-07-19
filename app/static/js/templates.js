// 課表管理：列表（templates）與編輯器（templateEdit）兩個畫面。
// 課表 = 名稱＋動作順序＋每動作預設組數；刪除採兩段確認（避免 modal）。

import { api } from "./api.js";
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
  tpl.selectedAdd = null;
  tpl.muscleFilter = null;
  tpl.itemsScrollTop = 0;
  tpl.searchQ = "";
}

// ---------- 列表畫面 ----------

function templateRow(template, rerender, guard, openEditor) {
  const confirming = tpl.confirmDeleteId === template.id;
  const remove = async () => {
    if (!confirming) {
      tpl.confirmDeleteId = template.id;
      rerender();
      return;
    }
    if (tpl.busy) return; // 防雙擊：第一發刪除完成前不再送
    tpl.busy = true;
    try {
      await api.deleteTemplate(template.id);
      await openTemplates();
    } finally {
      tpl.busy = false;
    }
    rerender();
  };
  return el("div", { class: "tpl-row" }, [
    el("div", { class: "tpl-info" }, [
      el("span", { class: "tpl-name" }, [template.name]),
      el("span", { class: "sub" }, [
        template.exercises.map((e) => exerciseName(e)).join(" · "),
      ]),
    ]),
    el("div", { class: "tpl-actions" }, [
      el("button", { class: "btn chip", onclick: () => openEditor(template) }, ["編輯"]),
      el(
        "button",
        { class: `btn chip${confirming ? " btn-danger" : ""}`, onclick: () => guard(remove) },
        [confirming ? "確認刪除" : "刪除"],
      ),
    ]),
  ]);
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
    el("div", { class: "tpl-item-name" }, [
      el("span", {}, [exerciseName(item)]),
      el("span", { class: "sub" }, [exerciseAlias(item)]),
    ]),
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
          class: "btn chip btn-danger",
          onclick: () => {
            tpl.editing = { ...tpl.editing, items: items.filter((_, i) => i !== index) };
            rerender();
          },
        },
        ["✕"],
      ),
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
        // onchange（blur/enter 才觸發）：oninput 會整頁重繪打斷輸入
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
        el("div", { class: "modal-actions" }, [
          confirmBtn,
          el("button", { class: "btn btn-ghost modal-cancel", onclick: close }, ["取消"]),
        ]),
      ]),
    ],
  );
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
  // F21（2026-07-19 調整）：清單約 3 個動作高，超過 3 個才固定高度捲動
  const scrollable = editing.items.length > 3;
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
    el("button", { class: "btn btn-ghost", onclick: () => guard(backToList) }, ["← 課表列表"]),
    // F21：加動作懸浮視窗（overlay，蓋在整個編輯畫面上）
    ...(tpl.adding ? [addModal(rerender, guard)] : []),
  ]);
}
