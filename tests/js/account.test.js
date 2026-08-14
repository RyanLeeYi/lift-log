import assert from "node:assert/strict";
import test from "node:test";

import {
  completePendingAccountWipe,
  finishNativeSignOut,
  markPendingAccountWipe,
} from "../../app/static/js/account.js";

test("native sign-out wipes local data before invalidating the session", async () => {
  const calls = [];
  await finishNativeSignOut({
    wipe: async () => calls.push("wipe"),
    signOut: async () => calls.push("sign-out"),
    reload: () => calls.push("reload"),
  });
  assert.deepEqual(calls, ["wipe", "sign-out", "reload"]);
});

test("native sign-out keeps the session when local wipe fails", async () => {
  const calls = [];
  await assert.rejects(() => finishNativeSignOut({
    wipe: async () => { calls.push("wipe"); throw new Error("disk busy"); },
    signOut: async () => calls.push("sign-out"),
    reload: () => calls.push("reload"),
  }));
  assert.deepEqual(calls, ["wipe"]);
});

test("committed account deletion keeps a retry marker until local wipe succeeds", async () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  markPendingAccountWipe(storage);
  await assert.rejects(() => completePendingAccountWipe({
    storage,
    wipe: async () => { throw new Error("disk busy"); },
  }));
  assert.equal(values.size, 1);
  assert.equal(await completePendingAccountWipe({ storage, wipe: async () => {} }), true);
  assert.equal(values.size, 0);
});
