// 共用 DOM helper：建元素、掛 class 與事件。

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    node.append(child);
  }
  return node;
}

// 觸控友善的 +/- 數值調整（記錄新組與 F16 編輯共用，避免手機上難點的原生 number 箭頭）。
// apply(delta) 就地改外部狀態、rerender() 重繪。
export function stepper(name, value, steps, apply, rerender) {
  return el("div", { class: "stepper" }, [
    el("span", { class: "name" }, [name]),
    el("output", {}, [String(value)]),
    el("div", { class: "pair" },
      steps.map(([label, delta]) =>
        el("button", { class: "btn", onclick: () => { apply(delta); rerender(); } }, [label]),
      ),
    ),
  ]);
}

// F40：口語「累度軸」——一條 5 停點 slider（可左右拖、也可點停點），對應底層 rpe 6–10。
// 一律有值（新組預設輕鬆＝6；value 為 null 的舊組亦起始 6），不再有「未記」空狀態。
// 拖曳/點選時只就地更新本元件 DOM（形容詞＋停點高亮），絕不呼叫 rerender——否則整頁重繪會把
// 正在拖的 input 拆掉、中斷拖曳（同「就地重畫」教訓）；rerender 參數保留僅為呼叫端簽名相容。
// F84：done-list 也要顯示口語詞，所以匯出——兩處各寫一份對照表遲早會走鐘
export const RPE_WORDS = { 6: "輕鬆", 7: "有餘力", 8: "吃力", 9: "很吃力", 10: "力竭" };

export function rpePicker(value, apply, _rerender) {
  // 底層 schema 允許 rpe 1–10，但此軸只呈現 6–10 五個停點。舊資料 1–5（或任何越界值）正規化到
  // 最低停點 6，且同步回呼叫端草稿——否則畫面顯示輕鬆卻仍送出原 1–5 值，畫面≠送出（Codex P2）。
  const cur = value == null ? 6 : Math.min(10, Math.max(6, value));
  if (value != null && value !== cur) apply(cur);
  const word = el("output", { class: "rpe-word" }, [RPE_WORDS[cur]]);
  const slider = el("input", {
    type: "range", class: "rpe-slider", min: "6", max: "10", step: "1",
    value: String(cur), "aria-label": "這組多累？",
  });
  const ticks = [6, 7, 8, 9, 10].map((n) =>
    el("button", { type: "button", class: `rpe-tick${n === cur ? " on" : ""}` }, [RPE_WORDS[n]]),
  );
  const paint = (v) => {
    slider.value = String(v);
    word.textContent = RPE_WORDS[v];
    ticks.forEach((t, i) => t.classList.toggle("on", 6 + i === v));
  };
  const set = (v) => { apply(v); paint(v); }; // 就地更新，不整頁重繪
  slider.addEventListener("input", () => set(Number(slider.value)));
  ticks.forEach((t, i) => t.addEventListener("click", () => set(6 + i)));
  return el("div", { class: "rpe-axis" }, [
    el("div", { class: "rpe-head" }, [
      el("span", { class: "rpe-lbl" }, ["這組多累？"]),
      word,
    ]),
    slider,
    el("div", { class: "rpe-ticks" }, ticks),
  ]);
}
