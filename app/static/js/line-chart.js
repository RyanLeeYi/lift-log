// 折線圖共用模組（F162）。動作表現（F134/F135/F136）與體重趨勢共用同一套幾何、
// 點渲染、浮動框定位與鍵盤互動。
//
// 為什麼抽出來而不是各寫一份：這裡的幾何有好幾條是 review 打出來的不變量，最典型的是
// x 用 (i+0.5)/n 而不是 i/(n-1)——後者會讓頭尾點貼齊容器邊緣，命中寬只剩內部點的一半、
// 跌破 F113 的 44px 觸控門檻（2026-08-07 P1 review 抓到）。複製一份等於複製兩份會各自
// 漂移的隱形規則；下一個改圖的人只會改到其中一邊。
//
// 呼叫端負責的事：把自己的資料轉成 { key, value, label } 的陣列，以及決定浮動框內容。
// 本模組不認識 session、不認識體重，只認識「一串有序的數值」。

import { el } from "./dom.js";

const SVG_NS = "http://www.w3.org/2000/svg";

// 圖高與上下留白（px）。CHART_H 要跟 app.css 的 .line-chart 高度一致——改一邊要改另一邊。
// CHART_PAD_TOP 要放得下最高點的圓點與（動作表現的）獎盃列。
export const CHART_H = 140;
export const CHART_PAD_TOP = 26;
export const CHART_PAD_BOTTOM = 12;

// 320px 視窗下的實際圖寬。所有「擠不擠得下」的判定一律用這個最窄情境，寬螢幕只會更鬆。
// （x 是百分比、真實寬度要 layout 後才知道，這裡不量 DOM，用最壞情況換取可預測與可測試。）
export const MIN_CHART_W = 252;

export function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

// F135 ①②④：未選中點依區間內點數 N 分級縮小。分級只動視覺尺寸（CSS class），
// 不動 x 座標公式與命中判定，所以頭尾一致的命中寬不受影響。選中點不分級（③）。
export function pointSizeClass(n) {
  if (n > 40) return " sz-sm"; // 4px
  if (n > 20) return " sz-md"; // 6px
  return ""; // N <= 20：8px
}

/**
 * 把 `{ key, value }` 陣列排進圖上的 x/y。
 *
 * x：序位等距、內縮到各自那一格的中心（不是依實際天數比例）——同一天兩筆也各占自己的
 * 位置，不會疊到同一像素。用 (i+0.5)/n 而非 i/(n-1) 的理由見檔頭。
 * y：span === 0（只有一筆，或所有值相同）畫在繪圖區中線，不除以 0。
 *
 * padTop 由呼叫端給：動作表現走獎盃帶時繪圖區要整個下移到帶子底下，圖總高不變、
 * 只有繪圖區被壓縮。沒有這種需求就給 CHART_PAD_TOP。
 */
export function layoutPoints(items, { padTop = CHART_PAD_TOP } = {}) {
  const n = items.length;
  if (n === 0) return [];
  const values = items.map((it) => it.value);
  const valMin = Math.min(...values);
  const valMax = Math.max(...values);
  const span = valMax - valMin;
  const plotH = CHART_H - padTop - CHART_PAD_BOTTOM;
  return items.map((item, i) => ({
    ...item,
    x: n === 1 ? 50 : ((i + 0.5) / n) * 100,
    y: span === 0
      ? padTop + plotH / 2
      : padTop + (1 - (item.value - valMin) / span) * plotH,
  }));
}

// 命中判定：x 軸距離最近的點（不要求精準落在點上）。points 等距排列，相鄰兩點的邊界
// 自然落在中點，不會重疊也不會留空隙。
export function nearestPointIndex(points, xPct) {
  let best = 0;
  let bestDist = Infinity;
  points.forEach((p, i) => {
    const dist = Math.abs(p.x - xPct);
    if (dist < bestDist) { bestDist = dist; best = i; }
  });
  return best;
}

// rerender() 是整棵子樹重繪，舊的 .line-pt 節點連同焦點一起被拆掉。鍵盤操作後要把焦點
// 找回「同一序位」的新節點——重繪後陣列順序不變（同一份資料、同一個排序），用索引對應
// 即可，不需要記住是哪一天。root 可指定，避免同頁有兩張圖時抓錯。
export function focusChartPoint(idx, root = document) {
  const pts = root.querySelectorAll(".line-pt");
  if (pts[idx]) pts[idx].focus();
}

// 每一行各自的 class。**三個名字必須各自唯一**：F134 的 E2E 用 `.line-tip-sets`
// 這種單一選擇器直接取值，同一個框裡出現兩個就撞 Playwright 的 strict mode
// （2026-08-20 抽共用模組時把它們壓成兩種，verify_f134 當場紅給我看）。
// 超過三行的情形沿用最後一個 class——目前沒有呼叫端這樣用。
const TIP_LINE_CLASSES = ["line-tip-date", "line-tip-sets", "line-tip-best"];

/**
 * 浮動框。選中的點落在最左/最右 30% 就靠邊貼齊，否則置中——避免框被容器裁切（F134 ⑦）。
 * lines 是要顯示的字串陣列，依序套 TIP_LINE_CLASSES。
 *
 * role="status" 隱含 aria-live="polite"：換點／關閉再開會被朗讀，不必另外掛 aria-live。
 */
export function lineTip(point, lines) {
  const align = point.x <= 30 ? "left" : point.x >= 70 ? "right" : "center";
  return el("div", {
    class: `line-tip align-${align}`,
    role: "status",
    ...(align === "center" ? { style: `left:${point.x}%` } : {}),
  }, lines.map((text, i) =>
    el("span", {
      class: TIP_LINE_CLASSES[Math.min(i, TIP_LINE_CLASSES.length - 1)],
    }, [text]),
  ));
}

/**
 * 資料點節點。滑鼠點擊由呼叫端在卡片層代理（要算 x 百分比），這裡只掛鍵盤——
 * 兩條路徑都走同一個 onSelect，不各自維護一份 toggle 邏輯（F136 ①）。
 *
 * role="button" + tabindex="0" 給鍵盤與螢幕閱讀器一個非指標裝置的入口；DOM 順序＝
 * points 陣列順序＝左舊右新，Tab 順序天然等於視覺順序，不必另外處理（F136 ①③）。
 */
export function pointNodes(points, { selected, sizeClass, extraClass, ariaLabel, onSelect, onClose }) {
  return points.map((point, i) =>
    el("div", {
      class: `line-pt${sizeClass}${extraClass ? extraClass(point) : ""}${point === selected ? " sel" : ""}`,
      style: `left:${point.x}%;top:${point.y}px`,
      role: "button",
      tabindex: "0",
      "aria-label": ariaLabel(point),
      onkeydown: (e) => {
        if (e.key === "Enter" || e.key === " ") {
          // Space 的預設行為是捲動頁面（沿用 dom.js stepper 同一套 preventDefault）
          e.preventDefault();
          onSelect(i);
        } else if (e.key === "Escape" && selected !== null) {
          e.preventDefault();
          onClose(i);
        }
      },
    }, []),
  );
}

// 折線本身。少於兩點畫不出線（單點只有圓點），不是錯誤狀態。
export function linePath(points) {
  const svg = svgEl("svg", {
    class: "line-svg", viewBox: `0 0 100 ${CHART_H}`, preserveAspectRatio: "none",
  });
  if (points.length >= 2) {
    svg.append(svgEl("polyline", {
      class: "line-path",
      points: points.map((p) => `${p.x},${p.y}`).join(" "),
      "vector-effect": "non-scaling-stroke",
    }));
  }
  return svg;
}

// 卡片層的點擊代理：落在 .line-chart 內就選最近的點，落在其餘地方（標題列、底部標示等
// 空白處）就關閉浮動框。x 用 getBoundingClientRect 換算成百分比，與 layoutPoints 的
// x 同一個座標系。
export function cardClickHandler(points, { onSelect, onClose }) {
  return (e) => {
    const chartEl = e.currentTarget.querySelector(".line-chart");
    if (!chartEl || !chartEl.contains(e.target)) {
      onClose();
      return;
    }
    const rect = chartEl.getBoundingClientRect();
    const frac = rect.width > 0
      ? Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
      : 0;
    onSelect(nearestPointIndex(points, frac * 100));
  };
}

// --- 聚合（F162 R6） --------------------------------------------------------
//
// 門檻 50 不是隨手取的：F135 ② 保證「320px 寬、圖寬 252px 下相鄰未選中點的圓緣間距
// >= 1px」，4px 的點因此需要 >= 5px 間距，252 / 5 約等於 50。超過這個數字，那條保證
// 本來就斷了——聚合正好接在它斷掉的地方。
export const AGG_MAX_POINTS = 50;

// 依序退：日 -> 週 -> 月，取第一個讓點數 <= AGG_MAX_POINTS 的單位。
const AGG_UNITS = [
  { unit: "day", label: null, bucket: (d) => d },
  { unit: "week", label: "每週平均", bucket: isoWeekStart },
  { unit: "month", label: "每月平均", bucket: (d) => `${d.slice(0, 7)}-01` },
];

// 該日所屬那一週的週一（ISO 週）。用 UTC 建構避免本地時區把日期推掉一天——
// date 字串本身是無時區的 YYYY-MM-DD，用 new Date(str) 會被當成 UTC 午夜，
// 再用 getDay()（本地）就可能落到前一天。整段一律走 UTC。
function isoWeekStart(dateStr) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  const dow = (d.getUTCDay() + 6) % 7; // 週一 = 0
  d.setUTCDate(d.getUTCDate() - dow);
  return d.toISOString().slice(0, 10);
}

/**
 * 點數超過門檻時把 items 併成區間平均。
 *
 * 取平均而不是取最佳，是 F56 那條反對意見的直接回應：體重是天天量的連續數列，
 * 取週/月「最佳」會抹掉短期波動，而波動正是看體重的重點。平均保住趨勢，而每個
 * 聚合點另外帶 min/max 與 from/to，讓呼叫端可以把波動放進浮動框裡——資訊沒有
 * 消失，只是從線上移到框裡。
 *
 * 回傳 { items, label }：label 為 null 代表沒有聚合，呼叫端維持原本的標題。
 */
export function aggregate(items, { maxPoints = AGG_MAX_POINTS } = {}) {
  for (const { label, bucket } of AGG_UNITS) {
    const groups = bucketize(items, bucket);
    // 最後一個單位（月）沒有更粗的可以退了：即使仍超過門檻也就用它。年平均對體重與
    // 訓練都太粗，寧可讓點擠在一起也不要給一條看不出東西的線；要細看可以用區間藥丸。
    const isLast = label === AGG_UNITS[AGG_UNITS.length - 1].label;
    if (groups.size > maxPoints && !isLast) continue;
    if (label === null) return { items, label: null };
    return { items: [...groups.entries()].map(summarize), label };
  }
  return { items, label: null }; // 不會走到（AGG_UNITS 非空），留著讓回傳型別一致
}

function bucketize(items, bucket) {
  const groups = new Map();
  for (const item of items) {
    const key = bucket(item.key);
    const group = groups.get(key);
    if (group) group.push(item);
    else groups.set(key, [item]);
  }
  return groups;
}

// 一個聚合點：平均撐折線，min/max 與 from/to 讓呼叫端把波動放進浮動框。
function summarize([key, group]) {
  const values = group.map((g) => g.value);
  return {
    key,
    value: values.reduce((a, b) => a + b, 0) / values.length,
    min: Math.min(...values),
    max: Math.max(...values),
    from: group[0].key,
    to: group[group.length - 1].key,
    count: group.length,
  };
}
