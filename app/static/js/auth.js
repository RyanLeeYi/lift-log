import { apiBase } from "./env.js";

const authPlugin = () => globalThis.Capacitor?.Plugins?.AuthSession;
let nativeAccessToken = "";

export function getNativeAccessToken() {
  return nativeAccessToken;
}

class AuthError extends Error {}

async function jsonRequest(fetchImpl, path, init = {}) {
  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);
  try {
    response = await fetchImpl(apiBase() + path, { ...init, signal: controller.signal });
  } catch {
    throw new AuthError("連不上登入服務——離線資料仍可使用");
  } finally {
    clearTimeout(timeout);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new AuthError(body.error || `登入服務錯誤（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function nonce() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

export async function restoreNativeSession({
  plugin = authPlugin(),
  fetchImpl = fetch,
  now = Date.now(),
} = {}) {
  if (!plugin) throw new AuthError("這個 APK 不支援 Google 登入，請更新 App");
  const stored = await plugin.loadSession();
  if (!stored.refreshToken) {
    nativeAccessToken = "";
    return { authenticated: false };
  }
  if (stored.accessToken && stored.accessExpiresAt > now + 30_000) {
    nativeAccessToken = stored.accessToken;
    return { authenticated: true, accessToken: stored.accessToken };
  }
  nativeAccessToken = "";
  try {
    const rotated = await jsonRequest(fetchImpl, "/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        refresh_token: stored.refreshToken,
        device_id: stored.deviceId,
      }),
    });
    const accessExpiresAt = now + rotated.expires_in * 1000;
    await plugin.saveSession({
      accessToken: rotated.access_token,
      refreshToken: rotated.refresh_token,
      accessExpiresAt,
    });
    nativeAccessToken = rotated.access_token;
    return { authenticated: true, accessToken: rotated.access_token };
  } catch (error) {
    if (error.status === 401) {
      await plugin.clearSession();
      nativeAccessToken = "";
      return { authenticated: false };
    }
    // 已成功登入過的 Android 在伺服器離線時仍可完整使用本機資料。
    return { authenticated: true, offline: true };
  }
}

export async function signInNative({
  plugin = authPlugin(),
  fetchImpl = fetch,
  now = Date.now(),
} = {}) {
  if (!plugin) throw new AuthError("這個 APK 不支援 Google 登入，請更新 App");
  const config = await jsonRequest(fetchImpl, "/api/auth/config");
  if (!config.google_client_id) throw new AuthError("伺服器尚未設定 Google 登入");
  const challenge = nonce();
  const google = await plugin.googleSignIn({
    clientId: config.google_client_id,
    nonce: challenge,
  });
  const issued = await jsonRequest(fetchImpl, "/api/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id_token: google.idToken,
      nonce: challenge,
      device_id: google.deviceId,
      device_name: google.deviceName,
      client: "android",
    }),
  });
  await plugin.saveSession({
    accessToken: issued.access_token,
    refreshToken: issued.refresh_token,
    accessExpiresAt: now + issued.expires_in * 1000,
  });
  nativeAccessToken = issued.access_token;
}
