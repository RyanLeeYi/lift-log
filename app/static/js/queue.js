// 離線佇列：送不出去的組先進 IndexedDB，恢復連線後照入列順序重放。
// 靠 client_uuid 冪等不重複；4xx（如 workout 已被刪）標 failed 留佇列供手動捨棄，不無限重試。

import { isNativeApp } from "./env.js";

const DB_NAME = "liftlog";
const STORE = "pending_sets";

let dbPromise = null;

function openDb() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        req.result.createObjectStore(STORE, { keyPath: "client_uuid" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbPromise;
}

function asPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function store(mode) {
  const db = await openDb();
  return db.transaction(STORE, mode).objectStore(STORE);
}

export async function enqueueSet(workoutId, payload) {
  if (isNativeApp()) throw new Error("Android 組紀錄必須直接寫入 LocalStore");
  await asPromise(
    (await store("readwrite")).put({
      client_uuid: payload.client_uuid,
      workout_id: workoutId,
      payload,
      status: "pending",
      queued_at: Date.now(),
    }),
  );
}

export async function listQueued() {
  if (isNativeApp()) return [];
  const all = await asPromise((await store("readonly")).getAll());
  return all.sort((a, b) => a.queued_at - b.queued_at);
}

export async function queueCounts() {
  if (isNativeApp()) {
    const status = await globalThis.Capacitor?.Plugins?.LocalStore?.status?.();
    return { pending: status?.pendingMutations ?? 0, failed: 0 };
  }
  const all = await listQueued();
  return {
    pending: all.filter((e) => e.status === "pending").length,
    failed: all.filter((e) => e.status === "failed").length,
  };
}

async function removeEntry(clientUuid) {
  await asPromise((await store("readwrite")).delete(clientUuid));
}

/** F16：從佇列移除未同步的一組（刪除尚未上傳的組）。編輯未同步組則直接 enqueueSet 覆蓋同 client_uuid。 */
export async function removeQueued(clientUuid) {
  if (isNativeApp()) return;
  await removeEntry(clientUuid);
}

async function markFailed(entry) {
  await asPromise((await store("readwrite")).put({ ...entry, status: "failed" }));
}

/** 重放 pending 佇列。logSet = api.logSet。回傳成功補傳的 [{client_uuid, saved}] 清單
 *  （saved＝server 回的 SetOut，含 id）——呼叫端要用它把 id 寫回畫面上的組，
 *  否則同步後那筆仍缺 id 會被當「未同步」，之後刪/改打不到伺服器。
 *  網路仍斷（status 0）或 server 暫時故障（5xx）→ 中止保留，之後再試；
 *  token 失效（401）→ 上拋讓 guard() 導回 setup 重新輸入，佇列原封保留；
 *  永久性 4xx（404/400/409 = workout 被刪、資料壞）→ 標 failed 供手動捨棄，不無限重試。 */
export async function flushQueue(logSet) {
  if (isNativeApp()) return [];
  const entries = (await listQueued()).filter((e) => e.status === "pending");
  const synced = [];
  for (const entry of entries) {
    try {
      const saved = await logSet(entry.workout_id, entry.payload);
      await removeEntry(entry.client_uuid);
      synced.push({ client_uuid: entry.client_uuid, saved });
    } catch (err) {
      if (err && err.status === 401) throw err;
      if (err && (err.status === 0 || err.status >= 500)) break;
      await markFailed(entry);
    }
  }
  return synced;
}

/** 捨棄所有 failed 項（單一交易，全刪或全不刪）。回傳被捨棄的 client_uuid 清單。 */
export async function discardFailed() {
  if (isNativeApp()) return [];
  const failed = (await listQueued()).filter((e) => e.status === "failed");
  if (failed.length === 0) return [];
  const objectStore = await store("readwrite");
  await Promise.all(failed.map((entry) => asPromise(objectStore.delete(entry.client_uuid))));
  return failed.map((entry) => entry.client_uuid);
}

// ---------- F91 ④：離線時「結束訓練」的補送佇列 ----------
//
// 用 localStorage 而不是上面那顆 IndexedDB：這裡只存一小串 workout id，
// 沒有 payload、沒有狀態機，同步讀寫反而讓補送邏輯簡單得多。
// 端點是冪等的，所以重放安全——重複送只會拿到同一個 ended_at。

const PENDING_ENDS_KEY = "liftlog.pendingEnds";

/**
 * 每筆是 `{id, mode}`：`mode` 為 "end"（標記結束）或 "delete"（刪掉空 workout）。
 * 舊格式是純數字陣列，一律當成 "end"（那時還沒有 delete 這條路）。
 */
function readPendingEnds() {
  try {
    const raw = JSON.parse(localStorage.getItem(PENDING_ENDS_KEY));
    if (!Array.isArray(raw)) return [];
    return raw
      .map((e) => (Number.isInteger(e) ? { id: e, mode: "end" } : e))
      .filter((e) => e && Number.isInteger(e.id) && (e.mode === "end" || e.mode === "delete"));
  } catch {
    return [];
  }
}

function writePendingEnds(entries) {
  if (entries.length === 0) localStorage.removeItem(PENDING_ENDS_KEY);
  else localStorage.setItem(PENDING_ENDS_KEY, JSON.stringify(entries));
}

/**
 * 收尾請求沒送成功 → 記下來等回線上補送。
 *
 * `mode` 一定要跟著記：F92 ⑥ 的空 workout 該被**刪掉**，只記 id 的話回線上會補成
 * 「標記結束」，那場空的就永遠留在資料庫（Codex P2）。
 */
export function rememberPendingEnd(workoutId, mode = "end") {
  if (isNativeApp()) return;
  const entries = readPendingEnds();
  const found = entries.find((e) => e.id === workoutId);
  if (!found) writePendingEnds([...entries, { id: workoutId, mode }]);
  else if (found.mode !== mode) {
    // 同一場先記了 end 又要 delete（或反之）→ 以最後一次為準
    writePendingEnds(entries.map((e) => (e.id === workoutId ? { id: e.id, mode } : e)));
  }
}

export function listPendingEnds() {
  if (isNativeApp()) return [];
  return readPendingEnds();
}

/**
 * 重放待補送的結束請求。`endWorkout` = api.endWorkout。
 *
 * 錯誤分類與 flushQueue 一致：401 上拋交 guard；連不上／5xx 留著下次再試；
 * 永久性 4xx（404＝workout 已被刪）就不必再送了，直接移除。
 */
export async function flushPendingEnds(endWorkout, deleteWorkout) {
  if (isNativeApp()) return;
  const done = new Set();

  // 寫回時**重讀當下的清單**再扣掉已處理的，不能拿函式開頭的快照覆蓋——
  // 每個 await 之間使用者都可能又結束一場，rememberPendingEnd() 會寫進同一個 key，
  // 用舊快照寫回會把剛加入的那筆抹掉，那場的結束事件就永遠送不出去（Codex P2）。
  const commit = () => writePendingEnds(readPendingEnds().filter((e) => !done.has(e.id)));

  /** true＝這筆處理完了；false＝留著下次；throw＝上拋給呼叫端。 */
  const attempt = async (fn, id) => {
    try {
      await fn(id);
      return true;
    } catch (err) {
      if (err && err.status === 401) {
        commit();
        throw err;
      }
      if (err && (err.status === 0 || err.status >= 500)) return null; // 連不上／5xx：留著
      if (err && err.status === 409) return "conflict"; // 刪不得（伺服器上其實有組）
      return true; // 404 等永久性 4xx：那場已經不在了
    }
  };

  for (const { id, mode } of readPendingEnds()) {
    if (mode === "delete" && deleteWorkout) {
      const r = await attempt(deleteWorkout, id);
      if (r === null) {
        commit();
        return;
      }
      if (r !== "conflict") {
        done.add(id);
        continue;
      }
      // 409＝別台在同一場記過組 → 這場不該刪，退回標記結束
    }
    const r = await attempt(endWorkout, id);
    if (r === null) {
      commit();
      return;
    }
    done.add(id);
  }
  commit();
}
