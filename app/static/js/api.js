// REST client：所有請求帶 Bearer token；錯誤統一丟 ApiError（含 server 的 {error} 訊息）。
// 路徑一律以 / 開頭；apiBase() 在 web 版回空字串（同源相對路徑），app 版回公開站（F61 ③）。

import { apiBase } from "./env.js";

const TOKEN_KEY = "liftlog.token";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

async function request(method, path, body) {
  let resp;
  try {
    resp = await fetch(apiBase() + path, {
      method,
      headers: {
        Authorization: `Bearer ${getToken()}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "連不上伺服器——檢查網路後再試一次");
  }
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(resp.status, data.error || `HTTP ${resp.status}`);
  return data;
}

export const api = {
  searchExercises: (q) =>
    request("GET", q ? `/api/exercises?q=${encodeURIComponent(q)}` : "/api/exercises"),
  createExercise: (payload) => request("POST", "/api/exercises", payload), // F10 自訂動作
  exercisesWithData: () => request("GET", "/api/exercises?has_data=true"), // F39 動作表現瀏覽
  // excludeWorkoutId：排除進行中的 workout → 「上次」看前一次訓練而非本次（F32）
  lastSets: (exerciseId, excludeWorkoutId) =>
    request(
      "GET",
      excludeWorkoutId != null
        ? `/api/exercises/${exerciseId}/last-sets?exclude_workout=${excludeWorkoutId}`
        : `/api/exercises/${exerciseId}/last-sets`,
    ),
  createWorkout: (payload = {}) => request("POST", "/api/workouts", payload),
  listTemplates: () => request("GET", "/api/templates"),
  createTemplate: (payload) => request("POST", "/api/templates", payload),
  updateTemplate: (templateId, payload) =>
    request("PUT", `/api/templates/${templateId}`, payload),
  deleteTemplate: (templateId) => request("DELETE", `/api/templates/${templateId}`),
  logSet: (workoutId, payload) => request("POST", `/api/workouts/${workoutId}/sets`, payload),
  updateSet: (setId, payload) => request("PATCH", `/api/sets/${setId}`, payload), // F16 原位編輯
  deleteSet: (setId) => request("DELETE", `/api/sets/${setId}`), // F16 軟刪

  // F35/F36 動作詳情：某動作 [from,to] 內每次訓練的全部組＋全期 PR
  exerciseHistory: (exerciseId, from, to) =>
    request("GET", `/api/exercises/${exerciseId}/history?from=${from}&to=${to}`),

  workoutDetail: (workoutId) => request("GET", `/api/workouts/${workoutId}`),
  // F91：標記訓練結束（冪等）。伺服器端的結束狀態，讓另一台裝置的舊快取不會把它接下去。
  endWorkout: (workoutId) => request("POST", `/api/workouts/${workoutId}/end`),
  listWorkouts: (start, end) => request("GET", `/api/workouts?start=${start}&end=${end}`),
  calendarStats: (year, month) =>
    request("GET", `/api/stats/calendar?year=${year}&month=${month}`),
  // F56：選填區間（後端已支援 start／end）。不帶＝全部（自體重動作抓最新體重時仍用不帶的形式）
  // F56：選填區間（後端已支援 start／end）。不帶＝全部（exercise-detail 抓自體重時用不帶的形式）。
  // review P3-2：傳了 range 卻欠欄位時明確拋錯——原本會靜默降級成「查全部」，症狀是悄悄顯示全部資料
  listBodyMetrics: (range) => {
    if (range && !(range.from && range.to)) {
      throw new Error("listBodyMetrics: range 需要同時有 from 與 to");
    }
    return request(
      "GET",
      range ? `/api/body-metrics?start=${range.from}&end=${range.to}` : "/api/body-metrics",
    );
  },
  // F58：資料起訖（不回資料列）——前端用它判斷哪些區間檔位有意義
  bodyMetricBounds: () => request("GET", "/api/body-metrics/range"),
  logBodyMetric: (payload) => request("POST", "/api/body-metrics", payload),
  deleteBodyMetric: (dateIso) => request("DELETE", `/api/body-metrics/${dateIso}`), // F17 硬刪
  listDailyStatus: (start, end) => request("GET", `/api/daily-status?start=${start}&end=${end}`),
  logDailyStatus: (payload) => request("POST", "/api/daily-status", payload), // F18 編輯＝同日覆蓋
  deleteDailyStatus: (dateIso) => request("DELETE", `/api/daily-status/${dateIso}`), // F18 硬刪
  // F67：app 版自我更新——伺服器上最新的 APK 版本（沒有發佈版本時回 404）
  appLatest: () => request("GET", "/api/app/latest"),
  // F83：今日菜單一次取多個動作的「上次」代表值（逐個打 last-sets 會是 N 次往返）
  lastSetValues: (ids, excludeWorkoutId) =>
    request(
      "GET",
      `/api/exercises/last-set-values?ids=${ids.join(",")}` +
        (excludeWorkoutId ? `&exclude_workout=${excludeWorkoutId}` : ""),
    ),
  // F80/F81：今天排到什麼、本週進度、上次訓練（首頁一次請求拿齊）
  scheduleToday: () => request("GET", "/api/schedule/today"),
  getSetting: (key) => request("GET", `/api/settings/${key}`),
  putSetting: (key, value) => request("PUT", `/api/settings/${key}`, { value: String(value) }),
  // F31 Web Push（休息結束通知）
  pushPublicKey: () => request("GET", "/api/push/public-key"),
  pushSubscribe: (sub) => request("POST", "/api/push/subscribe", sub),
  scheduleRest: (seconds) => request("POST", "/api/push/rest-timer", { seconds }),
  cancelRest: () => request("POST", "/api/push/rest-timer/cancel"),
};
