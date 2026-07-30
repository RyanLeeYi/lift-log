// 體重體脂趨勢（F8）：輸入同日覆蓋（server 為 SSOT）、SVG 折線自繪（無圖表庫）。

import { api, ApiError } from "./api.js";
import { el } from "./dom.js";
import { icon } from "./icons.js";
import {
  PRESETS,
  iso as isoOf,
  longestAvailable,
  monthsAgo,
  presetAvailable as presetUsable,
  startOfPreset,
  todayIso,
} from "./range.js";
import { state } from "./state.js";

// 折線最多畫的點數上限（保險，避免極長區間畫出上千個點）。**刻意不做聚合抽樣**：
// 體重是天天量的連續數列，取週/月最佳會抹掉短期波動，而波動正是看體重的重點（F56 簽核時已告知 Ryan）
const CHART_POINTS = 1200;

// 本模組自己的畫面狀態（不進全域 state：換畫面即重置無妨）
const body = {
  metrics: [], // 升冪 [{date, weight_kg, body_fat_pct}]
  savedFlash: null, // 剛存成功的訊息（一次性）
  saving: false, // 防雙擊：送出中不再受理（教訓同 logSet／課表儲存）
  formOpen: false, // F54：記錄表單收進懸浮視窗——是否開啟
  editDate: null, // F17：清單裡正在行內編輯的那天（date iso）
  editDraft: { weight: "", fat: "" }, // F17：編輯草稿——驗證/網路失敗重繪時不丟使用者輸入
  metric: "weight", // F53：圖表與紀錄清單顯示哪一項（weight|fat）；不持久化，進畫面一律回體重
  // F56：查詢區間。{kind:"preset",months}；F87 起沒有自訂區間（五顆藥丸取代）。不持久化，進畫面回 3M
  range: { kind: "preset", months: 3 },
  // F58：資料起訖 {weight_first, fat_first, last}——判斷哪些區間檔位有意義（分體重／體脂各自判定）
  bounds: { weight_first: null, fat_first: null, last: null },
  rangeNote: null, // F58：點到停用檔位／自動退檔時的一次性說明
  // F53 review P2-1/P2-2：紀錄清單的捲動位置。**分頁籤各記一份**——體脂清單通常比體重短，
  // 只存一份的話「切去體脂（位置被夾成 0）再切回體重」會回不到原處
  rowsScroll: { weight: 0, fat: 0 },
  form: null, // F11：頂部補記表單草稿 {date,weight,fat}——失敗重繪時保留（尤其目標日期，
  // 否則重試會誤寫今天／覆蓋既有資料，Codex P1）；成功儲存後清空 → 回預設今天
};

// F53 review P2-1：重繪前把清單捲動位置抓下來（由 app.js 的 render() 統一呼叫）。
// 讀 DOM 而不掛 onscroll——節點被拆時瀏覽器補送的 scrollTop=0 會污染記錄（F48 首版的教訓）。
export function captureBodyScroll() {
  const live = document.querySelector(".bm-rows");
  // ⚠ 只在「DOM 裡這份清單確實屬於當前 metric」時才記錄。F58 P1-1 把切 metric 改走 rerender 後
  // 暴露了這個 bug：render() 開頭執行本函式時 body.metric 已是新的，但 DOM 還是舊 metric 的清單，
  // 於是舊清單的 scrollTop 被寫進新 metric 的記憶格；切回去時原本記住的位置就被蓋掉。
  if (live && live.dataset.metric === body.metric) {
    body.rowsScroll[body.metric] = live.scrollTop;
  }
}

// F56：月份回推（月底日期夾到當月最後一天，同 exercise-detail 的 monthsAgo）
function datesFor(range) {
  // review P3-3：preset 一旦被 loadRange 解析過就帶著 from/to——直接用它，不再重算 new Date()。
  // 否則「/body 開著跨過午夜 → 切體重/體脂頁籤（paint 不重新查資料）」會讓 domain 前進一天，
  // foot 顯示一組從未被查詢過的區間、最舊的點還會被 clamp 壓到左緣
  if (range.from && range.to) return { from: range.from, to: range.to };
  // F87：months=null 代表「全部」——起點是資料的最早日。
  // ⚠ 不能直接丟給 monthsAgo：`getMonth() - null` 是 `getMonth() - 0`，算出來是**今天**，
  // 於是「全部」只查得到今天那一筆（E2E 量到只畫一根長條才發現）。
  return {
    from: startOfPreset(range.months, firstDateFor(body.metric)),
    to: todayIso(),
  };
}

// F58：當前 metric 的最早紀錄日（體脂比體重稀疏，故分開判定；null＝沒有資料）
function firstDateFor(metric) {
  return metric === "fat" ? body.bounds.fat_first : body.bounds.weight_first;
}

let reqSeq = 0; // 過期回應丟棄：快速連點檔位時只採用最新一次查詢（同 exercise-detail 的 reqSeq）

// F56：取新區間的資料，**成功才原子提交 range＋metrics**；失敗（拋出）時兩者都不動，
// 由 guard 接住並以舊狀態重繪——不會出現「chip 已高亮但圖表還是舊區間」的半套狀態
// F56 review P2-1：mutation（記錄／編輯／刪除）後的重查也要有 seq 保護，否則「刪一列後立刻切區間」
// 可能讓晚回的舊查詢覆寫 body.metrics → chip 顯示新區間、資料卻是舊區間。與 loadRange 共用 reqSeq，
// 政策統一為「最後發出的贏」。
async function refetchCurrent() {
  // review P2-2：任何資料變動後，先前那條「還沒有更早的資料」之類的說明就過期了
  body.rangeNote = null;
  // review P2-3：順手非阻塞刷新 bounds——否則補記一筆更早的資料後，點灰掉的檔位會回一句
  // 「還沒有更早的資料」，與旁邊的「已補記 2020-01-01」直接互斥（主動說錯話）。
  // 用 .then 而非 await：bounds 失敗不該讓「記錄成功」變成失敗（同 openBody 的精神）
  api.bodyMetricBounds().then((b) => { body.bounds = b; }).catch(() => {});
  const seq = ++reqSeq;
  const data = await api.listBodyMetrics(datesFor(body.range));
  if (seq !== reqSeq) return;
  body.metrics = data;
}

async function loadRange(newRange) {
  const { from, to } = datesFor(newRange);
  const seq = ++reqSeq;
  const data = await api.listBodyMetrics({ from, to });
  if (seq !== reqSeq) return; // 較舊但較慢的回應——丟棄
  // 連同「實際查詢用的 from/to」一起存：foot 與 x 軸從此等於真正查過的區間（review P3-3）
  body.range = { ...newRange, from, to };
  body.metrics = data;
}

export async function openBody() {
  // review P3-5：先查資料、成功後才重設模組狀態——載入失敗時（離線／5xx）不會留下「範圍已重設但資料是舊的」
  // review P3-4：**先**抓 bounds 再決定初次載入哪個區間——否則資料只有幾天時，
  // 預設 3M 會同時是 on 與 off（被選中的那顆是灰的、旁邊 1M 卻亮著）。順序對調不多花請求。
  body.metric = "weight"; // 判定用當前 metric，先歸位（下面還會再設一次，無害）
  try {
    body.bounds = await api.bodyMetricBounds(); // F58
  } catch {
    body.bounds = { weight_first: null, fat_first: null, last: null }; // 拿不到就不限制，不擋開頁
  }
  const first = firstDateFor(body.metric);
  const initialMonths = presetUsable(3, first) ? 3 : longestAvailable(first);
  await loadRange({ kind: "preset", months: initialMonths }); // F56：進畫面回預設（不記憶選擇）
  body.rangeNote = null;
  body.savedFlash = null;
  body.editDate = null;
  body.form = null; // 進畫面回到預設今天
  body.formOpen = false; // F54：進畫面時視窗關著
  body.metric = "weight"; // F53：不記憶選擇（Ryan 決定），每次進來都是體重
  body.rowsScroll = { weight: 0, fat: 0 }; // 進畫面從頂端
}

/** F87 ⑩：把送出中的狀態直接寫進畫面（不重繪，才不會清掉正在輸入的值）。 */
function setSavingUi(on) {
  const modal = document.querySelector(".body-log-modal");
  if (!modal) return;
  modal.classList.toggle("saving", on);
  for (const button of modal.querySelectorAll(".modal-actions button")) {
    if (on) button.setAttribute("disabled", "");
    else button.removeAttribute("disabled");
  }
}

function latestMetric() {
  return body.metrics[body.metrics.length - 1] || null;
}

// ---------- F87：主卡（大數字＋差值）＋ 24 根長條圖 ----------

const BAR_COUNT = 24; // 設計稿訂的根數。資料不足 24 筆時**不補空條**（⑤）——補了會讓
//                      「才記三天」看起來像「有 24 天資料但大多是 0」。

function fmtValue(v) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/**
 * 主卡：左邊最新值（52px），右邊「這段區間變化了多少」。
 *
 * 差值的方向是有意義的：體重下降用 --good、上升用 --text-mute（⑤ 的凍結條文）。
 * ⚠ 這是體重的語意，體脂同向。**不對「上升」用警示色**——那會把「今天多喝了水」
 * 演成錯誤，而這個 app 不做價值判斷。
 */
function mainCard(points, unit, domain) {
  if (!points.length) {
    return el("div", { class: "body-main" }, [el("p", { class: "body-empty" }, ["還沒有紀錄"])]);
  }
  const last = points[points.length - 1];
  const first = points[0];
  const delta = last.value - first.value;
  const down = delta < 0;
  const spanText = domain.from === domain.to
    ? domain.from
    : `${domain.from.slice(5).replace("-", "/")} – ${domain.to.slice(5).replace("-", "/")}`;
  return el("div", { class: "body-main" }, [
    el("div", { class: "body-main-value" }, [
      el("span", { class: "bm-big" }, [fmtValue(last.value)]),
      el("span", { class: "bm-unit" }, [unit]),
    ]),
    el("div", { class: "body-main-delta" }, [
      el("span", { class: `bm-delta${down ? " down" : ""}` }, [
        `${delta > 0 ? "+" : delta < 0 ? "−" : "±"}${fmtValue(Math.abs(delta))} ${unit}`,
      ]),
      el("span", { class: "bm-span" }, [spanText]),
    ]),
  ]);
}

/**
 * 24 根長條。高度＝**24% + 正規化 * 72%**（Ryan 2026-07-30 裁決，偏離設計稿的 14%+82%）。
 *
 * 設計稿的 14% 下限是對著較高的圖表區訂的；F87 ⑪ 為了讓版面門檻避開 Ryan 的 727px 裝置，
 * 把長條區壓到 80px，14% 只剩 11px——圓角 99px 之下看起來是一顆點而不是長條，
 * 而那顆點正好是「最新值」的強調色，反而最不明顯（真機截圖才看出來）。
 * 提到 24%（約 19px）後最矮的仍讀得出是長條；最高仍是 96%，兩端的對比沒有變。
 *
 * 只有一筆資料時全部值相同，正規化分母為 0 → 一律給滿（不是 0）。
 */
function barChart(points, unit) {
  if (!points.length) return el("div", { class: "body-bars-empty" }, []);
  const shown = points.slice(-BAR_COUNT);
  const values = shown.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  return el("div", { class: "body-bars-wrap" }, [
    el(
      "div",
      { class: "body-bars" },
      shown.map((point, i) => {
        const norm = span === 0 ? 1 : (point.value - min) / span;
        return el("div", {
          class: `body-bar${i === shown.length - 1 ? " latest" : ""}`,
          style: `height:${(24 + norm * 72).toFixed(1)}%`,
          "aria-label": `${point.date} ${point.value}${unit}`,
        }, []);
      }),
    ),
    el("div", { class: "body-bars-foot" }, [
      el("span", {}, [shown[0].date.slice(5).replace("-", "/")]),
      el("span", {}, [shown[shown.length - 1].date.slice(5).replace("-", "/")]),
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

  // F54 review P2-2／P3-4：三條關窗路徑（遮罩／取消／成功）收斂成一支——原本只有「取消」清 state.error，
  // 用遮罩關窗會留下一條與當下無關的紅色錯誤掛在畫面上（還把版面撐高、擴大矮螢幕的溢出）。
  // 草稿也在這裡清：「關窗即無草稿」是不變式，比「開窗時補救」可靠（同 F49 P2-1 的收斂做法）。
  const closeLogModal = () => {
    body.formOpen = false;
    body.form = null;
    state.error = null;
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
    // F87 ⑩：旗標要**立刻**進 DOM。原本只設變數，而下一次重繪要等 await 回來——
    // 送出期間按鈕看起來完全正常，慢網路下使用者會一直按（邏輯上有 `if (body.saving) return`
    // 擋住，但畫面沒有任何回饋等於沒說）。
    // 用 class 而不是 rerender()：重繪會把視窗裡正在輸入的值與焦點一起打掉。
    setSavingUi(true);
    try {
      await api.logBodyMetric(payload);
      await refetchCurrent(); // F56：維持當前區間（含 seq 保護）
      body.savedFlash =
        dateSel === todayIso()
          ? "已記錄——同日重送會覆蓋更新"
          : `已補記 ${dateSel}——同日重送會覆蓋更新`;
      closeLogModal(); // 成功才關窗（含清草稿與錯誤）；失敗（拋錯）不關，輸入留在視窗裡可直接重試
    } finally {
      body.saving = false;
      setSavingUi(false);
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
    await refetchCurrent(); // F56：維持當前區間（含 seq 保護）
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
    await refetchCurrent(); // F56：維持當前區間（含 seq 保護）
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
    // F53：清單跟著 toggle 只顯示該項數值（編輯/刪除仍是整筆操作，編輯表單維持體重＋體脂兩欄）
    // F87 ⑧：體脂那天沒量就顯示 —（不再把整列藏起來）。用 em dash 而不是空字串，
    // 空的話那一列看起來像壞掉的資料，而「沒量」是正常狀態。
    const valText = body.metric === "fat"
      ? (m.body_fat_pct != null ? `${m.body_fat_pct} %` : "—")
      : `${m.weight_kg} kg`;
    return el("div", { class: "bm-row" }, [
      el("span", { class: "bm-date" }, [m.date]),
      el("span", { class: "bm-val" }, [valText]),
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
  // slice(-CHART_POINTS) 會靜默丟掉最舊的點（3Y preset 約 1096 天碰不到 1200，只有「自訂 > 1200 天」觸發）。
  // F57 起 foot 顯示的是 domain 邊界，所以被丟掉的點在 x 軸左側呈現為空白——看不出是「沒資料」還是
  // 「被丟棄」，這是已知降級（F56 P3-4 已接受）
  const weightPoints = body.metrics
    .map((m) => ({ date: m.date, value: m.weight_kg }))
    .slice(-CHART_POINTS);
  const fatPoints = body.metrics
    .filter((m) => m.body_fat_pct != null)
    .map((m) => ({ date: m.date, value: m.body_fat_pct }))
    .slice(-CHART_POINTS);

  // F53：體重／體脂一顆 toggle 切換（沿用 F36 動作表現的 metric 切換範式）。
  // 切換一律就地替換圖表與清單節點、不呼叫 rerender——整頁重繪會清掉上方表單正在輸入的值並讓
  // 輸入框失焦（本專案反覆踩過的「就地重畫」教訓，這次預先避開）。
  const chartHost = el("div", { class: "body-card-body" });
  const rowsHost = el("div", { class: "bm-rows" });
  const mkTab = (key, label) =>
    el(
      "button",
      {
        class: `metric-pill${body.metric === key ? " on" : ""}`,
        onclick: () => {
          // 先把目前頁籤的捲動位置收起來，再換頁籤（否則切過去被夾成 0，切回來就回不去了）
          body.rowsScroll[body.metric] = rowsHost.scrollTop;
          // review P3-1：切頁籤一併退出行內編輯——編輯列可能因過濾而消失，留著編輯態沒有任何提示
          body.metric = key;
          body.editDate = null;
          body.rangeNote = null;
          // F58：分 metric 判定的代價——切過去後當前檔位可能不可用（體脂通常比體重晚開始記）。
          // 留在不可用的檔位只會給一張空圖，故自動退到最長的可用檔位並說明一次。
          if (body.range.kind === "preset" && !presetUsable(body.range.months, firstDateFor(key))) {
            const months = longestAvailable(firstDateFor(key));
            const what = key === "fat" ? "體脂" : "體重";
            guard(async () => {
              await loadRange({ kind: "preset", months });
              // review P3-5：訊息在切換成功後才設——失敗時 metric 已切但區間沒切，
              // 若先設就會出現「說改了其實沒改」
              body.rangeNote = `${what}紀錄從 ${firstDateFor(key)} 開始，已改為顯示最近 ${months} 個月`;
              rerender();
            });
            return;
          }
          // review P1-1：這裡必須 rerender 而非 paint——paint() 只更新圖表/清單/toggle，
          // 不碰 .body-range 的 chips 與 .range-note，切 metric 後 chips 會留著上一個 metric 的
          // 灰／亮狀態（直接打掉「分 metric 判定」的契約）。rerender 同樣不重查資料，
          // 且 renderBody 尾端的 rAF 會還原 rowsScroll，F53 的分頁籤捲動記憶不受影響。
          rerender();
        },
      },
      [label],
    );
  const tabW = mkTab("weight", "體重");
  const tabF = mkTab("fat", "體脂");
  const toggle = el("div", { class: "metric-toggle" }, [tabW, tabF]);

  function paint() {
    const isFat = body.metric === "fat";
    const points = isFat ? fatPoints : weightPoints;
    const unit = isFat ? "%" : "kg";
    chartHost.replaceChildren(
      mainCard(points, unit, datesFor(body.range)),
      barChart(points, unit),
    );
    // F87 ⑧：體脂頁籤**列出全部日子**，沒量體脂的顯示 —。
    // 原本只列有體脂的日子是 F53 的實作解讀（acceptance ② 沒明說），後果是
    // 「那天忘了量體脂」在體脂頁籤完全看不到，也就改不到——要補記還得先切回體重頁籤。
    const rows = [...body.metrics].reverse();
    rowsHost.replaceChildren(
      ...(rows.length > 0 ? rows.map(metricRow) : [el("p", { class: "body-empty" }, ["還沒有紀錄"])]),
    );
    // >2 筆才捲動（門檻語意同 F48／F50／F51）；高度由 CSS 的 flex 吃剩餘空間
    rowsHost.classList.toggle("scrollable", rows.length > 2);
    for (const b of toggle.children) b.classList.remove("on");
    (isFat ? tabF : tabW).classList.add("on");
    rowsHost.dataset.metric = body.metric; // 給 captureBodyScroll 判斷這份清單屬於哪個 metric
    // 還原該頁籤自己的捲動位置（replaceChildren 會把 scrollTop 夾掉；review P2-2）
    rowsHost.scrollTop = body.rowsScroll[body.metric];
  }
  paint();
  // 整頁重繪後（編輯/刪除/儲存）用 rAF 還原——此時節點才進 DOM、scrollHeight 才算得出來（review P2-1）
  requestAnimationFrame(() => {
    rowsHost.scrollTop = body.rowsScroll[body.metric];
  });

  // F56：區間 chips＋自訂面板。切換一律走 loadRange（成功才提交），失敗由 guard 接住、狀態不動
  const presetBtn = ([label, months]) => {
    // F58：超出資料範圍的檔位灰掉但**仍可點**——點了顯示說明（用 disabled 就點不到、給不了說明）
    const available = presetUsable(months, firstDateFor(body.metric));
    const on = body.range.kind === "preset" && body.range.months === months;
    return el("button", {
      class: `range-pill${on ? " on" : ""}${available ? "" : " off"}`,
      // review P3-6：不能用 disabled（要能點以顯示說明）。**也不能用 aria-disabled**——它宣告的正是
      // 「不可互動」，與「點了給說明」自相矛盾，而且 Playwright 會據此拒絕點擊（實測踩到）。
      // 改用 aria-label 把狀態講給螢幕閱讀器聽，同時保留可互動語意。
      ...(available ? {} : { "aria-label": `${label}（超出資料範圍，點擊查看說明）` }),
      onclick: () => {
        if (!available) {
          const first = firstDateFor(body.metric);
          const what = body.metric === "fat" ? "體脂" : "體重";
          body.rangeNote = `最早的${what}紀錄是 ${first}，還沒有更早的資料`;
          rerender();
          return;
        }
        guard(async () => {
          body.rangeNote = null;
          await loadRange({ kind: "preset", months });
          rerender();
        });
      },
    }, [label]);
  };

  return el("section", { class: "screen body fills" }, [
    // F87 ①：沿用 .screen-head 慣例。副標講「最近一次量是哪天」——
    // 進這頁最常想確認的就是「我上次量是什麼時候」
    el("header", { class: "screen-head" }, [
      el("button", {
        class: "btn btn-ghost back-btn", "aria-label": "回首頁", onclick: goHome,
      }, [icon("back", { size: 20, label: "回首頁" })]),
      el("div", { class: "screen-head-text" }, [
        el("h1", {}, ["體重 · 體脂"]),
        el("span", { class: "st" }, [
          latest ? `最近一次 ${+latest.date.slice(5, 7)}月${+latest.date.slice(8, 10)}日` : "還沒有紀錄",
        ]),
      ]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...(body.savedFlash ? [el("div", { class: "body-saved" }, [body.savedFlash])] : []),

    el("div", { class: "range-pills body-range" }, PRESETS.map(presetBtn)),
    // F58：點到停用檔位／自動退檔時的說明（一次性，任何區間或頁籤操作即清）
    ...(body.rangeNote ? [el("p", { class: "range-note" }, [body.rangeNote])] : []),
    el("div", { class: "body-card" }, [
      el("div", { class: "body-card-head" }, [toggle]),
      chartHost,
    ]),
    // F33：紀錄清單收進卡片（與圖表卡一致）；F53：清單填滿剩餘空間、內部捲動。
    // review P3-3：完全沒有任何紀錄時不渲染這張卡（否則首次使用會看到空卡片還吃掉 120px）
    ...(body.metrics.length > 0
      ? [el("div", { class: "body-card body-list" }, [
          el("div", { class: "body-list-head" }, ["紀錄"]),
          rowsHost,
        ])]
      : []),
    // F54：表單收進懸浮視窗，畫面只留入口鈕；F55：入口鈕移到畫面下方（在「← 回首頁」之上）——原本這塊佔 231px，是 F53「清單填滿」在矮螢幕
    // 做不到的主因（/body 固定區塊 584px）
    el(
      "button",
      {
        class: "btn btn-primary body-log-open",
        // 純同步狀態變更，不需要 guard（guard 開頭本來就清 state.error，包起來只是雜訊；review P3-5）
        onclick: () => {
          body.form = null; // ⑥ 每次開窗從乾淨狀態（日期回今天、體重帶最新值）
          state.error = null;
          body.formOpen = true;
          rerender();
        },
      },
      ["＋ 記錄"],
    ),
    el("button", { class: "btn btn-ghost", onclick: goHome }, ["← 回首頁"]),
    // F54：記錄視窗（overlay）。錯誤訊息在視窗內自帶一份——遮罩會蓋住畫面上的 error-banner（F49 P2-2）
    ...(body.formOpen
      ? [
          el(
            "div",
            {
              class: "modal-overlay",
              onclick: (e) => {
                if (e.target !== e.currentTarget) return;
                if (body.saving) return; // 送出中不關（同 F43 P2-2）
                closeLogModal(); // review P2-2：三條關窗路徑共用，遮罩關窗也要清錯誤與草稿
                rerender();
              },
            },
            [
              el("div", { class: "modal body-log-modal" }, [
                el("div", { class: "modal-head" }, ["記錄體重"]),
                ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
                el("div", { class: "body-form" }, [
                  el("label", { class: "bm-date-field" }, [
                    el("span", { class: "bm-date-label" }, ["日期"]),
                    dateInput,
                  ]),
                  weightInput,
                  fatInput,
                ]),
                el("div", { class: "modal-actions" }, [
                  el(
                    "button",
                    {
                      class: "btn btn-primary",
                      ...(body.saving ? { disabled: "" } : {}),
                      onclick: () => guard(save),
                    },
                    ["✓ 記錄"],
                  ),
                  el(
                    "button",
                    {
                      class: "btn btn-ghost",
                      ...(body.saving ? { disabled: "" } : {}),
                      onclick: () => { closeLogModal(); rerender(); },
                    },
                    ["取消"],
                  ),
                ]),
              ]),
            ],
          ),
        ]
      : []),
  ]);
}
