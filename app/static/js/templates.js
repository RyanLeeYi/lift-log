// 課表管理：列表（templates）與編輯器（templateEdit）兩個畫面。
// 課表 = 名稱＋動作順序＋每動作預設組數；刪除採兩段確認（避免 modal）。

import { api } from "./api.js";
import { el } from "./dom.js";
import { exerciseAlias, exerciseName, state } from "./state.js";

// 本模組自己的畫面狀態（不進全域 state：離開課表畫面即重置無妨）
const tpl = {
  list: [], // GET /api/templates 結果
  editing: null, // {id|null, name, items: [{exercise_id, name_zh, name_en, muscle_group, is_bodyweight, default_sets}]}
  confirmDeleteId: null, // 兩段刪除：第一下記 id、第二下才真刪
  adding: false, // 編輯器內是否展開「加動作」面板
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
  return el("div", { class: "tpl-item" }, [
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
  ]);
}

function addPanel(rerender, guard) {
  // 已在課表裡的動作不再列出——一個動作只出現一次（進度以 exercise_id 計數）
  const pickable = () => {
    const added = new Set(tpl.editing.items.map((it) => it.exercise_id));
    return tpl.exercises.filter((e) => !added.has(e.id));
  };
  const buttons = () =>
    pickable().map((exercise) =>
      el(
        "button",
        {
          class: "btn exercise-item",
          onclick: () => {
            tpl.editing = {
              ...tpl.editing,
              items: [
                ...tpl.editing.items,
                {
                  exercise_id: exercise.id,
                  name_zh: exercise.name_zh,
                  name_en: exercise.name_en,
                  muscle_group: exercise.muscle_group,
                  is_bodyweight: exercise.is_bodyweight,
                  default_sets: 3,
                },
              ],
            };
            tpl.adding = false;
            rerender();
          },
        },
        [
          el("span", {}, [exerciseName(exercise)]),
          el("span", { class: "sub" }, [exerciseAlias(exercise)]),
        ],
      ),
    );
  const list = el("div", { class: "exercise-list" }, buttons());
  return el("div", { class: "tpl-add-panel" }, [
    el("input", {
      type: "search",
      placeholder: "搜尋動作（中英皆可）",
      value: tpl.searchQ,
      // 只更新清單、不整頁重繪——重繪會清空輸入框並讓鍵盤失焦
      oninput: (e) => {
        tpl.searchQ = e.target.value;
        guard(async () => {
          const fresh = await loadPickable(tpl.searchQ);
          if (fresh) list.replaceChildren(...buttons());
        });
      },
    }),
    list,
  ]);
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
      exercises: tpl.editing.items.map(({ exercise_id, default_sets }) => ({
        exercise_id,
        default_sets,
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

  return el("section", { class: "screen template-edit" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, [editing.id === null ? "新課表" : "編輯課表"]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    nameInput,
    el("div", { class: "tpl-items" }, editing.items.map((item, i) => itemRow(item, i, rerender))),
    ...(tpl.adding
      ? [addPanel(rerender, guard)]
      : [
          el(
            "button",
            {
              class: "btn",
              onclick: () =>
                guard(async () => {
                  await loadPickable(tpl.searchQ);
                  tpl.adding = true;
                  rerender();
                }),
            },
            ["＋ 加動作"],
          ),
        ]),
    el("button", { class: "btn btn-primary", onclick: () => guard(save) }, ["儲存課表"]),
    el("button", { class: "btn btn-ghost", onclick: () => guard(backToList) }, ["← 課表列表"]),
  ]);
}
