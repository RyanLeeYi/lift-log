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

async function finishNativeSignOut() {
  await signOutNative();
  await api.wipeLocalData();
  acct.logoutBlock = null;
  location.reload();
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
  const { idToken, nonce } = await reauth();
  await api.deleteAccount(idToken, nonce, "DELETE");
  if (isNativeApp()) await api.wipeLocalData();
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
