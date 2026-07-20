// REST client：所有請求帶 Bearer token；錯誤統一丟 ApiError（含 server 的 {error} 訊息）。

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
    resp = await fetch(path, {
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
  lastSets: (exerciseId) => request("GET", `/api/exercises/${exerciseId}/last-sets`),
  createWorkout: (payload = {}) => request("POST", "/api/workouts", payload),
  listTemplates: () => request("GET", "/api/templates"),
  createTemplate: (payload) => request("POST", "/api/templates", payload),
  updateTemplate: (templateId, payload) =>
    request("PUT", `/api/templates/${templateId}`, payload),
  deleteTemplate: (templateId) => request("DELETE", `/api/templates/${templateId}`),
  logSet: (workoutId, payload) => request("POST", `/api/workouts/${workoutId}/sets`, payload),
  updateSet: (setId, payload) => request("PATCH", `/api/sets/${setId}`, payload), // F16 原位編輯
  deleteSet: (setId) => request("DELETE", `/api/sets/${setId}`), // F16 軟刪

  workoutDetail: (workoutId) => request("GET", `/api/workouts/${workoutId}`),
  listWorkouts: (start, end) => request("GET", `/api/workouts?start=${start}&end=${end}`),
  calendarStats: (year, month) =>
    request("GET", `/api/stats/calendar?year=${year}&month=${month}`),
  listBodyMetrics: () => request("GET", "/api/body-metrics"),
  logBodyMetric: (payload) => request("POST", "/api/body-metrics", payload),
  deleteBodyMetric: (dateIso) => request("DELETE", `/api/body-metrics/${dateIso}`), // F17 硬刪
  listDailyStatus: (start, end) => request("GET", `/api/daily-status?start=${start}&end=${end}`),
  logDailyStatus: (payload) => request("POST", "/api/daily-status", payload), // F18 編輯＝同日覆蓋
  deleteDailyStatus: (dateIso) => request("DELETE", `/api/daily-status/${dateIso}`), // F18 硬刪
  // F31 Web Push（休息結束通知）
  pushPublicKey: () => request("GET", "/api/push/public-key"),
  pushSubscribe: (sub) => request("POST", "/api/push/subscribe", sub),
  scheduleRest: (seconds) => request("POST", "/api/push/rest-timer", { seconds }),
  cancelRest: () => request("POST", "/api/push/rest-timer/cancel"),
};
