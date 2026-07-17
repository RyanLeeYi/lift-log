// 體重體脂趨勢（F8）：輸入同日覆蓋（server 為 SSOT）、SVG 折線自繪（無圖表庫）。

import { api } from "./api.js";
import { el } from "./dom.js";
import { state } from "./state.js";

const CHART_POINTS = 90; // 折線最多畫最近 90 筆，再久的看數字就好

// 本模組自己的畫面狀態（不進全域 state：換畫面即重置無妨）
const body = {
  metrics: [], // 升冪 [{date, weight_kg, body_fat_pct}]
  savedFlash: null, // 剛存成功的訊息（一次性）
  saving: false, // 防雙擊：送出中不再受理（教訓同 logSet／課表儲存）
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
  const weightInput = el("input", {
    type: "number",
    inputmode: "decimal",
    step: "0.1",
    min: "30",
    max: "300",
    placeholder: "體重 kg",
    value: latest ? String(latest.weight_kg) : "",
  });
  const fatInput = el("input", {
    type: "number",
    inputmode: "decimal",
    step: "0.1",
    min: "1",
    max: "99",
    placeholder: "體脂 %（選填）",
    value: editingToday && latest.body_fat_pct != null ? String(latest.body_fat_pct) : "",
  });

  const save = async () => {
    if (body.saving) return;
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
    body.saving = true;
    try {
      await api.logBodyMetric(payload); // 不帶 date＝今天；同日重送為覆蓋
      body.metrics = await api.listBodyMetrics();
      body.savedFlash = "已記錄——同日重送會覆蓋更新";
    } finally {
      body.saving = false;
    }
    rerender();
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
      weightInput,
      fatInput,
      el(
        "button",
        {
          class: "btn btn-primary",
          ...(body.saving ? { disabled: "" } : {}),
          onclick: () => guard(save),
        },
        ["✓ 記錄今天"],
      ),
    ]),
    chartCard("體重", weightPoints, "kg"),
    chartCard("體脂", fatPoints, "%"),
    el("button", { class: "btn btn-ghost", onclick: goHome }, ["← 回首頁"]),
  ]);
}
