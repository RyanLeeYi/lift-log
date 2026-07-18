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

// RPE 6–10 點選（再點同值＝取消）。apply(next) 收 6-10 或 null。
export function rpePicker(value, apply, rerender) {
  return el("div", { class: "rpe-row" }, [
    el("span", { class: "name" }, ["RPE"]),
    el("div", { class: "rpe" },
      [6, 7, 8, 9, 10].map((n) =>
        el(
          "button",
          {
            class: value === n ? "on" : "",
            onclick: () => { apply(value === n ? null : n); rerender(); },
          },
          [String(n)],
        ),
      ),
    ),
  ]);
}
