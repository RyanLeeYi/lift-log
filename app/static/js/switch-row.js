// F106：設定頁的開關列。標籤在左、switch 在右，底下可掛一行**獨立可點**的副標。
//
// 為什麼不是藥丸按鈕（F81 到 F105 的樣子）：F89 ⑥ 的凍結條文描述的是 switch 的「軌道」與
// 「鈕」兩個零件的顏色，藥丸沒有那兩個零件，條文無從照字面驗。Ryan 2026-07-31 裁決改實作。
//
// ⚠ 副標為什麼要獨立成一顆可點的東西（本模組唯一的行為改動）：
// 藥丸時代把兩件事塞在同一顆按鈕上——「開但精確鬧鐘被關」時點下去是**去開系統授權**，
// 不是關掉提醒。switch 的點擊語意固定是「切換開關」，不能再兼任跳轉，否則使用者
// 想關提醒卻被丟到系統設定頁。所以出路搬到副標，它自己是按鈕。
//
// 副標的點擊會 stopPropagation：它在列的範圍內，不擋的話會冒泡到 switch 上，
// 變成「點出路順便把開關撥掉」——那正是把出路搬出來要避免的事（verify_f106 有反面斷言）。

import { el } from "./dom.js";
import { iconLabel } from "./icons.js";

/**
 * @param {object} opts
 * @param {string} opts.icon    icons.js 的圖示名
 * @param {string} opts.label   標籤文字（不含「：開／關」——狀態由 switch 自己表達）
 * @param {boolean} opts.on     開關狀態
 * @param {() => void} opts.onToggle 撥動時呼叫
 * @param {?{ text: string, onClick: () => void }} [opts.sub] 副標與它的出路；null＝不掛
 * @returns {HTMLElement}
 */
export function switchRow({ icon, label, on, onToggle, sub = null }) {
  const knob = el("span", { class: "switch-knob" });
  const track = el("span", { class: "switch-track" }, [knob]);
  const control = el(
    "button",
    {
      class: `switch${on ? " on" : ""}`,
      role: "switch",
      "aria-checked": on ? "true" : "false",
      "aria-label": label,
      onclick: onToggle,
    },
    [el("span", { class: "switch-label" }, [iconLabel(icon, label)]), track],
  );

  return el("div", { class: "switch-row" }, [
    control,
    ...(sub
      ? [
          el(
            "button",
            {
              class: "switch-sub",
              onclick: (e) => {
                e.stopPropagation(); // 見檔頭：不擋就會順手撥掉開關
                sub.onClick();
              },
            },
            [sub.text],
          ),
        ]
      : []),
  ]);
}
