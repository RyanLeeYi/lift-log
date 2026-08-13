import assert from "node:assert/strict";
import test from "node:test";

import {
  initializeNativeSync,
  normalizeSyncStatus,
  readNativeConflicts,
  readNativeSyncStatus,
  resolveNativeConflict,
  runNativeSync,
} from "../../app/static/js/native-sync.js";

test("sync status normalizes bridge values and preserves bootstrap gate", () => {
  assert.deepEqual(normalizeSyncStatus({
    state: "offline",
    pending: "3",
    failed: 1,
    cursor: "42",
    lastSyncedAt: "1000",
    nextSyncAt: "5000",
    bootstrapComplete: false,
  }), {
    state: "offline",
    pending: 3,
    failed: 1,
    cursor: 42,
    lastSyncedAt: 1000,
    errorCode: null,
    nextSyncAt: 5000,
    bootstrapComplete: false,
    conflicts: 0,
  });
});

test("conflict inbox reads items and forwards the user's choice verbatim", async () => {
  const calls = [];
  const plugin = {
    conflicts: async () => {
      calls.push(["conflicts"]);
      return { items: [{ conflictId: "c1", entityType: "set", reason: "version_mismatch" }] };
    },
    resolveConflict: async (args) => {
      calls.push(["resolveConflict", args]);
      return { state: "pending", pending: 1, bootstrapComplete: true, conflicts: 0 };
    },
  };

  const items = await readNativeConflicts({ plugin });
  assert.equal(items.length, 1);
  assert.equal(items[0].conflictId, "c1");

  const status = await resolveNativeConflict(
    { conflictId: "c1", choice: "local", mutationId: "m1" }, { plugin },
  );
  assert.equal(status.conflicts, 0);
  assert.deepEqual(calls, [
    ["conflicts"],
    ["resolveConflict", { conflictId: "c1", choice: "local", mutationId: "m1" }],
  ]);
});

test("conflict resolution rejects anything but an explicit local/server choice", async () => {
  const plugin = { resolveConflict: async () => assert.fail("不該打到 bridge") };
  await assert.rejects(
    () => resolveNativeConflict({ conflictId: "c1", choice: "newest", mutationId: "m1" }, { plugin }),
    /不支援的衝突解決方式/,
  );
});

test("initialize, status, and manual sync call distinct native methods", async () => {
  const calls = [];
  const plugin = {
    initialize: async ({ baseUrl }) => {
      calls.push(["initialize", baseUrl]);
      return { state: "pending", pending: 2, bootstrapComplete: false };
    },
    status: async () => {
      calls.push(["status"]);
      return { state: "pending", pending: 1, bootstrapComplete: false };
    },
    syncNow: async () => {
      calls.push(["syncNow"]);
      return { state: "synced", pending: 0, bootstrapComplete: true };
    },
  };

  assert.equal((await initializeNativeSync({ plugin, baseUrl: "https://lift.test" })).pending, 2);
  assert.equal((await readNativeSyncStatus({ plugin })).pending, 1);
  assert.equal((await runNativeSync({ plugin })).bootstrapComplete, true);
  assert.deepEqual(calls, [
    ["initialize", "https://lift.test"],
    ["status"],
    ["syncNow"],
  ]);
});
