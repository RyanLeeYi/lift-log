import assert from "node:assert/strict";
import test from "node:test";

import { restoreNativeSession, signInNative } from "../../app/static/js/auth.js";

const response = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

test("valid access token does not rotate early", async () => {
  const plugin = {
    loadSession: async () => ({
      accessToken: "access",
      refreshToken: "refresh",
      accessExpiresAt: 200_000,
      deviceId: "11111111-1111-4111-8111-111111111111",
    }),
  };
  const result = await restoreNativeSession({
    plugin,
    now: 100_000,
    fetchImpl: async () => assert.fail("must not refresh"),
  });
  assert.deepEqual(result, { authenticated: true, accessToken: "access" });
});

test("expired access token rotates and saves the pair", async () => {
  let saved;
  const plugin = {
    loadSession: async () => ({
      accessToken: "old-access",
      refreshToken: "old-refresh",
      accessExpiresAt: 1,
      deviceId: "11111111-1111-4111-8111-111111111111",
    }),
    saveSession: async (session) => { saved = session; },
  };
  const result = await restoreNativeSession({
    plugin,
    now: 1_000,
    fetchImpl: async () => response(200, {
      access_token: "new-access",
      refresh_token: "new-refresh",
      expires_in: 900,
    }),
  });
  assert.equal(result.accessToken, "new-access");
  assert.deepEqual(saved, {
    accessToken: "new-access",
    refreshToken: "new-refresh",
    accessExpiresAt: 901_000,
  });
});

test("refresh replay rejection clears the compromised session", async () => {
  let cleared = false;
  const plugin = {
    loadSession: async () => ({
      refreshToken: "used-refresh",
      deviceId: "11111111-1111-4111-8111-111111111111",
    }),
    clearSession: async () => { cleared = true; },
  };
  const result = await restoreNativeSession({
    plugin,
    fetchImpl: async () => response(401, { error: "unauthorized" }),
  });
  assert.deepEqual(result, { authenticated: false });
  assert.equal(cleared, true);
});

test("offline refresh keeps a previously authenticated local account usable", async () => {
  const plugin = {
    loadSession: async () => ({
      refreshToken: "refresh",
      deviceId: "11111111-1111-4111-8111-111111111111",
    }),
  };
  const result = await restoreNativeSession({
    plugin,
    fetchImpl: async () => { throw new Error("offline"); },
  });
  assert.deepEqual(result, { authenticated: true, offline: true });
});

test("Google nonce is identical in Credential Manager and server request", async () => {
  let credentialNonce;
  let loginBody;
  let saved;
  const plugin = {
    googleSignIn: async ({ nonce }) => {
      credentialNonce = nonce;
      return {
        idToken: "google-id-token",
        deviceId: "11111111-1111-4111-8111-111111111111",
        deviceName: "Pixel",
      };
    },
    saveSession: async (session) => { saved = session; },
  };
  let call = 0;
  await signInNative({
    plugin,
    now: 1_000,
    fetchImpl: async (_url, init) => {
      call += 1;
      if (call === 1) return response(200, { google_client_id: "client-id" });
      loginBody = JSON.parse(init.body);
      return response(200, {
        access_token: "access",
        refresh_token: "refresh",
        expires_in: 900,
      });
    },
  });
  assert.equal(loginBody.nonce, credentialNonce);
  assert.ok(credentialNonce.length >= 32);
  assert.equal(loginBody.client, "android");
  assert.equal(saved.refreshToken, "refresh");
});
