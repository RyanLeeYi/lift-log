// F165：內建對話畫面。一句話查詢或記錄訓練，寫入前先看 dry-run 摘要再自己按確認。
//
// 寫入的兩段式在 server（F164）：第一次只算會發生什麼並回 pending_write，
// 這裡把它原樣存著，使用者按「確認寫入」才帶回去。按取消就整包丟掉，不送第二次請求。

import * as api from "./api.js";
import { el } from "./dom.js";
import { icon, iconLabel } from "./icons.js";

// 上游錯誤碼 → 人話。看不懂的碼一律走 fallback，不把原始碼丟到畫面上。
const ERROR_TEXT = {
  llm_key_missing: "還沒有可用的 LLM API key。到設定頁的「對話 API KEY」填入自己的 key 後再試。",
  llm_unauthorized: "這把 API key 無效或沒有權限，到設定頁換一把。",
  llm_rate_limited: "上游額度用盡或太頻繁，等一下再試。",
  llm_timeout: "上游回應逾時，等一下再試。",
  llm_unreachable: "連不上 LLM 服務，檢查網路後再試。",
  llm_upstream_error: "LLM 服務回應異常，等一下再試。",
  llm_tool_loop_exhausted: "這個問題繞太多輪還沒有結論，換個說法再問一次。",
};

let messages = []; // {role: "user" | "assistant", text}
let pending = null; // {write, dryRun} — 等使用者確認的寫入
let busy = false;
let errorText = "";
let draft = "";

export function resetChat() {
  messages = [];
  pending = null;
  busy = false;
  errorText = "";
  draft = "";
}

function errorMessage(error) {
  return ERROR_TEXT[error?.message] ?? "對話服務暫時不可用，等一下再試。";
}

function summaryLine(result) {
  if (!result) return "已寫入。";
  if (result.error) return result.error;
  const parts = [];
  if (result.sets_count !== undefined) parts.push(`${result.sets_count} 組`);
  // 噸位與總秒數並列不相加（F105 ③）
  if (result.tonnage_kg) parts.push(`噸位 ${result.tonnage_kg} kg`);
  if (result.duration_seconds) parts.push(`總計 ${result.duration_seconds} 秒`);
  if (result.weight_kg !== undefined) parts.push(`體重 ${result.weight_kg} kg`);
  return parts.length ? `已寫入：${parts.join("、")}` : "已寫入。";
}

function dryRunCard(rerender, guard) {
  const { write, dryRun } = pending;
  const counts = dryRun
    ? [
        `將新增 ${dryRun.will_create_count} 筆`,
        `將略過 ${dryRun.will_skip_count} 筆`,
        `將衝突 ${dryRun.will_conflict_count} 筆`,
      ].join("、")
    : "將寫入 1 筆";
  const preview = (dryRun?.preview ?? []).slice(0, 5).map((row) =>
    el("li", { class: "chat-preview-row" }, [
      `${row.exercise} ${row.weight_kg} kg × ${row.reps ?? `${row.duration_seconds} 秒`}`,
    ]),
  );
  return el("section", { class: "card chat-dryrun", "data-testid": "chat-dryrun" }, [
    el("div", { class: "card-label" }, ["寫入前確認"]),
    el("div", { class: "chat-dryrun-counts" }, [counts]),
    ...(preview.length ? [el("ul", { class: "chat-preview" }, preview)] : []),
    el("div", { class: "modal-actions" }, [
      el(
        "button",
        {
          class: "btn btn-primary",
          "data-testid": "chat-confirm",
          ...(busy ? { disabled: "" } : {}),
          onclick: () =>
            guard(async () => {
              busy = true;
              errorText = "";
              rerender();
              try {
                const resp = await api.chat({ pendingWrite: write });
                messages.push({ role: "assistant", text: summaryLine(resp.result) });
                pending = null;
              } catch (error) {
                errorText = errorMessage(error);
              } finally {
                busy = false;
                rerender();
              }
            }),
        },
        ["確認寫入"],
      ),
      el(
        "button",
        {
          class: "btn btn-ghost",
          "data-testid": "chat-cancel",
          ...(busy ? { disabled: "" } : {}),
          // 取消不送第二次請求——沒有請求就沒有寫入
          onclick: () => {
            pending = null;
            messages.push({ role: "assistant", text: "已取消，沒有寫入任何資料。" });
            rerender();
          },
        },
        ["取消"],
      ),
    ]),
  ]);
}

export function renderChat(rerender, backHome, guard) {
  const send = () =>
    guard(async () => {
      const text = draft.trim();
      if (!text || busy) return;
      messages.push({ role: "user", text });
      draft = "";
      busy = true;
      errorText = "";
      pending = null;
      rerender();
      try {
        const resp = await api.chat({ message: text });
        if (resp.reply) messages.push({ role: "assistant", text: resp.reply });
        if (resp.pending_write) pending = { write: resp.pending_write, dryRun: resp.dry_run };
      } catch (error) {
        errorText = errorMessage(error);
      } finally {
        busy = false;
        rerender();
      }
    });

  return el("section", { class: "screen chat-screen" }, [
    el("header", { class: "topbar" }, [el("h1", {}, ["對話"])]),
    ...(errorText
      ? [el("div", { class: "error-banner", "data-testid": "chat-error" }, [errorText])]
      : []),
    el(
      "div",
      { class: "chat-log", "data-testid": "chat-log" },
      messages.map((m) => el("div", { class: `chat-bubble chat-${m.role}` }, [m.text])),
    ),
    ...(busy ? [el("div", { class: "chat-busy" }, ["思考中…"])] : []),
    ...(pending ? [dryRunCard(rerender, guard)] : []),
    el("div", { class: "chat-input-row" }, [
      el("input", {
        class: "input chat-input",
        "data-testid": "chat-input",
        type: "text",
        value: draft,
        placeholder: "例：深蹲 60 公斤 5 下",
        oninput: (e) => {
          draft = e.target.value; // 不重繪：重繪會讓輸入游標跳掉
        },
        onkeydown: (e) => {
          if (e.key === "Enter") send();
        },
      }),
      el(
        "button",
        {
          class: "btn btn-primary chat-send",
          "data-testid": "chat-send",
          ...(busy ? { disabled: "" } : {}),
          onclick: send,
        },
        [icon("arrow-right", { size: 18, label: "送出" })],
      ),
    ]),
    el(
      "button",
      { class: "btn btn-ghost settings-back", onclick: () => guard(async () => backHome()) },
      [iconLabel("back", "回首頁")],
    ),
  ]);
}
