import { apiBase } from "./env.js";

const syncPlugin = () => globalThis.Capacitor?.Plugins?.Sync;

function requirePlugin(plugin) {
  if (!plugin) throw new Error("這個 APK 不支援資料同步，請更新 App");
  return plugin;
}

/** 將 Capacitor bridge 的鬆散回傳收斂成 UI 可依賴的固定 shape。 */
export function normalizeSyncStatus(value = {}) {
  const allowed = new Set(["synced", "pending", "offline", "error"]);
  const state = allowed.has(value.state) ? value.state : "error";
  return {
    state,
    pending: Math.max(0, Number(value.pending) || 0),
    failed: Math.max(0, Number(value.failed) || 0),
    cursor: Math.max(0, Number(value.cursor) || 0),
    lastSyncedAt: value.lastSyncedAt == null ? null : Number(value.lastSyncedAt),
    errorCode: value.errorCode || null,
    nextSyncAt: Math.max(0, Number(value.nextSyncAt) || 0),
    bootstrapComplete: value.bootstrapComplete === true,
    conflicts: Math.max(0, Number(value.conflicts) || 0),
  };
}

/** 未解決的衝突；每筆都帶本機與雲端兩份值，UI 只負責顯示與轉送選擇。 */
export async function readNativeConflicts({ plugin = syncPlugin() } = {}) {
  const value = await requirePlugin(plugin).conflicts();
  return Array.isArray(value?.items) ? value.items : [];
}

export async function resolveNativeConflict(
  { conflictId, choice, mutationId }, { plugin = syncPlugin() } = {},
) {
  if (choice !== "local" && choice !== "server") throw new Error("不支援的衝突解決方式");
  return normalizeSyncStatus(
    await requirePlugin(plugin).resolveConflict({ conflictId, choice, mutationId }),
  );
}

export async function initializeNativeSync({ plugin = syncPlugin(), baseUrl = apiBase() } = {}) {
  return normalizeSyncStatus(await requirePlugin(plugin).initialize({ baseUrl }));
}

export async function readNativeSyncStatus({ plugin = syncPlugin() } = {}) {
  return normalizeSyncStatus(await requirePlugin(plugin).status());
}

export async function runNativeSync({ plugin = syncPlugin() } = {}) {
  return normalizeSyncStatus(await requirePlugin(plugin).syncNow());
}
