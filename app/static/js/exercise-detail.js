// F36 動作詳情頁：曲線（最重重量／最重總訓練量，時間窗＋自訂區間＋折點自動疏密）＋全期 PR。
// 歷來紀錄清單由 F37 補在 .ex-hist 容器。資料源＝GET /api/exercises/{id}/history（F35）。

import { api } from "./api.js";
import { el } from "./dom.js";
import { exerciseName, state } from "./state.js";

// 本模組畫面狀態（不進全域 state：換畫面即重置無妨）
const detail = {
  exerciseId: null,
  exercise: null, // {id, name_zh, name_en}
  returnScreen: "picker", // 返回目的地（F38 兩入口各自帶入）
  metric: "w", // w＝最重重量（不乘次數）／v＝最重總訓練量（單組 weight×reps）
  range: { kind: "preset", months: 3 }, // 或 {kind:"custom", from, to}
  data: { prs: { top_weight: null, top_set_volume: null }, sessions: [] },
  customOpen: false,
  customFrom: "",
  customTo: "",
  expandedMonths: new Set(), // F37：歷來紀錄展開中的月份 key（載入時預設近 3 個月）
  bodyweight: 0, // F37：自體重動作噸位用（取最新體重，同日曆的近似）
};

const PRESETS = [
  ["1M", 1], ["3M", 3], ["6M", 6], ["9M", 9], ["1Y", 12], ["2Y", 24], ["3Y", 36],
];
const METRICS = { w: { lbl: "最重重量", u: "kg" }, v: { lbl: "最重總訓練量", u: "kg" } };
const BUCKET_CAP = 16; // 折點上限；超過就聚合每週／每月最佳

function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function monthsAgo(d, n) {
  const total = d.getFullYear() * 12 + d.getMonth() - n;
  const y = Math.floor(total / 12);
  const m = ((total % 12) + 12) % 12; // 0-11
  const lastDay = new Date(y, m + 1, 0).getDate();
  return new Date(y, m, Math.min(d.getDate(), lastDay));
}

function datesFor(range) {
  if (range.kind === "custom") return { from: range.from, to: range.to };
  const today = new Date();
  return { from: iso(monthsAgo(today, range.months)), to: iso(today) };
}

let reqSeq = 0; // 過期回應丟棄：快速連點時只採用最新一次查詢

// 取新 range 的資料，成功才原子提交 range＋data；失敗（拋出）時 range/data 均不動，
// 由 guard 接住並以舊狀態重繪（新檔位不會殘留高亮、圖表不與檔位不一致）
async function loadRange(newRange) {
  const { from, to } = datesFor(newRange);
  const seq = ++reqSeq;
  const data = await api.exerciseHistory(detail.exerciseId, from, to);
  if (seq !== reqSeq) return; // 較舊但較慢的回應——丟棄
  detail.range = newRange;
  detail.data = data;
  // F37：每次換區間重設月份展開＝近 3 個月自動攤開
  const months = [...new Set(data.sessions.map((s) => s.date.slice(0, 7)))].sort().reverse();
  detail.expandedMonths = new Set(months.slice(0, 3));
}

export function detailReturnScreen() {
  return detail.returnScreen;
}

// 入口（F38 的 picker／logger 兩處呼叫）：載入預設 3M 資料
export async function openExerciseDetail(exercise, returnScreen = "picker") {
  detail.exerciseId = exercise.id;
  detail.exercise = exercise;
  detail.returnScreen = returnScreen;
  detail.metric = "w";
  detail.range = { kind: "preset", months: 3 };
  detail.data = { prs: { top_weight: null, top_set_volume: null }, sessions: [] }; // 清掉上一個動作殘留
  detail.customOpen = false;
  detail.customFrom = "";
  detail.customTo = "";
  // 自體重動作：取最新體重，噸位才不會把引體向上算成 0（同日曆 set_tonnage 的近似）
  detail.bodyweight = 0;
  if (exercise.is_bodyweight) {
    try {
      const metrics = await api.listBodyMetrics();
      if (metrics.length) {
        detail.bodyweight = metrics.reduce((a, b) => (b.date > a.date ? b : a)).weight_kg;
      }
    } catch {
      /* 拿不到體重就當 0，不擋開頁 */
    }
  }
  await loadRange({ kind: "preset", months: 3 });
}

// ---------- 指標與折點疏密 ----------

const metricOf = {
  w: (s) => Math.max(...s.sets.map((x) => x.weight_kg)),
  v: (s) => Math.max(...s.sets.map((x) => x.weight_kg * x.reps)),
};

function isoWeekKey(dateStr) {
  const d = new Date(dateStr);
  const jan1 = new Date(d.getFullYear(), 0, 1);
  return `${d.getFullYear()}-W${Math.floor((d - jan1) / 6048e5)}`;
}

// 回 {gran, pts:[{x,v}]}；折點數控制在 BUCKET_CAP 內
function buckets(sessions) {
  const fn = metricOf[detail.metric];
  const pts = sessions.map((s) => ({ x: s.date.slice(5), v: fn(s), date: s.date }));
  if (pts.length <= BUCKET_CAP) return { gran: "每次訓練", pts };
  for (const [keyer, label] of [[isoWeekKey, "每週最佳"], [(d) => d.slice(0, 7), "每月最佳"]]) {
    const map = new Map();
    for (const p of pts) {
      const k = keyer(p.date);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(p);
    }
    if (map.size <= BUCKET_CAP || label === "每月最佳") {
      const agg = [...map.values()].map((g) => ({
        x: g[g.length - 1].x,
        v: Math.max(...g.map((p) => p.v)),
      }));
      return { gran: label, pts: agg };
    }
  }
  return { gran: "每次訓練", pts };
}

// ---------- render ----------

// kind："weight"＝主值顯示重量；"volume"＝主值顯示 weight×reps（總訓練量）
function prCard(k, entry, kind) {
  let v = "—", u = "";
  if (entry) {
    if (kind === "weight") {
      v = String(entry.weight_kg);
      u = `kg × ${entry.reps}`;
    } else {
      v = String(entry.weight_kg * entry.reps);
      u = `kg (${entry.weight_kg}×${entry.reps})`;
    }
  }
  return el("div", { class: "pr" }, [
    el("div", { class: "k" }, [k]),
    el("div", { class: "v" }, [v]),
    el("div", { class: "u" }, [u]),
  ]);
}

function drawChart(container, capNow, capGran) {
  const { gran, pts } = buckets(detail.data.sessions);
  const d = pts.map((p) => p.v);
  const xs = pts.map((p) => p.x);
  capGran.textContent = pts.length ? `· ${gran} · ${pts.length} 點` : "";
  if (!d.length) {
    container.innerHTML = "";
    container.append(el("p", { class: "ex-chart-empty" }, ["這個區間內沒有紀錄"]));
    capNow.textContent = "—";
    return;
  }
  capNow.textContent = String(d[d.length - 1]);
  const W = 330, H = 150, padL = 30, padR = 8, padT = 12, padB = 22;
  const min = Math.min(...d), max = Math.max(...d);
  const lo = min - (max - min) * 0.15 - 0.1, hi = max + (max - min) * 0.15 + 0.1;
  const X = (i) => padL + (W - padL - padR) * (d.length < 2 ? 0.5 : i / (d.length - 1));
  const Y = (v) => padT + (H - padT - padB) * (1 - (v - lo) / (hi - lo));
  const P = d.map((v, i) => [X(i), Y(v)]);
  const line = P.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = line + ` L${X(d.length - 1).toFixed(1)} ${H - padB} L${padL} ${H - padB} Z`;
  let g = "";
  for (let k = 0; k <= 2; k++) {
    const v = lo + (hi - lo) * k / 2, y = Y(v);
    g += `<line class="ex-grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}"/>`;
    g += `<text class="ex-axis" x="0" y="${(y + 3).toFixed(1)}">${Math.round(v)}</text>`;
  }
  const idxs = [...new Set(d.length <= 5 ? d.map((_, i) => i) : [0, Math.floor(d.length / 2), d.length - 1])];
  let xl = "";
  for (const i of idxs) {
    xl += `<text class="ex-axis" x="${X(i).toFixed(1)}" y="${H - 6}" text-anchor="middle">${xs[i]}</text>`;
  }
  const idxBest = d.indexOf(Math.max(...d));
  const dots = P.map((p, i) =>
    `<circle class="ex-dot${i === idxBest ? " pr" : ""}" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${(i === d.length - 1 || i === idxBest) ? 4 : (d.length > 14 ? 1.8 : 2.5)}"/>`,
  ).join("");
  container.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}">` +
    `<defs><linearGradient id="exg" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0" stop-color="#ffb020" stop-opacity=".22"/>` +
    `<stop offset="1" stop-color="#ffb020" stop-opacity="0"/></linearGradient></defs>` +
    g + `<path class="ex-area" d="${area}"/><path class="ex-line" d="${line}"/>${dots}${xl}</svg>`;
}

// ---------- F37 歷來紀錄（綁時間窗、月份摺疊、內捲） ----------

function relTime(dateStr) {
  const days = Math.round((new Date(iso(new Date())) - new Date(dateStr)) / 864e5);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 30) return `${days} 天前`;
  if (days < 365) return `${Math.round(days / 30)} 個月前`;
  return `${Math.floor(days / 365)} 年前`;
}

function dayBlock(s) {
  // 自體重動作以（最新體重＋額外負重）計有效重量，同日曆 set_tonnage 規則
  const isBW = detail.exercise?.is_bodyweight;
  const bw = isBW && detail.bodyweight ? detail.bodyweight : 0;
  const tonnage = s.sets.reduce((a, x) => a + (x.weight_kg + bw) * x.reps, 0);
  const bestW = Math.max(...s.sets.map((x) => x.weight_kg)); // 當日最重那組掛 🏆（比額外負重）
  return el("div", { class: "ex-day" }, [
    el("div", { class: "d" }, [
      el("span", { class: "date" }, [s.date.slice(5)]),
      ...(relTime(s.date) ? [el("span", { class: "rel" }, [relTime(s.date)])] : []),
      el("span", { class: "vol" }, [`${Math.round(tonnage).toLocaleString()} kg`]),
    ]),
    el("div", { class: "sets" },
      s.sets.map((x) =>
        el("span", { class: `set${x.weight_kg === bestW ? " best" : ""}` }, [
          `${x.weight_kg}×${x.reps}`,
          ...(x.rpe ? [el("span", { class: "rpe" }, [`@${x.rpe}`])] : []),
        ]),
      ),
    ),
  ]);
}

function renderHistory(rerender) {
  const sessions = [...detail.data.sessions].reverse(); // 新→舊
  if (!sessions.length) return [el("p", { class: "ex-hist-empty" }, ["這個區間內沒有紀錄"])];
  const byMonth = new Map();
  for (const s of sessions) {
    const k = s.date.slice(0, 7);
    if (!byMonth.has(k)) byMonth.set(k, []);
    byMonth.get(k).push(s);
  }
  const nodes = [];
  for (const [k, ss] of byMonth) {
    const [y, m] = k.split("-");
    const open = detail.expandedMonths.has(k);
    const maxW = Math.max(...ss.flatMap((s) => s.sets.map((x) => x.weight_kg)));
    nodes.push(
      el("div", { class: `ex-month${open ? "" : " collapsed"}` }, [
        el("div", {
          class: "ex-mhead",
          onclick: () => {
            if (open) detail.expandedMonths.delete(k);
            else detail.expandedMonths.add(k);
            rerender();
          },
        }, [
          el("span", { class: "mo" }, [`${y} 年 ${+m} 月`]),
          el("span", { class: "sum" }, [`${ss.length} 次 · 最重 ${maxW} kg`]),
          el("span", { class: "car" }, [open ? "▾" : "▸"]),
        ]),
        ...(open ? [el("div", { class: "ex-mbody" }, ss.map(dayBlock))] : []),
      ]),
    );
  }
  return nodes;
}

export function renderExerciseDetail(rerender, goBack, guard) {
  const capNow = el("b", { class: "ex-now" }, ["—"]);
  const capGran = el("span", { class: "ex-gran" }, []);
  const capLbl = el("span", { class: "ex-lbl-text" }, [METRICS[detail.metric].lbl]);
  const chart = el("div", { class: "ex-chart" });
  const histBox = el("div", { class: "ex-hist" });

  // R2：切 metric 只重畫曲線＋cap＋按鈕高亮，不 rerender()（整頁重繪）、不打 API
  const mBtn = { w: null, v: null };
  function setMetric(m) {
    detail.metric = m;
    mBtn.w.classList.toggle("on", m === "w");
    mBtn.v.classList.toggle("on", m === "v");
    capLbl.textContent = METRICS[m].lbl;
    drawChart(chart, capNow, capGran);
  }
  const metricBtn = (m) => {
    const b = el("button", { class: detail.metric === m ? "on" : "", onclick: () => setMetric(m) }, [METRICS[m].lbl]);
    mBtn[m] = b;
    return b;
  };

  const presetBtn = ([label, months]) =>
    el("button", {
      class: detail.range.kind === "preset" && detail.range.months === months ? "on" : "",
      onclick: () =>
        guard(async () => {
          await loadRange({ kind: "preset", months }); // 成功才提交檔位＋資料
          detail.customOpen = false;
          rerender();
        }),
    }, [label]);

  const customChip = el("button", {
    class: detail.range.kind === "custom" ? "on" : "",
    onclick: () => { detail.customOpen = !detail.customOpen; rerender(); },
  }, ["自訂"]);

  const customPanel = detail.customOpen
    ? el("div", { class: "ex-custom" }, [
        el("input", {
          type: "date", class: "ex-date", value: detail.customFrom, max: iso(new Date()),
          oninput: (e) => { detail.customFrom = e.target.value; },
        }),
        el("span", { class: "ex-dash" }, ["→"]),
        el("input", {
          type: "date", class: "ex-date", value: detail.customTo, max: iso(new Date()),
          oninput: (e) => { detail.customTo = e.target.value; },
        }),
        el("button", {
          class: "btn btn-primary sm ex-custom-apply",
          onclick: () =>
            guard(async () => {
              const f = detail.customFrom, t = detail.customTo;
              // to 上限 today：max 屬性只是控制項提示，手打的未來日期仍要自己擋
              if (!f || !t || f > t || t > iso(new Date())) {
                state.error = "起訖日期不對（起要早於訖，且不能超過今天）";
                rerender();
                return;
              }
              state.error = null;
              await loadRange({ kind: "custom", from: f, to: t }); // 成功才提交檔位＋資料
              rerender();
            }),
        }, ["套用"]),
      ])
    : null;

  const node = el("section", { class: "screen exercise-detail" }, [
    el("header", { class: "topbar" }, [
      el("button", { class: "btn btn-ghost chip ex-back", onclick: goBack }, ["←"]),
      el("h1", {}, [exerciseName(detail.exercise)]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    el("div", { class: "ex-prs" }, [
      prCard("最重重量", detail.data.prs.top_weight, "weight"),
      prCard("最重總訓練量", detail.data.prs.top_set_volume, "volume"),
    ]),
    el("div", { class: "seg ex-metric" }, [metricBtn("w"), metricBtn("v")]),
    el("div", { class: "ex-range" }, [...PRESETS.map(presetBtn), customChip]),
    ...(customPanel ? [customPanel] : []),
    el("div", { class: "ex-chartcard" }, [
      el("div", { class: "ex-cap" }, [
        el("span", { class: "ex-lbl" }, [capLbl, capGran]),
        el("span", { class: "ex-nowwrap" }, [capNow, " ", el("span", { class: "ex-unit" }, ["kg"])]),
      ]),
      chart,
    ]),
    el("div", { class: "ex-hhead" }, [
      el("span", {}, ["歷來紀錄"]),
      el("span", { class: "cnt" }, [`此區間 ${detail.data.sessions.length} 次`]),
    ]),
    histBox, // F37 歷來紀錄清單
  ]);

  // 月份摺疊就地更新，保留內捲位置（全頁 rerender 會讓 scrollTop 歸零）
  function refreshHist() {
    const st = histBox.scrollTop;
    histBox.replaceChildren(...renderHistory(refreshHist));
    histBox.scrollTop = st;
  }
  histBox.replaceChildren(...renderHistory(refreshHist));

  drawChart(chart, capNow, capGran);
  return node;
}
