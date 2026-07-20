// 體重體脂趨勢（F8）：輸入同日覆蓋（server 為 SSOT）、SVG 折線自繪（無圖表庫）。

import { api, ApiError } from "./api.js";
import { el } from "./dom.js";
import { state } from "./state.js";

const CHART_POINTS = 90; // 折線最多畫最近 90 筆，再久的看數字就好

// 本模組自己的畫面狀態（不進全域 state：換畫面即重置無妨）
const body = {
  metrics: [], // 升冪 [{date, weight_kg, body_fat_pct}]
  savedFlash: null, // 剛存成功的訊息（一次性）
  saving: false, // 防雙擊：送出中不再受理（教訓同 logSet／課表儲存）
  editDate: null, // F17：清單裡正在行內編輯的那天（date iso）
  editDraft: { weight: "", fat: "" }, // F17：編輯草稿——驗證/網路失敗重繪時不丟使用者輸入
  form: null, // F11：頂部補記表單草稿 {date,weight,fat}——失敗重繪時保留（尤其目標日期，
  // 否則重試會誤寫今天／覆蓋既有資料，Codex P1）；成功儲存後清空 → 回預設今天
};

function todayIso() {
  const now = new Date();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${m}-${d}`;
}

export async function openBody() {
  body.metrics = await api.listBodyMetrics();
  body.savedFlash = null;
  body.editDate = null;
  body.form = null; // 進畫面回到預設今天
}

function latestMetric() {
  return body.metrics[body.metrics.length - 1] || null;
}

function chartCard(title, points, unit) {
  // points 升冪 [{date, value}]；自縮放，min/max 與起訖日期標示
  if (points.length === 0) {
    return el("div", { class: "body-card" }, [
      el("div", { class: "body-card-head" }, [el("span", {}, [title])]),
      el("p", { class: "body-empty" }, ["還沒有紀錄"]),
    ]);
  }
  const w = 320;
  const h = 96;
  const pad = 6;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i) =>
    points.length === 1 ? w / 2 : pad + (i * (w - pad * 2)) / (points.length - 1);
  const y = (v) => h - pad - ((v - min) * (h - pad * 2)) / span;
  const pts = points
    .map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)
    .join(" ");
  const last = points[points.length - 1];

  const chart = el("div", { class: "body-chart" });
  // 只嵌自家 API 的數值（Number 化過），無使用者字串——innerHTML 安全
  chart.innerHTML =
    `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">` +
    `<polyline points="${pts}" fill="none" stroke="currentColor" ` +
    `stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>` +
    `<circle cx="${x(points.length - 1).toFixed(1)}" cy="${y(last.value).toFixed(1)}" ` +
    `r="3" fill="currentColor"/>` +
    "</svg>";

  return el("div", { class: "body-card" }, [
    el("div", { class: "body-card-head" }, [
      el("span", {}, [title]),
      el("span", { class: "n latest" }, [`${last.value} ${unit}`]),
    ]),
    chart,
    el("div", { class: "body-card-foot" }, [
      el("span", {}, [points[0].date]),
      el("span", { class: "n" }, [`${min}–${max} ${unit}`]),
      el("span", {}, [last.date]),
    ]),
  ]);
}

export function renderBody(rerender, goHome, guard) {
  const latest = latestMetric();
  // 體脂只在「今天已有紀錄」時回填（編輯今天的值）；回填舊日期的體脂會把
  // 沒量測的數字寫成今天的資料。體重是必填欄，帶上次值當快速記錄的起點無妨。
  const editingToday = latest !== null && latest.date === todayIso();
  // body.form 草稿 { date, weight, fat }：使用者一動表單就存、跨任何 rerender 保留（失敗重試、
  // 或編輯清單列觸發重繪都不丟目標日期與輸入——Codex P1＋P2a）。date=null 表示未明示選日
  // →提交時取「當下」todayIso()，跨午夜也正確落今天（Codex P2b）。成功儲存/進畫面時清空。
  const draft = body.form;
  const weightInput = el("input", {
    type: "number",
    inputmode: "decimal",
    step: "0.1",
    min: "30",
    max: "300",
    placeholder: "體重 kg",
    value: draft ? draft.weight : latest ? String(latest.weight_kg) : "",
  });
  const fatInput = el("input", {
    type: "number",
    inputmode: "decimal",
    step: "0.1",
    min: "1",
    max: "99",
    placeholder: "體脂 %（選填）",
    value: draft
      ? draft.fat
      : editingToday && latest.body_fat_pct != null
        ? String(latest.body_fat_pct)
        : "",
  });
  // F11：可補記過去日期。預設今天、max=今天擋未來（picker 選不到，save 再驗一次防手打）。
  const dateInput = el("input", {
    type: "date",
    class: "bm-date-picker",
    value: draft && draft.date ? draft.date : todayIso(),
    max: todayIso(),
  });
  // 任何輸入都同步進 body.form，跨重繪保留。weight/fat 改動不動 date（維持「未明示選日」語意）。
  const syncDraft = (patch) => {
    const cur = body.form || { date: null, weight: weightInput.value, fat: fatInput.value };
    body.form = { ...cur, ...patch };
  };
  weightInput.oninput = () => syncDraft({ weight: weightInput.value });
  fatInput.oninput = () => syncDraft({ fat: fatInput.value });
  // 換日期時把該日既有紀錄帶進表單——讓「同日覆蓋」看得見，避免把今天的值誤存到過去日。
  // 該日無紀錄：體重維持最近值當起點、體脂清空（不把舊體脂寫到沒量的日子，同 F8 原則）。明示選日→存 date。
  dateInput.onchange = () => {
    const existing = body.metrics.find((m) => m.date === dateInput.value);
    if (existing) {
      weightInput.value = String(existing.weight_kg);
      fatInput.value = existing.body_fat_pct != null ? String(existing.body_fat_pct) : "";
    } else {
      weightInput.value = latest ? String(latest.weight_kg) : "";
      fatInput.value = "";
    }
    body.form = { date: dateInput.value, weight: weightInput.value, fat: fatInput.value };
  };

  const save = async () => {
    if (body.saving) return;
    // 未明示選日→用提交當下 todayIso()（跨午夜正確落今天）；明示選過某日→用該日
    const explicitDate = body.form && body.form.date;
    const dateSel = explicitDate || todayIso();
    // 先快照當前輸入 → 任何驗證/網路失敗 guard 重繪時，目標日期與值都留著（Codex P1）
    body.form = { date: explicitDate || null, weight: weightInput.value, fat: fatInput.value };
    if (!dateSel) throw new Error("請選擇日期");
    if (dateSel > todayIso()) throw new Error("不能記錄未來日期"); // ISO 字串可字典序比較
    const weight = Number(weightInput.value);
    if (!Number.isFinite(weight) || weight < 30 || weight > 300) {
      throw new Error("體重要在 30–300 kg 之間");
    }
    const fatRaw = fatInput.value.trim();
    const payload = { weight_kg: weight };
    if (fatRaw !== "") {
      const fat = Number(fatRaw);
      if (!Number.isFinite(fat) || fat <= 0 || fat >= 100) {
        throw new Error("體脂要在 0–100% 之間");
      }
      payload.body_fat_pct = fat;
    }
    payload.date = dateSel; // F11：帶所選日期（預設今天）；同日重送為覆蓋
    body.saving = true;
    try {
      await api.logBodyMetric(payload);
      body.metrics = await api.listBodyMetrics();
      body.savedFlash =
        dateSel === todayIso()
          ? "已記錄——同日重送會覆蓋更新"
          : `已補記 ${dateSel}——同日重送會覆蓋更新`;
      body.form = null; // 成功後清草稿 → 下次回到預設今天
    } finally {
      body.saving = false;
    }
    rerender();
  };

  // ---------- F17 紀錄清單：每筆可編輯/單擊刪除 ----------
  const deleteMetric = async (m) => {
    try {
      await api.deleteBodyMetric(m.date); // 硬刪
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err; // 404＝已刪，視為成功（防連點）
    }
    body.metrics = await api.listBodyMetrics();
    rerender();
  };

  const saveEditMetric = async (m) => {
    const w = Number(body.editDraft.weight);
    if (!Number.isFinite(w) || w < 30 || w > 300) {
      state.error = "體重要在 30–300 kg 之間";
      rerender(); // 草稿在 body.editDraft，重繪不丟使用者輸入
      return;
    }
    const fatRaw = body.editDraft.fat.trim();
    const payload = { date: m.date, weight_kg: w }; // date 固定＝同日覆蓋（不可改日期）
    if (fatRaw !== "") {
      const fat = Number(fatRaw);
      if (!Number.isFinite(fat) || fat <= 0 || fat >= 100) {
        state.error = "體脂要在 0–100% 之間";
        rerender();
        return;
      }
      payload.body_fat_pct = fat;
    }
    await api.logBodyMetric(payload); // POST 同日覆蓋（既有 upsert）
    body.editDate = null;
    state.error = null;
    body.metrics = await api.listBodyMetrics();
    rerender();
  };

  const metricRow = (m) => {
    if (body.editDate === m.date) {
      // 輸入值以 body.editDraft 為準（oninput 靜默更新草稿，不 rerender 以免失焦）；
      // 驗證/網路失敗重繪時草稿仍在，使用者只需改錯的欄位（Codex P2）
      return el("div", { class: "bm-row editing" }, [
        el("span", { class: "bm-date" }, [m.date]),
        el("input", {
          type: "number", class: "bm-edit-weight", step: "0.1", inputmode: "decimal",
          placeholder: "kg", value: body.editDraft.weight,
          oninput: (e) => { body.editDraft.weight = e.target.value; },
        }),
        el("input", {
          type: "number", class: "bm-edit-fat", step: "0.1", inputmode: "decimal",
          placeholder: "體脂%", value: body.editDraft.fat,
          oninput: (e) => { body.editDraft.fat = e.target.value; },
        }),
        el("button", { class: "btn btn-primary sm", onclick: () => guard(() => saveEditMetric(m)) }, ["儲存"]),
        el("button", { class: "btn btn-ghost sm", onclick: () => { body.editDate = null; state.error = null; rerender(); } }, ["取消"]),
      ]);
    }
    return el("div", { class: "bm-row" }, [
      el("span", { class: "bm-date" }, [m.date]),
      el("span", { class: "bm-val" }, [
        `${m.weight_kg} kg${m.body_fat_pct != null ? `　${m.body_fat_pct}%` : ""}`,
      ]),
      el("button", {
        class: "btn icon-btn bm-edit",
        onclick: () => {
          body.editDate = m.date;
          body.editDraft = {
            weight: String(m.weight_kg),
            fat: m.body_fat_pct != null ? String(m.body_fat_pct) : "",
          };
          state.error = null;
          rerender();
        },
      }, ["✎"]),
      el("button", {
        // F17：單擊即刪（硬刪），跟 F19 範式一致、無兩段式確認
        class: "btn icon-btn bm-del",
        onclick: () => guard(() => deleteMetric(m)),
      }, ["🗑"]),
    ]);
  };

  // 兩序列各自先篩選再取最後 N 點——體脂記得稀疏時，先切再篩會丟掉仍屬最近的體脂點
  const weightPoints = body.metrics
    .map((m) => ({ date: m.date, value: m.weight_kg }))
    .slice(-CHART_POINTS);
  const fatPoints = body.metrics
    .filter((m) => m.body_fat_pct != null)
    .map((m) => ({ date: m.date, value: m.body_fat_pct }))
    .slice(-CHART_POINTS);

  return el("section", { class: "screen body" }, [
    el("header", { class: "topbar" }, [el("h1", {}, ["體重"])]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...(body.savedFlash ? [el("div", { class: "body-saved" }, [body.savedFlash])] : []),
    el("div", { class: "body-form" }, [
      el("label", { class: "bm-date-field" }, [
        el("span", { class: "bm-date-label" }, ["日期"]),
        dateInput,
      ]),
      weightInput,
      fatInput,
      el(
        "button",
        {
          class: "btn btn-primary",
          ...(body.saving ? { disabled: "" } : {}),
          onclick: () => guard(save),
        },
        ["✓ 記錄"],
      ),
    ]),
    chartCard("體重", weightPoints, "kg"),
    chartCard("體脂", fatPoints, "%"),
    ...(body.metrics.length > 0
      ? [
          // F33：紀錄清單收進卡片（與上方圖表卡一致），列間不再用帳本橫線
          el("div", { class: "body-card body-list" }, [
            el("div", { class: "body-list-head" }, ["紀錄"]),
            // 最新在上
            ...[...body.metrics].reverse().map(metricRow),
          ]),
        ]
      : []),
    el("button", { class: "btn btn-ghost", onclick: goHome }, ["← 回首頁"]),
  ]);
}
