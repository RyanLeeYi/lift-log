// F10 自訂動作建立視窗——picker 與課表編輯「加動作」視窗共用。
// 自我包含：輸入值直接讀 DOM、錯誤就地顯示（不觸發父層重繪，故不會清空正在填的欄位）。
// 參數：
//   groups   現有部位字串陣列（做 chips）
//   onCreated(exercise) 建立成功回呼——父層負責刷新自己的可選清單並移除本視窗
//   onCancel()          取消 / 點遮罩空白處
//   onFatal(err)        非就地可處理的錯誤（401、非預期）——交父層 guard 處理

import { api, ApiError } from "./api.js";
import { el } from "./dom.js";

export function customExerciseModal({ groups, onCreated, onCancel, onFatal }) {
  let selectedGroup = null; // 選中的現有部位 chip（null＝未選）

  const nameZh = el("input", { type: "text", placeholder: "中文名（必填）" });
  const nameEn = el("input", { type: "text", placeholder: "英文名（選填）" });
  const customGroup = el("input", { type: "text", placeholder: "其他部位（自訂，選填）" });
  const bodyweight = el("input", { type: "checkbox" });

  const errorBox = el("div", { class: "error-banner" }, []);
  errorBox.style.display = "none";
  const showError = (msg) => {
    errorBox.textContent = msg;
    errorBox.style.display = "";
  };

  const chips = el(
    "div",
    { class: "chips" },
    groups.map((g) =>
      el(
        "button",
        {
          class: "chip",
          // 就地切換高亮＋更新選取，不重繪——否則會清空正在填的文字輸入
          onclick: () => {
            selectedGroup = selectedGroup === g ? null : g;
            chips
              .querySelectorAll(".chip")
              .forEach((c) => c.classList.toggle("on", c.textContent === selectedGroup));
          },
        },
        [g],
      ),
    ),
  );

  const confirmBtn = el("button", { class: "btn btn-primary modal-confirm" }, ["建立"]);

  const submit = async () => {
    const name_zh = nameZh.value.trim();
    if (!name_zh) {
      showError("中文名必填");
      return;
    }
    const payload = { name_zh, is_bodyweight: bodyweight.checked };
    const en = nameEn.value.trim();
    if (en) payload.name_en = en;
    const grp = customGroup.value.trim() || selectedGroup; // 自訂文字優先，否則用選中的 chip
    if (grp) payload.muscle_group = grp;

    confirmBtn.disabled = true;
    try {
      const created = await api.createExercise(payload);
      onCreated(created); // 父層刷新清單並移除本視窗
    } catch (err) {
      confirmBtn.disabled = false;
      // 就地可處理：驗證/重複（400）與離線（0）——顯示錯誤、保住已填內容（DOM 未動）
      if (err instanceof ApiError && err.status !== 401) {
        showError(err.status === 0 ? "連不上伺服器——稍後再試" : err.message);
        return;
      }
      onFatal(err); // 401 / 非預期 → 交父層 guard 清狀態
    }
  };
  confirmBtn.addEventListener("click", submit);

  return el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) onCancel(); } },
    [
      el("div", { class: "modal custom-ex-modal" }, [
        el("div", { class: "modal-head" }, ["新增自訂動作"]),
        errorBox,
        nameZh,
        nameEn,
        el("div", { class: "field-label" }, ["部位（選填）"]),
        chips,
        customGroup,
        el("label", { class: "checkbox-row" }, [bodyweight, el("span", {}, ["自體重動作"])]),
        el("div", { class: "modal-actions" }, [
          confirmBtn,
          el("button", { class: "btn btn-ghost modal-cancel", onclick: onCancel }, ["取消"]),
        ]),
      ]),
    ],
  );
}
