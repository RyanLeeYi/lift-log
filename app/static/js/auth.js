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

// ---------- Web session（F146）----------
//
// 網頁不存 access token：session 走 Secure HttpOnly cookie，JS 讀不到也就偷不走。
// 手上只留 CSRF token，而它由 server 從 session id 推導，重整後再問一次就好。

let webCsrfToken = "";

export function getWebCsrfToken() {
  return webCsrfToken;
}

/** 開站時問一次：cookie 還有效就拿回 CSRF token，失效就是未登入。 */
export async function restoreWebSession({ fetchImpl = fetch } = {}) {
  try {
    const session = await jsonRequest(fetchImpl, "/api/auth/session", {
      credentials: "include",
    });
    webCsrfToken = session.csrf_token || "";
    return { authenticated: Boolean(webCsrfToken), user: session.user };
  } catch (error) {
    if (error.status === 401) {
      webCsrfToken = "";
      return { authenticated: false };
    }
    throw error; // 503／連不上不等於未登入——不能把離線畫成「請重新登入」
  }
}

export async function signInWeb(credential, { fetchImpl = fetch } = {}) {
  if (!credential?.idToken) throw new AuthError("沒有拿到 Google 憑證");
  const issued = await jsonRequest(fetchImpl, "/api/auth/google", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id_token: credential.idToken,
      nonce: credential.nonce,
      device_id: credential.deviceId,
      device_name: credential.deviceName ?? "Web",
      client: "web",
    }),
  });
  webCsrfToken = issued.csrf_token || "";
  return issued;
}

export async function signOutWeb({ fetchImpl = fetch } = {}) {
  try {
    await jsonRequest(fetchImpl, "/api/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": webCsrfToken },
    });
  } finally {
    webCsrfToken = ""; // 伺服器沒回應也要把本機這半邊清掉，不留一個看似已登入的畫面
  }
}

export function webSignInNonce() {
  return nonce();
}

const GSI_SRC = "https://accounts.google.com/gsi/client";
const WEB_DEVICE_KEY = "liftlog.web_device_id";

/** 每個瀏覽器一個固定 device id——換一顆就會在帳號底下長出一台新裝置。 */
export function webDeviceId(storage = localStorage) {
  let id = storage.getItem(WEB_DEVICE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    storage.setItem(WEB_DEVICE_KEY, id);
  }
  return id;
}

/** GSI 只在網頁真的要登入時才載入——不放進 index.html，APK 就不會多一個外部相依。 */
export function loadGoogleIdentity({ doc = document } = {}) {
  if (globalThis.google?.accounts?.id) return Promise.resolve(globalThis.google.accounts.id);
  return new Promise((resolve, reject) => {
    const existing = doc.querySelector(`script[src="${GSI_SRC}"]`);
    const script = existing ?? doc.createElement("script");
    const done = () => {
      if (globalThis.google?.accounts?.id) resolve(globalThis.google.accounts.id);
      else reject(new AuthError("載入 Google 登入失敗——檢查網路後再試一次"));
    };
    script.addEventListener("load", done, { once: true });
    script.addEventListener(
      "error",
      () => reject(new AuthError("載入 Google 登入失敗——檢查網路後再試一次")),
      { once: true },
    );
    if (!existing) {
      script.src = GSI_SRC;
      script.async = true;
      doc.head.appendChild(script);
    }
  });
}

/**
 * F148：只拿一顆新鮮的 Google id_token＋nonce，不建 session。
 * `signInWithGoogleWeb`（登入）與匯出／刪帳的近期身分重驗共用這一段——
 * 差別只在拿到憑證後要不要接著換 session，不是憑證本身怎麼拿。
 */
export async function promptGoogleReauth({
  fetchImpl = fetch,
  identity = null,
  timeoutMs = 60_000,
} = {}) {
  const config = await jsonRequest(fetchImpl, "/api/auth/config");
  if (!config.google_client_id) throw new AuthError("伺服器尚未設定 Google 登入");
  const gsi = identity ?? (await loadGoogleIdentity());
  const challenge = nonce();
  const credential = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new AuthError("驗證逾時，請再試一次")), timeoutMs);
    gsi.initialize({
      client_id: config.google_client_id,
      nonce: challenge,
      callback: (value) => {
        clearTimeout(timer);
        resolve(value?.credential);
      },
    });
    gsi.prompt();
  });
  if (!credential) throw new AuthError("沒有拿到 Google 憑證");
  return { idToken: credential, nonce: challenge };
}

/**
 * 網頁版 Google 登入：GSI 拿 id_token → 換成 HttpOnly cookie session。
 * nonce 由 `promptGoogleReauth` 產生並隨 id_token 一起送回 server 比對，擋掉重放別處拿到的憑證。
 */
export async function signInWithGoogleWeb({
  fetchImpl = fetch,
  identity = null,
  timeoutMs = 60_000,
} = {}) {
  const { idToken, nonce: challenge } = await promptGoogleReauth({
    fetchImpl, identity, timeoutMs,
  });
  return signInWeb(
    { idToken, nonce: challenge, deviceId: webDeviceId(), deviceName: "Web" },
    { fetchImpl },
  );
}

/** F148：原生版對應 `promptGoogleReauth`——同一顆 Credential Manager 憑證也帶回 deviceId/deviceName。 */
async function promptGoogleCredentialNative({ plugin = authPlugin(), fetchImpl = fetch } = {}) {
  if (!plugin) throw new AuthError("這個 APK 不支援 Google 登入，請更新 App");
  const config = await jsonRequest(fetchImpl, "/api/auth/config");
  if (!config.google_client_id) throw new AuthError("伺服器尚未設定 Google 登入");
  const challenge = nonce();
  const google = await plugin.googleSignIn({
    clientId: config.google_client_id,
    nonce: challenge,
  });
  return {
    idToken: google.idToken,
    nonce: challenge,
    deviceId: google.deviceId,
    deviceName: google.deviceName,
  };
}

export async function promptGoogleReauthNative(options = {}) {
  const { idToken, nonce: challenge } = await promptGoogleCredentialNative(options);
  return { idToken, nonce: challenge };
}

export async function signInNative({
  plugin = authPlugin(),
  fetchImpl = fetch,
  now = Date.now(),
} = {}) {
  const { idToken, nonce: challenge, deviceId, deviceName } = await promptGoogleCredentialNative({
    plugin, fetchImpl,
  });
  const issued = await jsonRequest(fetchImpl, "/api/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id_token: idToken,
      nonce: challenge,
      device_id: deviceId,
      device_name: deviceName,
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

/**
 * F148：原生登出。`/api/auth/logout` 本來就只憑 Bearer／cookie 解析 session，不分
 * android/web——不必另開一支端點。清 token（記憶體＋加密儲存）這步無論伺服器端撤銷
 * 成不成功都要做（理由同 `signOutWeb`：伺服器沒回應也不能留著一個看似仍登入的裝置，
 * 更不能讓 SecureStore 裡的 refresh token 活著、下次啟動又悄悄復原 session）。
 */
export async function signOutNative({ plugin = authPlugin(), fetchImpl = fetch } = {}) {
  try {
    await jsonRequest(fetchImpl, "/api/auth/logout", {
      method: "POST",
      headers: { Authorization: `Bearer ${nativeAccessToken}` },
    });
  } finally {
    nativeAccessToken = "";
    await plugin?.clearSession();
  }
}
