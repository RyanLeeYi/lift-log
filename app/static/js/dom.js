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
// F102：數字本身可點擊直接輸入。從 40 調到 100 原本要點 24 次 ±2.5，這是補一條路——
// ± 兩顆保留，微調時點一下比叫出鍵盤快。
//
// `edit` 給 { set, parse }：`parse(raw)` 回 number 代表合法、回 null 代表不合法（原值不動）。
// 各欄位的規則各自定義（重量一位小數、次數正整數），不在這裡塞一堆旗標。
// 不給 `edit` 就是唯讀的舊行為。
export function stepper(name, value, steps, apply, rerender, edit = null) {
  const out = edit
    ? el("output", {
        class: "value editable",
        tabindex: "0",
        role: "button",
        "aria-label": `${name}，點擊直接輸入`,
      }, [String(value)])
    : el("output", {}, [String(value)]);

  if (edit) {
    const beginEdit = () => {
      // ④ 就地換成 input，**不整頁重繪**——重繪會把剛長出來的 input 拆掉，
      // 鍵盤跟著收起、游標位置也沒了（F88 參考休息自訂輸入踩過同一個坑）。
      const input = el("input", {
        type: "text",
        // decimal 給重量的小數點；次數用同一個鍵盤也拿得到數字，不必分兩種
        inputmode: "decimal",
        class: "value-input",
        value: String(value),
        "aria-label": name,
      });
      let done = false;
      const finish = (commit) => {
        if (done) return; // blur 與 Enter 會前後腳各觸發一次
        done = true;
        const parsed = commit ? edit.parse(input.value) : null;
        // ③ 不合法（空白／abc／負數／小數位數過多）＝**還原原值**，不送 NaN、不清成 0
        if (parsed !== null && parsed !== value) {
          edit.set(parsed);
          rerender();
          return;
        }
        input.replaceWith(out);
      };
      input.addEventListener("blur", () => finish(true));
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); finish(true); }
        else if (e.key === "Escape") { e.preventDefault(); finish(false); }
      });
      out.replaceWith(input);
      input.focus();
      input.select();
    };
    out.addEventListener("click", beginEdit);
    out.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); beginEdit(); }
    });
  }

  return el("div", { class: "stepper" }, [
    el("span", { class: "name" }, [name]),
    out,
    el("div", { class: "pair" },
      steps.map(([label, delta]) =>
        el("button", { class: "btn", onclick: () => { apply(delta); rerender(); } }, [label]),
      ),
    ),
  ]);
}

// F102 ③：重量＝非負、最多一位小數。多一位就是打錯了，四捨五入會把錯誤吞掉，所以擋下。
export function parseWeight(raw) {
  const t = String(raw).trim();
  if (!/^\d+(\.\d)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 && n <= 999 ? n : null;
}

// F102 ③：次數＝正整數（0 次不是一組）。
export function parseReps(raw) {
  const t = String(raw).trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 && n <= 999 ? n : null;
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
