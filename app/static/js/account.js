// F148：資料生命週期──匯出、登出（Android 端擋未同步資料）、刪除帳號（二次確認＋近期 Google 重驗）。
// 網頁登出已經在 app.js 的 webSignOutRow 做完（web 沒有本機 domain 副本要清），這裡只補
// 三件事：匯出、原生登出（要清 LocalStore）、刪帳（web／native 共用）。

import { api } from "./api.js";
import {
  promptGoogleReauth,
  promptGoogleReauthNative,
  signOutNative,
} from "./auth.js";
import { el } from "./dom.js";
import { isNativeApp } from "./env.js";
import { readNativeSyncStatus, runNativeSync } from "./native-sync.js";

// 本模組自己的畫面狀態（不進全域 state：離開設定頁即重置無妨）
const acct = {
  busy: false,
  error: null,
  logoutBlock: null, // {pending, conflicts}——非 null 時顯示登出攔截視窗
  deleteOpen: false,
  deleteConfirmText: "",
};
const PENDING_ACCOUNT_WIPE = "liftlog.pending-account-wipe";

export function markPendingAccountWipe(storage = localStorage) {
  storage.setItem(PENDING_ACCOUNT_WIPE, "1");
}

export async function completePendingAccountWipe({
  storage = localStorage,
  wipe = api.wipeLocalData,
} = {}) {
  if (storage.getItem(PENDING_ACCOUNT_WIPE) !== "1") return false;
  await wipe();
  storage.removeItem(PENDING_ACCOUNT_WIPE);
  return true;
}

function reauth() {
  return isNativeApp() ? promptGoogleReauthNative() : promptGoogleReauth();
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: filename });
  link.click();
  URL.revokeObjectURL(url);
}

async function doExport() {
  const { idToken, nonce } = await reauth();
  const data = await api.exportAccount(idToken, nonce);
  downloadJson(`lift-log-export-${new Date().toISOString().slice(0, 10)}.json`, data);
}

function exportRow(rerender, guard) {
  const run = () => guard(async () => {
    if (acct.busy) return;
    acct.busy = true;
    rerender();
    try {
      await doExport();
    } finally {
      acct.busy = false;
      rerender();
    }
  });
  return el("div", { class: "set-row" }, [
    el("span", { class: "set-row-label" }, ["匯出資料"]),
    el("button", {
      class: "btn chip", "data-testid": "account-export",
      ...(acct.busy ? { disabled: "" } : {}), onclick: run,
    }, [acct.busy ? "處理中…" : "匯出"]),
  ]);
}

// ---------- Android 登出（web 登出在 app.js 的 webSignOutRow） ----------

export async function finishNativeSignOut({
  wipe = api.wipeLocalData,
  signOut = signOutNative,
  reload = () => location.reload(),
} = {}) {
  // 先清資料再撤銷 session：wipe 若失敗，帳號仍留著讓使用者重試，不會留下無主資料給下個帳號。
  await wipe();
  await signOut();
  acct.logoutBlock = null;
  reload();
}

function nativeSignOutRow(rerender, guard) {
  const attempt = () => guard(async () => {
    const status = await readNativeSyncStatus();
    if (status.pending > 0 || status.conflicts > 0) {
      acct.logoutBlock = { pending: status.pending, conflicts: status.conflicts };
      rerender();
      return;
    }
    await finishNativeSignOut();
  });
  return [el("div", { class: "set-row" }, [
    el("span", { class: "set-row-label" }, ["Google 帳號"]),
    el("button", { class: "btn chip", "data-testid": "native-signout", onclick: attempt }, ["登出"]),
  ])];
}

function logoutBlockedModal(rerender, guard) {
  if (!acct.logoutBlock) return [];
  const close = () => { acct.logoutBlock = null; rerender(); };
  const { pending, conflicts } = acct.logoutBlock;
  const parts = [
    pending > 0 ? `${pending} 筆待同步` : null,
    conflicts > 0 ? `${conflicts} 筆未解決衝突` : null,
  ].filter(Boolean).join("、");
  const syncThenClose = () => guard(async () => {
    await runNativeSync();
    close();
  });
  const exportThenKeepOpen = () => guard(doExport);
  const discardAndSignOut = () => guard(async () => {
    acct.logoutBlock = null;
    await finishNativeSignOut();
  });
  return [el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    [el("div", { class: "modal confirm-modal" }, [
      el("div", { class: "modal-head" }, ["還有未同步的資料"]),
      el("p", { class: "confirm-text" }, [
        `${parts}。登出前建議先同步或匯出，否則這些資料只留在這台裝置，登出後會被清除。`,
      ]),
      el("div", { class: "modal-actions" }, [
        el("button", { class: "btn chip", onclick: syncThenClose }, ["立即同步"]),
        el("button", { class: "btn chip", onclick: exportThenKeepOpen }, ["先匯出"]),
      ]),
      el("div", { class: "modal-actions" }, [
        el("button", { class: "btn btn-danger", onclick: discardAndSignOut }, ["仍要登出（捨棄）"]),
        el("button", { class: "btn btn-ghost", onclick: close }, ["取消"]),
      ]),
    ])],
  )];
}

// ---------- 刪除帳號（web／native 共用） ----------

function openDelete(rerender) {
  acct.deleteOpen = true;
  acct.deleteConfirmText = "";
  acct.error = null;
  rerender();
}

function closeDelete(rerender) {
  acct.deleteOpen = false;
  acct.deleteConfirmText = "";
  rerender();
}

function deleteAccountRow(rerender) {
  return el("div", { class: "set-row" }, [
    el("span", { class: "set-row-label" }, ["刪除帳號"]),
    el("button", {
      class: "btn chip", "data-testid": "account-delete-open",
      onclick: () => openDelete(rerender),
    }, ["刪除"]),
  ]);
}

async function finishDeleteAccount() {
  if (isNativeApp() && await completePendingAccountWipe()) {
    location.reload();
    return;
  }
  const { idToken, nonce } = await reauth();
  await api.deleteAccount(idToken, nonce, "DELETE");
  if (isNativeApp()) {
    markPendingAccountWipe();
    await completePendingAccountWipe();
  }
  location.reload();
}

function deleteAccountModal(rerender) {
  if (!acct.deleteOpen) return [];
  const close = () => closeDelete(rerender);
  const canConfirm = acct.deleteConfirmText.trim() === "DELETE";
  // 不透過 app.js 的 guard()：這個視窗自己有 error-banner，交給外層 guard 會多顯示一次
  const confirm = async () => {
    if (!canConfirm || acct.busy) return;
    acct.busy = true;
    acct.error = null;
    rerender();
    try {
      await finishDeleteAccount();
    } catch (err) {
      acct.busy = false;
      acct.error = err.message;
      rerender();
    }
  };
  return [el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    [el("div", { class: "modal confirm-modal" }, [
      el("div", { class: "modal-head" }, ["刪除帳號"]),
      el("p", { class: "confirm-text" }, [
        "刪除後帳號、雲端資料與這台裝置的本機資料都會清空，且無法復原。輸入 DELETE 以確認。",
      ]),
      el("input", {
        type: "text",
        class: "acct-confirm-input",
        "data-testid": "account-delete-confirm-input",
        value: acct.deleteConfirmText,
        oninput: (e) => { acct.deleteConfirmText = e.target.value; rerender(); },
      }),
      ...(acct.error ? [el("div", { class: "error-banner" }, [acct.error])] : []),
      el("div", { class: "modal-actions" }, [
        el("button", {
          class: "btn btn-danger", "data-testid": "account-delete-confirm",
          ...(canConfirm && !acct.busy ? {} : { disabled: "" }),
          onclick: confirm,
        }, [acct.busy ? "刪除中…" : "刪除帳號"]),
        el("button", { class: "btn btn-ghost", onclick: close }, ["取消"]),
      ]),
    ])],
  )];
}

// ---------- 對外入口 ----------

/**
 * 設定頁的帳號區塊：任何已用 Google 登入的使用者（不分 native／web）都看得到匯出與刪帳；
 * 登出的攔截邏輯只有 Android 需要（PRD R7 明文只提 Android 的 pending/conflict）。
 */
export function accountSettingsSection({ webAuthenticated, nativeAuthenticated }, rerender, guard) {
  const authenticated = isNativeApp() ? nativeAuthenticated : webAuthenticated;
  if (!authenticated) return [];
  return [
    exportRow(rerender, guard),
    ...(isNativeApp() ? nativeSignOutRow(rerender, guard) : []),
    deleteAccountRow(rerender),
    ...logoutBlockedModal(rerender, guard),
    ...deleteAccountModal(rerender),
  ];
}

// ---------- F158：MCP token 管理 ----------
// legacy 單一 token 沒有 user 身分，管不了 MCP token（app/api/mcp_tokens.py::_user_id）——
// 所以可見性條件與 accountSettingsSection 一樣，只有 Google 登入才看得到這塊。

const mcp = {
  tokens: null, // null＝尚未載入；[]＝載入完成但沒有 token
  loading: false,
  revokeTarget: null, // 要撤銷的 token row，非 null 時顯示確認視窗
  createOpen: false,
  createName: "",
  createExpires: "90", // "30" | "90" | "180" | "permanent"
  createReadOnly: false,
  createBusy: false,
  createError: null,
  createdPlaintext: null, // 建立成功後的回應——明文只在這裡出現一次
  copyFeedback: null,
};

const MCP_EXPIRY_OPTIONS = [
  { value: "30", label: "30 天" },
  { value: "90", label: "90 天" },
  { value: "180", label: "180 天" },
  { value: "permanent", label: "永久" },
];

// 伺服器把控制庫的時間戳存成不帶時區的 UTC naive datetime（見 services/mcp_tokens.py 開頭註解），
// JSON 序列化後字串沒有 Z——前端 `new Date()` 沒補這個會被當成瀏覽器本地時間解析，
// 顯示出來的「到期時間」整段偏移一個時區（同 app.js `detail.created_at + "Z"` 的既有作法）。
function formatLocalDateTime(iso) {
  return new Date(`${iso}Z`).toLocaleString("zh-TW", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function ensureMcpTokensLoaded(rerender, guard) {
  if (mcp.tokens !== null || mcp.loading) return;
  mcp.loading = true;
  guard(async () => {
    try {
      const rows = await api.listMcpTokens();
      // 外部資料不假設形狀——非陣列（伺服器契約意外跑掉、代理層吞掉回應）就當作空列表，
      // 不讓一顆壞回應把整個設定畫面的 render() 拖垮（mcp.tokens.map 會直接炸掉整頁）。
      mcp.tokens = Array.isArray(rows) ? rows : [];
    } catch (err) {
      // 失敗也要讓 mcp.tokens 脫離 null，不然下一輪 render 又會走進這裡再發一次請求 → 緊迴圈。
      // 錯誤本身照樣往外丟給 guard 的既有 showError（401 則由 guard 轉去登入畫面）。
      mcp.tokens = [];
      throw err;
    } finally {
      mcp.loading = false;
      rerender();
    }
  });
}

function mcpTokenRow(token, rerender, guard) {
  const revoked = token.revoked_at != null;
  const flags = [token.read_only ? "唯讀" : "可寫", revoked ? "已撤銷" : null]
    .filter(Boolean).join(" · ");
  const meta = [
    `建立於 ${formatLocalDateTime(token.created_at)}`,
    `最後使用 ${token.last_used_at ? formatLocalDateTime(token.last_used_at) : "尚未使用"}`,
    `到期 ${token.expires_at ? formatLocalDateTime(token.expires_at) : "永久"}`,
  ].join("　");
  return el("div", { class: "mcp-token-row", "data-testid": "mcp-token-row" }, [
    el("div", { class: "mcp-token-row-head" }, [
      el("span", { class: "mcp-token-name" }, [token.name]),
      el("span", { class: `mcp-token-flags${revoked ? " revoked" : ""}` }, [flags]),
    ]),
    el("div", { class: "mcp-token-meta" }, [meta]),
    ...(revoked ? [] : [el("button", {
      class: "btn chip", "data-testid": "mcp-token-revoke",
      onclick: () => { mcp.revokeTarget = token; rerender(); },
    }, ["撤銷"])]),
  ]);
}

function mcpTokenRows(rerender, guard) {
  if (mcp.tokens === null) return [el("div", { class: "mcp-token-empty" }, ["載入中…"])];
  if (mcp.tokens.length === 0) {
    return [el("div", { class: "mcp-token-empty" }, ["尚未建立任何 token"])];
  }
  return mcp.tokens.map((token) => mcpTokenRow(token, rerender, guard));
}

function mcpRevokeModal(rerender, guard) {
  const token = mcp.revokeTarget;
  if (!token) return [];
  const close = () => { mcp.revokeTarget = null; rerender(); };
  const confirmRevoke = () => guard(async () => {
    await api.revokeMcpToken(token.id);
    mcp.revokeTarget = null;
    mcp.tokens = await api.listMcpTokens(); // ③：撤銷後列表要真的反映伺服器狀態
    rerender();
  });
  return [el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    [el("div", { class: "modal confirm-modal" }, [
      el("div", { class: "modal-head" }, ["撤銷 Token"]),
      el("p", { class: "confirm-text" }, [
        `確定撤銷「${token.name}」？撤銷後無法復原，任何用它連線的第三方會立刻失效。`,
      ]),
      el("div", { class: "modal-actions" }, [
        el("button", {
          class: "btn btn-danger", "data-testid": "mcp-token-revoke-confirm", onclick: confirmRevoke,
        }, ["撤銷"]),
        el("button", { class: "btn btn-ghost", onclick: close }, ["取消"]),
      ]),
    ])],
  )];
}

function openCreateMcpToken(rerender) {
  mcp.createOpen = true;
  mcp.createName = "";
  mcp.createExpires = "90";
  mcp.createReadOnly = false;
  mcp.createBusy = false;
  mcp.createError = null;
  mcp.createdPlaintext = null;
  mcp.copyFeedback = null;
  rerender();
}

function closeCreateMcpToken(rerender) {
  mcp.createOpen = false;
  mcp.createdPlaintext = null;
  rerender();
}

// ②：明文只在這次回應出現一次——關掉這個視窗之後就再也拿不到，複製失敗要有可讀的手動備案。
function mcpTokenRevealModal(rerender) {
  const created = mcp.createdPlaintext;
  const close = () => closeCreateMcpToken(rerender);
  const tokenInput = el("input", {
    type: "text", readonly: "", class: "acct-confirm-input mcp-token-value",
    "data-testid": "mcp-token-plaintext", value: created.token,
  });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created.token);
      mcp.copyFeedback = "已複製";
    } catch {
      // clipboard API 在部分瀏覽器／非 https 情境不可用——退回「選起來讓你手動複製」
      tokenInput.focus();
      tokenInput.select();
      mcp.copyFeedback = "自動複製失敗，已為你選取文字，請手動複製";
    }
    rerender();
  };
  return el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    [el("div", { class: "modal confirm-modal" }, [
      el("div", { class: "modal-head" }, ["Token 已建立"]),
      el("p", { class: "confirm-text" }, [
        "這是唯一能看到完整內容的機會——關掉這個視窗後就再也看不到明文，請先複製並妥善保存。",
      ]),
      tokenInput,
      ...(mcp.copyFeedback
        ? [el("p", { class: "confirm-text mcp-copy-feedback" }, [mcp.copyFeedback])] : []),
      el("div", { class: "modal-actions" }, [
        el("button", { class: "btn chip", "data-testid": "mcp-token-copy", onclick: copy }, ["複製"]),
      ]),
      el("div", { class: "modal-actions" }, [
        el("button", { class: "btn btn-primary", "data-testid": "mcp-token-done", onclick: close }, ["完成"]),
      ]),
    ])],
  );
}

// ①②：建立視窗——名稱、到期（預設有限期）、唯讀／可寫。不透過外層 guard：
// 失敗時要留在視窗內顯示錯誤，交給 guard 會多顯示一次（同 deleteAccountModal 的理由）。
function mcpCreateModal(rerender) {
  if (!mcp.createOpen) return [];
  if (mcp.createdPlaintext) return [mcpTokenRevealModal(rerender)];
  const close = () => closeCreateMcpToken(rerender);
  const canSubmit = mcp.createName.trim().length > 0 && !mcp.createBusy;
  const submit = async () => {
    if (!canSubmit) return;
    mcp.createBusy = true;
    mcp.createError = null;
    rerender();
    let created;
    try {
      created = await api.createMcpToken({
        name: mcp.createName.trim(),
        expires_in_days: mcp.createExpires === "permanent" ? null : Number(mcp.createExpires),
        read_only: mcp.createReadOnly,
      });
    } catch (err) {
      mcp.createBusy = false;
      mcp.createError = err.message;
      rerender();
      return;
    }
    mcp.tokens = await api.listMcpTokens(); // 與 mcpRevokeModal 一致：讓列表順序真的反映伺服器狀態
    mcp.createdPlaintext = created;
    mcp.createBusy = false;
    rerender();
  };
  return [el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    [el("div", { class: "modal confirm-modal" }, [
      el("div", { class: "modal-head" }, ["新增 MCP Token"]),
      el("input", {
        type: "text", class: "acct-confirm-input", placeholder: "名稱（例如 Claude）",
        "data-testid": "mcp-token-name-input", value: mcp.createName,
        oninput: (e) => { mcp.createName = e.target.value; rerender(); },
      }),
      el("div", { class: "mcp-field-label" }, ["到期"]),
      el("div", { class: "chips", "data-testid": "mcp-token-expiry" }, MCP_EXPIRY_OPTIONS.map((opt) =>
        el("button", {
          class: `chip${mcp.createExpires === opt.value ? " on" : ""}`,
          "data-testid": `mcp-token-expiry-${opt.value}`,
          onclick: () => { mcp.createExpires = opt.value; rerender(); },
        }, [opt.label]))),
      ...(mcp.createExpires === "permanent" ? [el("p", { class: "confirm-text" }, [
        "永久 token 不會自動過期，外洩風險較高——只在你能持續保管的情境使用，且務必記得日後手動撤銷。",
      ])] : []),
      el("div", { class: "mcp-field-label" }, ["權限"]),
      el("div", { class: "chips" }, [
        el("button", {
          class: `chip${!mcp.createReadOnly ? " on" : ""}`, "data-testid": "mcp-token-scope-write",
          onclick: () => { mcp.createReadOnly = false; rerender(); },
        }, ["可寫"]),
        el("button", {
          class: `chip${mcp.createReadOnly ? " on" : ""}`, "data-testid": "mcp-token-scope-readonly",
          onclick: () => { mcp.createReadOnly = true; rerender(); },
        }, ["唯讀"]),
      ]),
      ...(mcp.createError ? [el("div", { class: "error-banner" }, [mcp.createError])] : []),
      el("div", { class: "modal-actions" }, [
        el("button", {
          class: "btn btn-primary", "data-testid": "mcp-token-create-confirm",
          ...(canSubmit ? {} : { disabled: "" }),
          onclick: submit,
        }, [mcp.createBusy ? "建立中…" : "建立"]),
        el("button", { class: "btn btn-ghost", onclick: close }, ["取消"]),
      ]),
    ])],
  )];
}

/** 設定頁的 MCP token 區塊：只有 Google 登入的使用者看得到（legacy token 管不了 MCP token）。 */
export function mcpTokenSection({ webAuthenticated, nativeAuthenticated }, rerender, guard) {
  const authenticated = isNativeApp() ? nativeAuthenticated : webAuthenticated;
  if (!authenticated) return [];
  ensureMcpTokensLoaded(rerender, guard);
  return [
    el("section", { class: "card mcp-token-card" }, [
      el("div", { class: "card-label" }, ["MCP TOKEN"]),
      ...mcpTokenRows(rerender, guard),
      el("button", {
        class: "btn chip", "data-testid": "mcp-token-add",
        onclick: () => openCreateMcpToken(rerender),
      }, ["新增 Token"]),
    ]),
    ...mcpRevokeModal(rerender, guard),
    ...mcpCreateModal(rerender),
  ];
}
