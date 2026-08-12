import assert from "node:assert/strict";
import test from "node:test";

import {
  initializeNativeSync,
  normalizeSyncStatus,
  readNativeSyncStatus,
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
  });
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
