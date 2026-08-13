import assert from "node:assert/strict";
import test from "node:test";

import {
  getWebCsrfToken,
  restoreNativeSession,
  restoreWebSession,
  signInNative,
  signInWeb,
  signOutWeb,
} from "../../app/static/js/auth.js";
import { authHeaders } from "../../app/static/js/api.js";

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

// ---------- F146：Web session ----------

test("web sign-in posts client=web with credentials and keeps only the csrf token", async () => {
  let init = null;
  await signInWeb(
    { idToken: "google-id-token", nonce: "n1", deviceId: "web-device" },
    {
      fetchImpl: async (_url, options) => {
        init = options;
        return response(200, { csrf_token: "csrf-1", user: { id: "u1" } });
      },
    },
  );
  const body = JSON.parse(init.body);
  assert.equal(body.client, "web");
  assert.equal(init.credentials, "include");
  assert.equal(getWebCsrfToken(), "csrf-1");
  // access/refresh token 不該出現在網頁這邊——session 全靠 HttpOnly cookie
  assert.equal(body.access_token, undefined);
});

test("restoring a web session recovers the csrf token, and 401 means signed out", async () => {
  const restored = await restoreWebSession({
    fetchImpl: async () => response(200, { csrf_token: "csrf-2", user: { id: "u1" } }),
  });
  assert.equal(restored.authenticated, true);
  assert.equal(getWebCsrfToken(), "csrf-2");

  const signedOut = await restoreWebSession({ fetchImpl: async () => response(401, {}) });
  assert.equal(signedOut.authenticated, false);
  assert.equal(getWebCsrfToken(), "");
});

test("server outage while restoring is not reported as signed out", async () => {
  await restoreWebSession({
    fetchImpl: async () => response(200, { csrf_token: "csrf-3", user: { id: "u1" } }),
  });
  await assert.rejects(
    () => restoreWebSession({ fetchImpl: async () => response(503, {}) }),
  );
  assert.equal(getWebCsrfToken(), "csrf-3"); // 仍視為已登入，不把離線畫成請重新登入
});

test("sign-out clears the local csrf token even when the server call fails", async () => {
  await restoreWebSession({
    fetchImpl: async () => response(200, { csrf_token: "csrf-4", user: { id: "u1" } }),
  });
  await assert.rejects(() => signOutWeb({ fetchImpl: async () => response(500, {}) }));
  assert.equal(getWebCsrfToken(), "");
});

test("api requests use cookie plus csrf header when a web session exists", async () => {
  await restoreWebSession({
    fetchImpl: async () => response(200, { csrf_token: "csrf-5", user: { id: "u1" } }),
  });
  const web = authHeaders({ any: true });
  assert.equal(web.headers["X-CSRF-Token"], "csrf-5");
  assert.equal(web.credentials, "include");
  assert.equal(web.headers.Authorization, undefined);

  const legacy = authHeaders(null, { csrf: "", token: "legacy-token" });
  assert.equal(legacy.headers.Authorization, "Bearer legacy-token");
  assert.equal(legacy.credentials, undefined);
});
