// F76：結構性圖示的唯一來源。
//
// 為什麼不用 emoji：emoji 是**彩色字形**，各平台長得不一樣、也不吃 CSS 的顏色——
// 2026-07-28 在原生浮動視窗上實測踩到（`setTextColor` 對 ⏹ 完全沒作用，畫面毫無變化）。
// 這裡的圖示走 `stroke="currentColor"`，顏色由 CSS 變數決定，一次改全站一致。
//
// 圖形取自 Lucide（ISC 授權）的路徑資料，**內嵌在專案裡**——app 版離線時也要畫得出來，
// 不能依賴 CDN（acceptance ②）。線寬統一 2、視框統一 24（③）。

const SVG_NS = "http://www.w3.org/2000/svg";

// 每個項目是該圖示的 path 資料（相對 24×24 視框）。新增圖示時只加在這裡。
const PATHS = {
  dumbbell: ["M14.4 14.4 9.6 9.6", "M18.657 21.485a2 2 0 1 1-2.829-2.828l-1.767 1.768a2 2 0 1 1-2.829-2.829l6.364-6.364a2 2 0 1 1 2.829 2.829l-1.768 1.767a2 2 0 1 1 2.828 2.829z", "m21.5 21.5-1.4-1.4", "M3.9 3.9 2.5 2.5", "M6.404 12.768a2 2 0 1 1-2.829-2.829l1.768-1.767a2 2 0 1 1-2.828-2.829l2.828-2.828a2 2 0 1 1 2.829 2.828l1.767-1.768a2 2 0 1 1 2.829 2.829z"],
  clipboard: ["M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2", "M12 11h4", "M12 16h4", "M8 11h.01", "M8 16h.01", "M15 2H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1z"],
  calendar: ["M8 2v4", "M16 2v4", "M3 10h18", "M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"],
  trending: ["M16 7h6v6", "m22 7-8.5 8.5-5-5L2 17"],
  // 天平（Lucide scale）——原本誤貼成左右箭頭的路徑，模擬器上一眼就看出畫錯
  scale: ["m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1z", "m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1z", "M7 21h10", "M12 3v18", "M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"],
  bell: ["M10.268 21a2 2 0 0 0 3.464 0", "M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"],
  window: ["M2 10h20", "M12 10v10", "M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"],
  timer: ["M10 2h4", "M12 14v-4", "M4 13a8 8 0 0 1 8-7 8 8 0 1 1-5.3 14L4 17.6"],
  pause: ["M14 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z", "M7 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"],
  play: ["M6 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 6 4.5z"],
  stop: ["M5 5h14a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"],
  check: ["M20 6 9 17l-5-5"],
  back: ["m12 19-7-7 7-7", "M19 12H5"],
  pencil: ["M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z", "m15 5 4 4"],
  trash: ["M10 11v6", "M14 11v6", "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6", "M3 6h18", "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"],
  download: ["M12 15V3", "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "m7 10 5 5 5-5"],
  warning: ["m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3", "M12 9v4", "M12 17h.01"],
  hourglass: ["M5 22h14", "M5 2h14", "M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22", "M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"],
};

/**
 * 建一個圖示元素。
 *
 * @param {string} name PATHS 裡的名稱
 * @param {{size?: number, label?: string}} opts size 走圖示尺寸 token（預設 20）；
 *   label 給只有圖示、沒有文字的按鈕當無障礙名稱（priority 1：icon-only 一定要有名字）
 */
export function icon(name, { size = 20, label } = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor"); // ④：顏色跟著文字色，深色主題自動正確
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("class", "icon");
  if (label) {
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
  } else {
    svg.setAttribute("aria-hidden", "true"); // 旁邊已有文字時不要讓螢幕閱讀器唸兩次
  }
  for (const d of PATHS[name] ?? []) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

/** 圖示 ＋ 文字的標準組合（間距與基線對齊集中在這裡，見 ③）。 */
export function iconLabel(name, text, opts = {}) {
  const wrap = document.createElement("span");
  wrap.className = "icon-label";
  wrap.append(icon(name, opts), document.createTextNode(text));
  return wrap;
}
