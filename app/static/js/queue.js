// 離線佇列：送不出去的組先進 IndexedDB，恢復連線後照入列順序重放。
// 靠 client_uuid 冪等不重複；4xx（如 workout 已被刪）標 failed 留佇列供手動捨棄，不無限重試。

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
  const all = await asPromise((await store("readonly")).getAll());
  return all.sort((a, b) => a.queued_at - b.queued_at);
}

export async function queueCounts() {
  const all = await listQueued();
  return {
    pending: all.filter((e) => e.status === "pending").length,
    failed: all.filter((e) => e.status === "failed").length,
  };
}

async function removeEntry(clientUuid) {
  await asPromise((await store("readwrite")).delete(clientUuid));
}

async function markFailed(entry) {
  await asPromise((await store("readwrite")).put({ ...entry, status: "failed" }));
}

/** 重放 pending 佇列。logSet = api.logSet。回傳成功補傳筆數。
 *  網路仍斷（status 0）或 server 暫時故障（5xx）→ 中止保留，之後再試；
 *  token 失效（401）→ 上拋讓 guard() 導回 setup 重新輸入，佇列原封保留；
 *  永久性 4xx（404/400/409 = workout 被刪、資料壞）→ 標 failed 供手動捨棄，不無限重試。 */
export async function flushQueue(logSet) {
  const entries = (await listQueued()).filter((e) => e.status === "pending");
  let synced = 0;
  for (const entry of entries) {
    try {
      await logSet(entry.workout_id, entry.payload);
      await removeEntry(entry.client_uuid);
      synced += 1;
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
  const failed = (await listQueued()).filter((e) => e.status === "failed");
  if (failed.length === 0) return [];
  const objectStore = await store("readwrite");
  await Promise.all(failed.map((entry) => asPromise(objectStore.delete(entry.client_uuid))));
  return failed.map((entry) => entry.client_uuid);
}
