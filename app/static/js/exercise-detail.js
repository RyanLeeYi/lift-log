// 動作表現頁（F36 起，F86 改版，F134 起圖表換成可點選折線圖）：
// 三張全期 PR 卡 ＋ 五檔時間窗 ＋ 每次最佳組折線圖 ＋ 歷來紀錄卡。
// 資料源＝GET /api/exercises/{id}/history（F35；F86 起 prs 多了 top_est_1rm 與 top_session_volume）。

import { api } from "./api.js";
import { el } from "./dom.js";
import { icon } from "./icons.js";
import {
  PRESETS,
  iso,
  longestAvailable,
  monthsAgo,
  presetAvailable as presetUsable,
} from "./range.js";
import { exerciseName, state } from "./state.js";
import {
  CHART_H,
  CHART_PAD_BOTTOM,
  CHART_PAD_TOP,
  MIN_CHART_W,
  aggregate,
  cardClickHandler,
  focusChartPoint,
  layoutPoints,
  lineTip,
  linePath,
  pointNodes,
  pointSizeClass,
} from "./line-chart.js";

// 本模組畫面狀態（不進全域 state：換畫面即重置無妨）
const detail = {
  exerciseId: null,
  exercise: null, // {id, name_zh, name_en}
  returnScreen: "picker", // 返回目的地（F38 兩入口各自帶入）
  range: { kind: "preset", months: 3 }, // months=null＝「全部」
  rangeNote: null, // F59：點到停用檔位時的一次性說明（初次退檔是靜默的，同 F58 的 openBody）
  data: { prs: {}, sessions: [] },
  chartSelected: null, // F134：折線圖目前選中的資料點索引（對應 barChart() 內建出的 points 陣列）
  bodyweight: 0, // F37：自體重動作噸位用（取最新體重，同日曆的近似）
};

function datesFor(range) {
  const today = new Date();
  // 「全部」：從最早訓練日起。還不知道最早日（第一次開頁）時退到一個夠早的日期，
  // 不用 null——後端的 from 是必填，少一個參數會變成 422。
  if (range.months === null) {
    return { from: detail.data.first_session_date || "2000-01-01", to: iso(today) };
  }
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
  detail.chartSelected = null; // F134 ⑤：切換區間要清掉浮動資訊與選中狀態，不殘留上一個區間的點
}

export function detailReturnScreen() {
  return detail.returnScreen;
}

// 入口（F38 的 picker／logger 兩處呼叫）：載入預設 3M 資料
export async function openExerciseDetail(exercise, returnScreen = "picker") {
  detail.exerciseId = exercise.id;
  detail.exercise = exercise;
  detail.returnScreen = returnScreen;
  detail.range = { kind: "preset", months: 3 };
  detail.data = { prs: {}, sessions: [] }; // 清掉上一個動作殘留
  detail.chartSelected = null; // F134：換動作也要清掉上一個動作殘留的圖表選中狀態
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
  detail.rangeNote = null;
  const myId = exercise.id; // review P2-1：載入期間使用者可能又點了別的動作
  await loadRange({ kind: "preset", months: 3 });
  // review P2-1：本函式在 await 後才切畫面，期間可再點另一個動作。若 detail.exerciseId 已被換掉，
  // 這裡的續行就不該再動任何狀態（同 app.js pickExercise 的 `state.exercise !== exercise` 手法）
  if (detail.exerciseId !== myId) return;
  // F59（同 F58 P3-4）：first_session_date 要等第一次查詢回來才知道；若 3M 其實不可用就退檔，
  // 否則畫面會出現「被選中的那顆是灰的」。
  // review P2-2：**不再發第二次請求**——可以證明它必然多餘：presetUsable(3, detail.data.first_session_date) 為 false
  // ⇒ 資料全落在最近一個月內 ⇒ 可用集合恆為 {1M} ⇒ 1M 的資料是剛拿到的 3M 的嚴格子集。
  // 而那次請求若失敗會讓使用者「明明資料在手上卻進不去頁面」。所以就地過濾。
  if (!presetUsable(3, detail.data.first_session_date)) {
    const months = longestAvailable(detail.data.first_session_date);
    // F121：起始日走本模組的 datesFor（同一份規則），**不要自己再算一次 monthsAgo**——
    // F86 ③ 加了「全部」檔位（months === null）之後 longestAvailable 的答案就是它，而
    // `getMonth() - null` 是 `getMonth() - 0`，算出來是**今天**：於是「唯一一次訓練在 10 天前」
    // 的動作退檔後被濾成空清單（退檔本來是為了「別給一張空圖」，結果自己造了一張）。
    // datesFor 早就處理了 null 這個情形——重複的第二份算式才是 bug 的來源。
    const { from } = datesFor({ kind: "preset", months });
    detail.range = { kind: "preset", months };
    detail.data = {
      ...detail.data,
      sessions: detail.data.sessions.filter((x) => x.date >= from),
    };
  }
}

// ---------- F86：每次最佳組（F105 起依 mode 分流） ----------

// F105：判斷一律用動作的 mode，不用「哪個欄位非空」（凍結契約）。
function isTimeMode() {
  return detail.exercise?.mode === "time";
}

// 一次訓練的「最佳組」：次數型＝重量最大者（同重量取次數多的）；
// 時間型＝撐最久者（duration_seconds 最大）——沒有「重量」這個排序軸。
// ⚠ 這是整個畫面的軸心（折線圖的 y 座標、chip 的獎盃、右上角的最大值都問它），
// 所以只能有一個定義。先前 dayBlock 自己用 `Math.max(weight)` 判當日最重，
// 遇到同重量不同次數會同時標兩顆——那不是「最佳組」，是「最重的重量」。
function bestSet(session) {
  if (isTimeMode()) {
    return session.sets.reduce((a, b) => (b.duration_seconds > a.duration_seconds ? b : a));
  }
  return session.sets.reduce((a, b) => {
    if (b.weight_kg !== a.weight_kg) return b.weight_kg > a.weight_kg ? b : a;
    return b.reps > a.reps ? b : a;
  });
}

// bestSet() 拿到的那組要拿哪個欄位當「排名用數值」——折線圖 y 座標、PR 累進判定共用。
function bestMetric(best) {
  return isTimeMode() ? best.duration_seconds : best.weight_kg;
}

function sessionTonnage(session) {
  // 自體重動作以（最新體重＋額外負重）計，同日曆 set_tonnage 規則
  const bw = detail.exercise?.is_bodyweight && detail.bodyweight ? detail.bodyweight : 0;
  return session.sets.reduce((a, x) => a + (x.weight_kg + bw) * x.reps, 0);
}

// F105 ③：時間型以總秒數表達一次訓練的份量（reps 型用噸位，見上）。
function sessionDuration(session) {
  return session.sets.reduce((a, x) => a + x.duration_seconds, 0);
}

// ---------- render ----------

function fmtNum(v) {
  // 26px 的數字欄位放不下無意義的小數：整數就不補 .0
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

function renderPrCards(cards) {
  return el(
    "div",
    { class: "pr-cards" },
    cards.map(([label, value, unit, hi]) =>
      el("div", { class: `pr-card${hi ? " hi" : ""}` }, [
        el("div", { class: "pr-k" }, [label]),
        el("div", { class: "pr-v" }, [value, ...(unit ? [el("span", { class: "pr-u" }, [unit])] : [])]),
      ]),
    ),
  );
}

function prCards() {
  const prs = detail.data.prs || {};
  // F105 ⑤（Ryan 拍板）：時間型只有兩張卡（最長單組秒數／單次訓練總秒數），
  // 兩張等分——`.pr-card{flex:1}` 本來就是等分規則，卡數變動不必再改 CSS。
  // 估計 1RM「整格不出現」＝陣列裡根本沒有那個項目，不是塞 "—" 進去。
  if (isTimeMode()) {
    return renderPrCards([
      ["最長單組秒數", prs.top_set_duration == null ? "—" : fmtNum(prs.top_set_duration.duration_seconds), "秒", true],
      ["單次訓練總秒數", prs.top_session_duration_seconds == null ? "—" : fmtNum(prs.top_session_duration_seconds), "秒", false],
    ]);
  }
  const top = prs.top_weight;
  return renderPrCards([
    // 主卡（--card-hi 底 ＋ --accent 數字）：推估 1RM 是三者中最能一眼看出進步的
    ["推估 1RM", prs.top_est_1rm == null ? "—" : fmtNum(Math.round(prs.top_est_1rm)), "", true],
    ["最重", top ? fmtNum(top.weight_kg) : "—", "", false],
    [
      "單次量",
      prs.top_session_volume == null ? "—" : fmtNum(Math.round(prs.top_session_volume / 100) / 10),
      "t",
      false,
    ],
  ]);
}

// ---------- F134：可點選的折線圖（取代上面 F86 ⑤ 的長條圖） ----------




/**
 * 把 sessions 轉成畫圖用的點陣列：x／y 座標、是否 PR，並過濾掉算不出最佳組的那次
 * （F134 邊界情況：sets 是空陣列，或 bestSet() 給的排名數值是 null——沿用 bestSet()／
 * bestMetric() 本身的定義，這裡只加一層「算不出來就跳過、不連線」的防呆）。
 *
 * PR 判定沿用 F86：**累進**最佳（到那次為止的最高），不是「等於全期最大值」。
 * F105：排名數值＝bestMetric()，次數型是 weight_kg、時間型是 duration_seconds。
 */
function chartPoints(sessions) {
  const raw = sessions
    .map((s) => {
      if (!s.sets.length) return null;
      const best = bestSet(s);
      const metric = best ? bestMetric(best) : null;
      return metric != null ? { date: s.date, session: s, best, metric } : null;
    })
    .filter(Boolean);
  let running = -Infinity;
  for (const point of raw) {
    point.isPr = point.metric > running;
    if (point.isPr) running = point.metric;
  }
  // F162：點數超過門檻改畫區間平均（日 -> 週 -> 月）。聚合後 PR 這個概念不再對應到
  // 單一場次，所以獎盃一併不畫——這是 F134 ⑧「不省略資料點」被本條 supersede 的部分，
  // 換來的是點距回到看得清的範圍。動作表現實務上很少超過 50 點，這條路徑罕見但不特例化。
  const { items, label } = aggregate(
    raw.map((p) => ({ ...p, key: p.date, value: p.metric })),
  );
  const aggregated = label !== null;
  // 走獎盃帶時，繪圖區整個下移到帶子底下——這就是「獎盃永不蓋住資料點」的來源。
  // 圖總高（CHART_H／app.css 的 .line-chart）維持不變，只有繪圖區被壓縮。
  const band = aggregated ? null : flagLayout(items.length);
  const padTop = band ? band.height + FLAG_BAND_GAP : CHART_PAD_TOP;
  return { points: layoutPoints(items, { padTop }), band, aggLabel: label };
}


// PR 獎盃 icon 尺寸比照同一套分級縮小（④），高 N 時避免獎盃彼此蓋住；不省略任何一個。
function trophySize(n) {
  if (n > 40) return 8;
  if (n > 20) return 9;
  return 11;
}

const FLAG_ROW_GAP = 2;   // 帶內兩層之間的垂直留白
// 獎盃帶與繪圖區之間的留白。下限不是隨手取的：帶底到最高點圓心的距離＝
// FLAG_BAND_GAP + FLAG_ROW_GAP，而**選中**的點是 13px（半徑 6.5）再加 4px 光暈＝10.5px，
// 不留夠就會在選中最大重量那點（嚴格遞增的紀錄裡就是最後一點，日常最常見）時
// 讓光暈畫進獎盃列。box-shadow 不進 bounding box，E2E 量不到，只能從這裡保證。
const FLAG_BAND_GAP = 9;
const MIN_PLOT_H = 60;    // 繪圖區的下限：帶子再厚也不能把折線壓成一橫

/**
 * F135 ④ 的獎盃佈局（2026-08-08 Ryan 裁示「照字面」後重做）。
 *
 * 原本獎盃畫在各自資料點正上方。icon 寬 8–11px，而點距在 N 變大時會縮到更小
 * （N=50／320px 下只有 5.03px），於是兩件事同時發生：獎盃彼此重疊，且 icon 橫向
 * 侵入鄰點欄位、把 y 剛好落在那條帶子裡的鄰點蓋住。要讓 icon 窄到不重疊就得縮到
 * 5px 以下，那個尺寸的獎盃（stroke 2/24 → 0.42px）已經看不出形狀，等於變相省略標記。
 *
 * 改法：點距容不下 icon 時，把獎盃移進繪圖區**上方的專用帶**，並依序位 `i % rows`
 * 分層交錯。兩條保證都變成幾何上的必然，不是靠調參數湊出來的餘裕：
 *   - 不蓋住鄰點：帶子與所有資料點分屬不相交的 y 區間（padTop 已把繪圖區整個推到帶子下方）
 *   - 不互相重疊：同一層相鄰兩個獎盃的 x 間距＝rows × 點距 ≥ icon 寬（rows 就是這樣取的）
 *
 * 回傳 null＝點距夠寬，維持 F134 原本畫在點正上方的樣子（低 N 的常態不受影響）。
 */
function flagLayout(n) {
  const iconW = trophySize(n);
  const spacing = MIN_CHART_W / n;
  if (iconW <= spacing) return null;
  const rowH = iconW + FLAG_ROW_GAP;
  // rows 必須有上界：CHART_H 是固定的 140，讓 rows 無限長會把 plotH 吃成負數
  // （n≥379 時），而負的 plotH 會讓 y 公式反轉——最大重量畫到最下面，最小重量頂進帶子裡，
  // 正好違反這條 feature 要保證的 ④。review 2026-08-08 抓到。
  const maxRows = Math.max(1, Math.floor((CHART_H - CHART_PAD_BOTTOM - MIN_PLOT_H - FLAG_BAND_GAP) / rowH));
  const rows = Math.min(Math.ceil(iconW / spacing), maxRows);
  // ponytail: rows 撞到 maxRows 之後（8px icon 約 n>127）同層間距不再必然 ≥ icon 寬，
  // 獎盃會重新開始重疊。那個密度下 ② 的「相鄰點圓緣間距 ≥1px」本來就已經不可能成立
  // （點距 <2px），要救得連點的佈局一起改（分頁或聚合），不是這條 feature 的範圍。
  return { iconW, rows, rowH, height: rows * rowH };
}


// F105 ⑥：一組的數值標籤依 mode 分流——時間型顯示「N 秒」，不是把 duration_seconds
// 套進次數型「N 次」的位置（reps 欄位本身在時間型 set 上就是 null）。
function bestSetLabel(best) {
  return isTimeMode()
    ? `${best.duration_seconds} 秒`
    : `${fmtNum(best.weight_kg)}kg × ${best.reps}`;
}


// F136 ①：滑鼠點擊（經 .bars-card 代理）與鍵盤 Enter/Space（掛在各自的 .line-pt）
// 走同一個選中分支，不各自維護一份 toggle 邏輯。
function selectChartPoint(idx, rerender) {
  detail.chartSelected = detail.chartSelected === idx ? null : idx;
  rerender();
}


// 聚合後的浮動框：顯示區間與平均，並把該區間的最低／最高一併帶出來——聚合抹掉的是
// 線上的波動，不是資訊本身（同 body.js 對 F56 那條反對意見的回應）。
function aggTipLines(point, unit) {
  const range = `${point.from.slice(5).replace("-", "/")}-${point.to.slice(5).replace("-", "/")}`;
  return [
    `${range}  平均 ${fmtNum(point.value)}${unit}`,
    `最低 ${fmtNum(point.min)}  最高 ${fmtNum(point.max)}`,
    `${point.count} 次`,
  ];
}

function barChart(rerender) {
  const { points, band, aggLabel } = chartPoints(detail.data.sessions);
  if (!points.length) {
    return el("div", { class: "bars-card" }, [
      el("p", { class: "bars-empty" }, ["這個區間內沒有紀錄"]),
    ]);
  }
  const max = Math.max(...points.map((p) => p.metric ?? p.value)); // F105：時間型是秒數，次數型是重量
  const monthOf = (d) => `${+d.slice(5, 7)}月`;
  const unit = isTimeMode() ? " 秒" : " kg";
  const selected = detail.chartSelected != null ? points[detail.chartSelected] : null;
  const sizeClass = pointSizeClass(points.length); // F135 ①②④：依 N 分級

  const close = (focusIdx) => {
    if (detail.chartSelected === null) return;
    detail.chartSelected = null;
    rerender();
    if (focusIdx != null) focusChartPoint(focusIdx);
  };
  const select = (idx, refocus) => {
    selectChartPoint(idx, rerender);
    if (refocus) focusChartPoint(idx);
  };

  return el("div", {
    class: "bars-card",
    onclick: cardClickHandler(points, { onSelect: (i) => select(i, false), onClose: () => close(null) }),
  }, [
    el("div", { class: "bars-head" }, [
      // F162 R6：聚合時標題要講明畫的是區間平均，不能讓人以為每個點是一次訓練。
      el("span", { class: "bars-title" }, [aggLabel ? `每次最佳組（${aggLabel}）` : "每次最佳組"]),
      el("span", { class: "bars-max" }, [`${fmtNum(max)}${unit}`]),
    ]),
    el("div", { class: "line-chart" }, [
      linePath(points),
      ...pointNodes(points, {
        selected,
        sizeClass,
        // 聚合後沒有「某一次是 PR」這回事，點也就不上獎盃色。
        extraClass: (p) => (p.isPr && !aggLabel ? " pr" : ""),
        ariaLabel: (p) => (aggLabel
          ? aggTipLines(p, unit).join("，")
          : `${p.date} 最佳組 ${bestSetLabel(p.best)}`),
        onSelect: (i) => select(i, true),
        onClose: (i) => close(i),
      }),
      // 獎盃只在 PR 那幾點才畫（不像長條圖需要每欄都保留節點來撐版面——
      // 這裡每個點的 y 各自獨立算出，沒有那個限制）。
      // 點距容不下 icon 時走專用帶（見 flagLayout）：top 改用帶內固定分層，不再跟著點的 y。
      // 交錯用的是**序位 i**（不是第幾個 PR）——相鄰序位必落在不同層，而同層兩個獎盃
      // 至少隔 rows 個序位，橫向間距因此 >= icon 寬。
      ...(aggLabel ? [] : points.map((point, i) => [point, i]).filter(([p]) => p.isPr).map(([point, i]) =>
        el("div", {
          class: `line-flag${sizeClass}${band ? " band" : ""}`,
          style: band
            ? `left:${point.x}%;top:${(i % band.rows) * band.rowH}px`
            : `left:${point.x}%;top:${point.y}px`,
        }, [
          icon("trophy", { size: trophySize(points.length), label: "個人紀錄" }),
        ]),
      )),
      ...(selected
        ? [lineTip(selected, aggLabel
            ? aggTipLines(selected, unit)
            : [
                selected.date.slice(5).replace("-", "/"),
                `${selected.session.sets.length} 組`,
                bestSetLabel(selected.best),
              ])]
        : []),
    ]),
    el("div", { class: "bars-foot" }, [
      el("span", {}, [monthOf(points[0].key)]),
      ...(aggLabel ? [] : [el("span", { class: "bars-legend" }, [icon("trophy", { size: 9 }), "個人紀錄"])]),
      el("span", {}, [monthOf(points[points.length - 1].key)]),
    ]),
  ]);
}

function relTime(dateStr) {
  const days = Math.round((new Date(iso(new Date())) - new Date(dateStr)) / 864e5);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 30) return `${days} 天前`;
  if (days < 365) return `${Math.round(days / 30)} 個月前`;
  return `${Math.floor(days / 365)} 年前`;
}

// F105 ⑥：組列表 chip 的量測值——次數型「重量×次數」、時間型「重量×秒數」
// （沿用既有無空格、無 kg 單位的緊湊格式，只把 reps 換成 duration_seconds＋秒）。
function chipLabel(x) {
  return isTimeMode() ? `${fmtNum(x.weight_kg)}×${x.duration_seconds}秒` : `${fmtNum(x.weight_kg)}×${x.reps}`;
}

// F86 ⑥：一次訓練一張卡。F37 的月份摺疊拿掉——改版後每張卡本來就只有兩行，
// 摺疊層級反而讓「最近練得如何」要多點兩下才看得到。
function sessionCard(session) {
  const best = bestSet(session);
  // F105 ③：時間型改由總秒數表達一次訓練的份量（次數型仍是噸位）。
  const volume = isTimeMode()
    ? `${sessionDuration(session)} 秒`
    : `${Math.round(sessionTonnage(session)).toLocaleString()} kg`;
  return el("div", { class: "hist-card" }, [
    el("div", { class: "hist-head" }, [
      el("span", { class: "hist-date" }, [session.date.slice(5).replace("-", "/")]),
      el("span", { class: "hist-rel" }, [relTime(session.date)]),
      el("span", { class: "hist-vol" }, [volume]),
    ]),
    el(
      "div",
      { class: "hist-sets" },
      session.sets.map((x) =>
        el("span", { class: `set-chip${x === best ? " best" : ""}` }, [
          chipLabel(x),
          ...(x.rpe ? [el("span", { class: "rpe" }, [`@${x.rpe}`])] : []),
          ...(x === best ? [icon("trophy", { size: 11, label: "當次最佳組" })] : []),
        ]),
      ),
    ),
  ]);
}

function renderHistory() {
  const sessions = [...detail.data.sessions].reverse(); // 新→舊
  if (!sessions.length) return [el("p", { class: "hist-empty" }, ["這個區間內沒有紀錄"])];
  return sessions.map(sessionCard);
}

export function renderExerciseDetail(rerender, goBack, guard) {
  const presetBtn = ([label, months]) => {
    // F86 ④（承 F59）：超出資料範圍的檔位灰掉但**仍可點**——點了顯示說明。
    // 不能用 disabled／aria-disabled：前者點不到，後者宣告「不可互動」會讓 Playwright 拒絕點擊。
    const available = presetUsable(months, detail.data.first_session_date);
    const on = detail.range.months === months;
    return el("button", {
      class: `range-pill${on ? " on" : ""}${available ? "" : " off"}`,
      ...(available ? {} : { "aria-label": `${label}（超出資料範圍，點擊查看說明）` }),
      onclick: () => {
        if (!available) {
          detail.rangeNote = `這個動作最早的訓練是 ${detail.data.first_session_date}，還沒有更早的資料`;
          rerender();
          return;
        }
        guard(async () => {
          detail.rangeNote = null;
          await loadRange({ kind: "preset", months }); // 成功才提交檔位＋資料
          rerender();
        });
      },
    }, [label]);
  };

  return el("section", { class: "screen exercise-detail" }, [
    // 沿用 F81 起的 .screen-head 慣例（.back-btn／.screen-head-text／.st），
    // 不另立一套類名——版面規則已經在 CSS 那邊定義過一次了
    el("header", { class: "screen-head" }, [
      el("button", {
        class: "btn btn-ghost back-btn", "aria-label": "返回", onclick: goBack,
      }, [icon("back", { size: 20, label: "返回" })]),
      el("div", { class: "screen-head-text" }, [
        el("h1", {}, [exerciseName(detail.exercise)]),
        el("span", { class: "st" }, [
          `${detail.exercise?.name_en ?? ""} · ${detail.data.sessions.length} 次紀錄`,
        ]),
      ]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    prCards(),
    el("div", { class: "range-pills" }, PRESETS.map(presetBtn)),
    ...(detail.rangeNote ? [el("p", { class: "range-note" }, [detail.rangeNote])] : []),
    barChart(rerender),
    el("div", { class: "hist-list" }, renderHistory()),
  ]);
}
