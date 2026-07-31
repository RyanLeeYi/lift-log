// lift-log 記錄頁：setup → home →（templateSelect）→ picker → logger，全部由 render() 重繪；
// 課表管理（templates / templateEdit）在 templates.js。

import { api, ApiError, getToken, setToken } from "./api.js";
import { captureBodyScroll, openBody, renderBody } from "./body.js";
import { openCalendar, renderCalendar } from "./calendar.js";
import { customExerciseModal } from "./custom-exercise.js";
import {
  checkForUpdate,
  dismissUpdate,
  downloadAndInstall,
  isDismissed,
} from "./app-update.js";
import { el, parseReps, parseWeight, RPE_WORDS, rpePicker, stepper } from "./dom.js";
// F76：結構性圖示一律走這裡（emoji 是彩色字形，跨平台不一致且吃不到 CSS 顏色）
import { icon, iconLabel } from "./icons.js";
import { switchRow } from "./switch-row.js";
import { apiBase, isNativeApp } from "./env.js";
import {
  detailReturnScreen,
  openExerciseDetail,
  renderExerciseDetail,
} from "./exercise-detail.js";
// F62：休息提醒改走 rest-notify 這層統一入口（web＝F31 Web Push／app＝手機端本機通知）
import {
  cancelRestNotify,
  cancelRestNotifyScheduleOnly,
  disableRestNotify,
  disableRestOverlay,
  enableRestNotify,
  enableRestOverlay,
  pauseRestNotify,
  refreshRestNotifyState,
  requestRestNotifyExact,
  resumeRestNotify,
  restNotifyDelayed,
  restNotifyEnabled,
  restNotifySupported,
  restOverlayEnabled,
  restOverlayPermitted,
  restOverlaySupported,
  restTimerRunning,
  scheduleRestNotify,
  subscribeRestControl,
  syncRestCardVisible,
} from "./rest-notify.js";
import {
  discardFailed,
  enqueueSet,
  flushPendingEnds,
  flushQueue,
  listQueued,
  queueCounts,
  rememberPendingEnd,
  removeQueued,
} from "./queue.js";
import {
  captureTemplateListScroll,
  hasUnsavedTemplate,
  openTemplates,
  renderTemplateEdit,
  renderTemplates,
  resetTemplateListScroll,
  restoreTemplateDraft,
  saveTemplateDraft,
} from "./templates.js";
import {
  APP_VERSION,
  DEFAULT_REST_HINT_SECONDS,
  clearActiveWorkout,
  exerciseAlias,
  exerciseName,
  getLang,
  pauseRest,
  restElapsedSeconds,
  restHintFor,
  restartRestFromNative,
  restPaused,
  restRemainingSeconds,
  restoreActiveWorkout,
  resumeRest,
  syncRestTargetFromNative,
  saveActiveWorkout,
  state,
  todayIso,
  toggleLang,
} from "./state.js";

const root = document.getElementById("app");
let restTicker = null;
let wakeLock = null; // R10：logger 畫面保持螢幕常亮，離開時釋放
let wakeLockPending = false; // request 進行中——完成時要重驗畫面狀態，避免離開後鎖洩漏
let restAlerted = false;
// F103 ③：浮動視窗按停止時凍結的「這輪已休息秒數」。按「再開始」時接回去——
// 停止再開始仍是同一輪休息，rest_seconds 要涵蓋整段而不是從停止那一刻重算。
let haltedRestElapsed = 0; // 本段休息是否已提醒過；調長目標後重新武裝
// F16/F19 done-list 行內編輯/單擊刪除（key＝已同步組的 id，未同步組退回 client_uuid）
let editDraft = null; // {key, weight, reps, rpe} 正在行內編輯的草稿
// F67：可用的更新（null＝沒有或還沒查完）與下載進度（0–1，null＝未在下載）。
// 只影響首頁顯示，訓練流程完全不碰。
let pendingUpdate = null;
let updateProgress = null;
let updateModalOpen = false; // F68：視窗開著（自動彈或由橫幅／版號點開）
let updateFlash = null; // F68 ⑦：手動檢查後的短暫提示（「已是最新版」）
let updateError = null; // F68 ⑤：更新失敗的訊息，顯示在視窗內（不是關窗再用頁面 banner）

function setRowKey(s) {
  return s.id != null ? `id:${s.id}` : `uuid:${s.client_uuid}`;
}

// ---------- 小工具 ----------

function todayLabel() {
  const now = new Date();
  return `${now.getMonth() + 1}/${now.getDate()}`;
}

function fmtClock(totalSeconds) {
  const m = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const s = String(totalSeconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function fmtRest(remaining) {
  // R10 倒數顯示：到 0 之後往上數。F84 ⑦ 起用「＋」而不是「−」——
  // 超時 15 秒是「多休了 15 秒」，減號讀起來像還剩負秒數，語意是反的。
  return remaining < 0 ? `+${fmtClock(-remaining)}` : fmtClock(remaining);
}

// F24：畫面角落的版本標記——手機載入哪版一眼可辨（快取過期會顯示舊版號）
// F93：這台服務是正式站還是測試站。/health 是免 auth 的，所以 setup 畫面（還沒有 token）
// 也顯示得出來——「我到底連到哪一站」正是那個當下最需要知道的事。
// null＝還沒問到（開站的第一瞬間或離線），那時不顯示，不要猜。
let envLabel = null;

// 只認得這兩個值。**不能把「非 prod」一律當成測試站**——`LIFTLOG_ENV` 打成
// `production` 之類的變體時，正式站會被標成紅字「測試環境」，使用者以為在動假資料，
// 那比沒有標示更危險（Codex P2）。未知值一律不顯示。
const ENV_LABELS = { prod: "正式環境", dev: "測試環境" };

async function loadEnvLabel() {
  try {
    const resp = await fetch(`${apiBase()}/health`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.env in ENV_LABELS && data.env !== envLabel) {
      envLabel = data.env;
      // renderUnlessTyping：這是背景查詢的結果，隨時可能在使用者打字時回來，
      // 而 render() 會 replaceChildren 重建整個畫面、清掉還沒進 state 的輸入
      // （setup 畫面的 token 就是這種）（Codex P2）。
      renderUnlessTyping();
    }
  } catch {
    /* 離線／連不上：不顯示，不要猜成正式站 */
  }
}

function envTag() {
  const text = ENV_LABELS[envLabel];
  if (!text) return [];
  return [
    el(
      "div",
      { class: `env-tag${envLabel === "dev" ? " env-tag-dev" : ""}` },
      [text],
    ),
  ];
}

function versionTag() {
  // F68 ③⑦：app 版的版號身兼三職——顯示目前版本、提示有新版（`v67 → v68`）、
  // 以及手動檢查的入口。原本另有一條更新橫幅，2026-07-28 回簽核拿掉：
  // 兩個入口重疊，而提示併進版號就不必多佔一行版面。
  // web 版維持純文字：那邊部署完自動到位，沒有「檢查更新」這回事。
  if (!isNativeApp()) return el("div", { class: "version-tag" }, [APP_VERSION]);
  // 環境標示由 envTag() 接在版號**下面**（見 settingsScreen），不併進這顆按鈕的文字——
  // app 版的版號兼任「有新版」提示與檢查入口，塞進去會讓 `v95 → v96` 更難讀。
  const hasUpdate = pendingUpdate !== null;
  return el(
    "button",
    {
      class: `version-tag version-tag-btn${hasUpdate ? " has-update" : ""}`,
      onclick: () =>
        guard(async () => {
          // 已經知道有更新就直接開窗，不必再問一次伺服器
          if (pendingUpdate) {
            updateModalOpen = true; // 手動開啟不受 ② 的靜音影響
            render();
            return;
          }
          const update = await checkForUpdate();
          if (update) {
            pendingUpdate = update;
            updateModalOpen = true;
          } else {
            updateFlash = "已是最新版";
            setTimeout(() => {
              updateFlash = null;
              if (state.screen === "home" || state.screen === "settings") render();
            }, 2000);
          }
          render();
        }),
    },
    [hasUpdate ? `${APP_VERSION} → v${pendingUpdate.versionCode}` : APP_VERSION],
  );
}

// ---------- R10 Wake Lock：訓練畫面不鎖屏，倒數提醒才收得到 ----------

async function syncWakeLock() {
  const wanted = () => state.screen === "logger" && document.visibilityState === "visible";
  if (wanted() && wakeLock === null && !wakeLockPending) {
    wakeLockPending = true; // 防並行申請
    try {
      const lock = (await navigator.wakeLock?.request("screen")) ?? null;
      lock?.addEventListener("release", () => {
        if (wakeLock === lock) wakeLock = null; // 系統自行釋放（切頁）——回來時再要一次
      });
      if (wanted()) {
        wakeLock = lock;
      } else {
        lock?.release().catch(() => {}); // 申請期間已離開 logger：就地釋放，不留孤兒鎖
      }
    } catch {
      /* 不支援或被拒：靜默降級，功能照常 */
    } finally {
      wakeLockPending = false;
    }
  } else if (!wanted() && wakeLock !== null) {
    const lock = wakeLock;
    wakeLock = null;
    try {
      await lock.release();
    } catch {
      /* 已被系統釋放 */
    }
  }
}

function showError(message) {
  state.error = message;
  render();
}

async function guard(action) {
  try {
    state.error = null;
    await action();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      stopRestTimer();
      state.screen = "setup";
      state.error = "Token 無效——重新輸入";
      render();
      return;
    }
    showError(err.message);
  }
}

// ---------- 離線佇列（F5）：送不出去先入列，恢復連線自動補傳 ----------

function isOffline(err) {
  return err instanceof ApiError && err.status === 0;
}

async function refreshQueueCounts() {
  // 一次讀取同時推導計數與逐筆狀態——done-list 的 ⏳/⚠ 標示以佇列為唯一事實來源
  const entries = await listQueued();
  state.queue = {
    pending: entries.filter((e) => e.status === "pending").length,
    failed: entries.filter((e) => e.status === "failed").length,
  };
  state.queueStatus = Object.fromEntries(entries.map((e) => [e.client_uuid, e.status]));
}

function renderUnlessTyping() {
  // 背景同步觸發的重繪不得清掉使用者正在輸入的搜尋框（重繪會失焦收鍵盤）；
  // 略過也無妨——標示會在下一次自然重繪時更新
  const active = document.activeElement;
  if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA")) return;
  render();
}

// F32：把佇列生命週期（補傳成功換得 server id、捨棄失敗組）同步到 doneSets 與各動作鏡射並持久化。
// doneByExercise 可能含非當前動作的離線組，故要掃全部項目——否則換動作回來會復活無 id 的舊 payload，
// 之後刪除只移出佇列不刪 server、編輯撞 client_uuid 冪等失效（Codex P1）。
function reconcileDoneSets({ replace, remove } = {}) {
  const mapArr = (arr) =>
    arr
      .map((s) => (replace && replace.has(s.client_uuid) ? replace.get(s.client_uuid) : s))
      .filter((s) => !(remove && remove.has(s.client_uuid)));
  state.doneSets = mapArr(state.doneSets);
  const before = state.doneByExercise;
  state.doneByExercise = Object.fromEntries(
    Object.entries(before).map(([id, arr]) => [id, mapArr(arr)]),
  );
  // 捨棄失敗的離線組時，setCounts 也要跟著降——只縮短鏡射的話，課表進度會停在
  // 丟棄前的數字，動作被提前標成做完（Codex P2）。按實際移除幾筆扣，不整份重算：
  // 鏡射在「舊狀態遷移＋離線」時可能不完整，重算會把還沒回填的組誤刪成 0。
  if (remove) {
    for (const [id, arr] of Object.entries(before)) {
      const removed = arr.length - state.doneByExercise[id].length;
      if (removed > 0) {
        state.setCounts[id] = Math.max(0, (state.setCounts[id] || 0) - removed);
      }
    }
  }
  saveActiveWorkout();
}

async function syncQueue() {
  const before = state.queue;
  const synced = await flushQueue(api.logSet);
  // F91 ④：組補完再補「結束」。順序有意義——先送結束的話，同一場還沒補完的組
  // 會落在 ended_at 之後（雖然 ⑥ 允許寫入，但時間軸會更難讀）。
  await flushPendingEnds(api.endWorkout, api.deleteWorkout);
  // 補傳成功者把含 server id 的回應寫回 doneSets 與鏡射——否則使用者仍停在 logger 時，
  // 該筆缺 id 會被誤判未同步，之後在畫面上刪/改會打不到伺服器（Codex P1）
  if (synced.length > 0) {
    const byUuid = new Map(synced.map((x) => [x.client_uuid, x.saved]));
    reconcileDoneSets({ replace: byUuid });
  }
  await refreshQueueCounts();
  const changed =
    synced.length > 0 ||
    before.pending !== state.queue.pending ||
    before.failed !== state.queue.failed;
  // F81：補傳進去的是「組」，本週天數與上次訓練因此改變。開站時 loadHome 與 syncQueue 並行，
  // 首頁那份通常先回來——不重抓的話畫面會停在補傳前的數字，直到下次切畫面（Codex P2）。
  if (synced.length > 0) await loadHome();
  if (changed) renderUnlessTyping();
}

function syncStatusLine() {
  const { pending, failed } = state.queue;
  if (pending === 0 && failed === 0) return [];
  const parts = [];
  if (pending > 0) {
    parts.push(el("span", { class: "sync-pending" }, [
      icon("hourglass", { size: 14 }), ` 待同步 ${pending} 組`,
    ]));
  }
  if (failed > 0) {
    parts.push(
      el(
        "button",
        {
          class: "btn btn-danger sync-failed",
          onclick: () =>
            guard(async () => {
              const discarded = new Set(await discardFailed());
              // 捨棄＝這些組沒進 server——從清單與鏡射一併移除（F32 P1），不能讓它們看起來像已同步
              reconcileDoneSets({ remove: discarded });
              await refreshQueueCounts();
              render();
            }),
        },
        [icon("warning", { size: 14 }), ` 同步失敗 ${failed} 組（點此捨棄）`],
      ),
    );
  }
  return [el("div", { class: "sync-line" }, parts)];
}

// ---------- setup ----------

function renderSetup() {
  const input = el("input", {
    type: "password",
    placeholder: "API token",
    autocomplete: "off",
  });
  const save = async () => {
    setToken(input.value.trim());
    await loadExercises(""); // 驗證 token 可用，順便預載動作庫
    await loadHome(); // F81：進首頁前把三張卡的資料補上（否則第一眼是空的，要離開再回來才出現）
    state.screen = "home";
    render();
    runUpdateCheck(); // F67：剛設好 token 才查得動——開機那次在 setup 畫面必然 401
    // F91 ④：401 會把待補送的項目留在佇列，而重新登入既不改變網路狀態、也不重載頁面，
    // 沒有任何既有觸發點會重放它們——不在這裡補，ended_at 會一直是 null（Codex P2）。
    // 組的佇列同理，所以整支 syncQueue 都跑。
    guard(syncQueue);
  };
  return el("section", { class: "screen setup" }, [
    el("div", { class: "mark" }, [icon("dumbbell", { size: 44, label: "lift-log" })]),
    el("h1", {}, ["lift-log"]),
    el("p", {}, ["輸入 API token 開始使用（存在這支手機上）"]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    input,
    el("button", { class: "btn btn-primary", onclick: () => guard(save) }, ["連線"]),
    versionTag(),
    ...envTag(),
  ]);
}

// ---------- home ----------

// F81：首頁的三張卡（本週進度、今天的安排、上次訓練）全部吃這一包。
// 一次請求拿齊，不讓首頁變成三個 spinner；載不到就讓卡片消失，首頁的主要動作仍在。
let homeData = null;

export async function loadHome() {
  try {
    homeData = await api.scheduleToday();
  } catch (err) {
    // 離線或後端沒醒＝可降級：卡片消失，首頁照樣能開練。
    // 但 401 是「token 失效」，吞掉就會讓人卡在看起來只是「今天沒安排」的首頁上——
    // 那條路要交給 guard 導回重新登入（Codex 2026-07-29 P2）。
    homeData = null;
    if (err instanceof ApiError && err.status === 401) throw err;
  }
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 11) return "早安";
  if (hour < 18) return "午安";
  return "晚安";
}

function longDateLabel() {
  const now = new Date();
  const week = ["日", "一", "二", "三", "四", "五", "六"][now.getDay()];
  return `${now.getMonth() + 1}月${now.getDate()}日 週${week}`;
}

async function goPicker() {
  if (pickerExercises.length === 0) await loadExercises("");
  state.screen = "picker";
  render();
  // F83：菜單的「已練 N 分」與各動作上次數值。先畫再補——網路不該擋住畫面出現
  loadMenuMeta().then(() => {
    if (state.screen === "picker") render();
  });
  startMenuTicker();
}

async function startWorkout(template) {
  const workout = await api.createWorkout(template ? { template_id: template.id } : {});
  state.workoutId = workout.id;
  state.workoutDate = workout.date; // F90 ②：日期以伺服器建立時為準，之後不隨存檔時間改寫
  state.template = template; // 課表快照跟著這次訓練走，之後刪課表不受影響
  menuScrollTop = 0; // F48（Codex P2）：捲動位置屬於「這次訓練的菜單」——換一次訓練要從頂端開始，
  //                    否則舊偏移量會蓋在新課表上，前幾個動作被藏在捲動區上方
  saveActiveWorkout();
  await goPicker();
}

// 本週進度卡：七段條 ＋ 大數字。資料全部來自 /api/schedule/today（F80）。
function weekProgressCard() {
  const today = homeData.weekday - 1; // ISO 1..7 → 陣列索引 0..6
  return el("section", { class: "card week-card" }, [
    el("div", { class: "card-label" }, ["本週進度"]),
    el("div", { class: "week-count" }, [
      el("span", { class: "n" }, [String(homeData.week_done_days)]),
      el("span", { class: "of" }, [`/ ${homeData.weekly_target_days} 天`]),
    ]),
    el(
      "div",
      { class: "week-bars" },
      homeData.week_days.map((done, i) =>
        el("span", { class: `week-bar${done ? " done" : i === today ? " today" : ""}` }, []),
      ),
    ),
  ]);
}

// 今天的安排。三態：一份（照設計稿）／多份（各自一張小卡）／沒排程。
function todayPlanCard(start, pickTemplate) {
  const planned = homeData?.templates ?? [];
  const startLabel = state.workoutId ? "繼續訓練" : "開始訓練";

  if (planned.length === 0) {
    return el("section", { class: "card plan-card" }, [
      el("div", { class: "card-label" }, ["今天的安排"]),
      el("div", { class: "plan-none" }, ["今天沒安排"]),
      el(
        "button",
        { class: "btn btn-primary plan-start", onclick: () => guard(start) },
        [state.workoutId ? "繼續訓練" : "挑一份課表"],
      ),
    ]);
  }

  if (planned.length === 1) {
    const plan = planned[0];
    return el("section", { class: "card plan-card" }, [
      el("div", { class: "card-label" }, ["今天的安排"]),
      el("div", { class: "plan-name" }, [plan.name]),
      el("div", { class: "plan-meta" }, [`${plan.exercise_count} 動作 · ${plan.set_count} 組`]),
      el(
        "button",
        { class: "btn btn-primary plan-start", onclick: () => guard(() => pickTemplate(plan.id)) },
        [startLabel],
      ),
      el("button", { class: "btn btn-ghost plan-swap", onclick: () => guard(start) }, [
        "換一份課表",
      ]),
    ]);
  }

  // 多份：一天可以排早上推、晚上有氧（F80 ④）。各自一列，主按鈕的位置不因份數而跳動。
  return el("section", { class: "card plan-card" }, [
    el("div", { class: "card-label" }, [`今天的安排 · ${planned.length} 份`]),
    ...planned.map((plan) =>
      el("div", { class: "plan-row" }, [
        el("div", { class: "plan-row-text" }, [
          el("div", { class: "plan-row-name" }, [plan.name]),
          el("div", { class: "plan-meta" }, [
            `${plan.exercise_count} 動作 · ${plan.set_count} 組`,
          ]),
        ]),
        el(
          "button",
          {
            class: "btn btn-primary plan-row-start",
            onclick: () => guard(() => pickTemplate(plan.id)),
          },
          [startLabel],
        ),
      ]),
    ),
    el("button", { class: "btn btn-ghost plan-swap", onclick: () => guard(start) }, [
      "換一份課表",
    ]),
  ]);
}

// 上次訓練。沒有任何歷史時整張不畫——空狀態的卡片只是噪音。
function lastWorkoutCard() {
  const last = homeData?.last_workout;
  if (!last) return [];
  const [, month, day] = last.date.split("-");
  const title = last.template_name ? `上次 · ${last.template_name}` : "上次訓練";
  return [
    el("section", { class: "card last-card" }, [
      el("div", { class: "last-text" }, [
        el("div", { class: "last-title" }, [title]),
        el("div", { class: "last-meta" }, [
          `${Number(month)}/${Number(day)} · ${last.set_count} 組`,
        ]),
      ]),
      el("div", { class: "last-volume" }, [
        el("span", { class: "v" }, [Math.round(last.volume_kg).toLocaleString("en-US")]),
        el("span", { class: "u" }, ["kg"]),
      ]),
    ]),
  ];
}

function bottomNav() {
  const go = async (screen, open) => {
    await open();
    state.screen = screen;
    render();
  };
  const items = [
    ["clipboard", "課表", () => go("templates", async () => {
      await openTemplates();
      resetTemplateListScroll(); // F48：從首頁進課表頁一律從頂端
    })],
    ["calendar", "日曆", () => go("calendar", openCalendar)],
    ["trending", "表現", async () => {
      // F39：不必先開練，直接瀏覽有資料的動作看表現
      const origin = state.screen;
      await openTrends();
      if (state.screen !== origin) return; // 載入期間離開首頁 → 不劫持導覽
      state.screen = "trends";
      render();
    }],
    ["scale", "體重", () => go("body", openBody)],
  ];
  return el(
    "nav",
    { class: "bottom-nav" },
    items.map(([name, label, onclick]) =>
      el("button", { class: "btn nav-item", onclick: () => guard(onclick) }, [
        icon(name, { size: 18 }),
        el("span", {}, [label]),
      ]),
    ),
  );
}

function renderHome() {
  const start = async () => {
    if (state.workoutId) {
      await goPicker(); // 訓練開著：直接回去（課表已隨 workout 還原）
      return;
    }
    templateChoices = await api.listTemplates();
    if (templateChoices.length === 0) {
      await startWorkout(null);
      return;
    }
    state.screen = "templateSelect";
    render();
  };

  // 今天排定的那份：直接開練，不必再繞去挑課表
  const pickTemplate = async (templateId) => {
    if (state.workoutId) {
      await goPicker();
      return;
    }
    const templates = await api.listTemplates();
    const template = templates.find((t) => t.id === templateId);
    if (!template) {
      await start(); // 課表在別處被刪了——退回挑課表，不要卡住
      return;
    }
    await startWorkout(template);
  };
  return el("section", { class: "screen home" }, [
    el("header", { class: "home-head" }, [
      el("h1", {}, [`${greeting()}，Ryan`]),
      el("span", { class: "date" }, [longDateLabel()]),
      el(
        "button",
        {
          class: "btn icon-btn home-settings",
          "aria-label": "設定",
          onclick: () =>
            guard(async () => {
              await openSettings();
              state.screen = "settings";
              render();
            }),
        },
        [icon("settings", { size: 20, label: "設定" })],
      ),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...syncStatusLine(),
    ...(homeData ? [weekProgressCard()] : []),
    todayPlanCard(start, pickTemplate),
    ...lastWorkoutCard(),
    bottomNav(),
    // F68 ①④：更新視窗仍自動彈在首頁——版號入口雖然搬進設定，但「有新版」不該要人自己去翻
    ...(updateModalOpen && pendingUpdate ? [updateModal()] : []),
  ]);
}


// ---------- settings（F81） ----------
//
// 首頁改版把版面讓給了「今天要練什麼」，所以提醒開關、浮動計時、週目標與版號都收進這裡。
// 它們的共同點是「設定一次就不再碰」——留在首頁只是每天擋在主要動作前面。

let weeklyTargetDraft = null;

export async function openSettings() {
  try {
    const setting = await api.getSetting("weekly_target_days");
    weeklyTargetDraft = Number(setting.value);
  } catch (err) {
    weeklyTargetDraft = null; // 讀不到就不畫這一列，其餘設定照常可用
    if (err instanceof ApiError && err.status === 401) throw err; // 同 loadHome：401 要導回登入
  }
}

function weeklyTargetRow() {
  if (weeklyTargetDraft === null) return [];
  const change = (delta) =>
    guard(async () => {
      const previous = weeklyTargetDraft;
      const next = Math.min(7, Math.max(1, previous + delta));
      if (next === previous) return;
      weeklyTargetDraft = next;
      render(); // 先反映在畫面上（按下去要立刻有反應）
      try {
        await api.putSetting("weekly_target_days", next);
      } catch (err) {
        // 寫入失敗就把畫面退回去——留著未儲存的數字，下一次加減會從錯的值起算
        //（伺服器還是 4、畫面卻是 5，再按一次就直接寫 6）。Codex 2026-07-29 P2。
        weeklyTargetDraft = previous;
        render();
        throw err;
      }
      await loadHome(); // 首頁的分母跟著變
    });
  return [
    el("div", { class: "set-row" }, [
      el("span", { class: "set-row-label" }, ["每週目標天數"]),
      el("div", { class: "set-row-ctl" }, [
        el("button", { class: "btn chip", "aria-label": "減少", onclick: () => change(-1) }, ["−"]),
        el("span", { class: "set-row-val" }, [String(weeklyTargetDraft)]),
        el("button", { class: "btn chip", "aria-label": "增加", onclick: () => change(1) }, ["＋"]),
      ]),
    ]),
  ];
}

// F89 ⑥：浮動計時的設定列是**三態**，不是開／關兩態。
//
//   開       —— 使用者要，系統也允許
//   關       —— 使用者自己關掉的；不需要引導，點一下就開
//   未授權   —— 系統不允許畫在其他 app 上。開關維持 OFF 外觀（--card-hi 底、--text-faint 字），
//               但**常駐**一行副標把出路寫出來。原本只有點下去才跳一次性錯誤訊息，
//               訊息消失後畫面上就再也看不出「為什麼開不起來」——那是靜默失敗的一種。
//
// 未授權時倒數不會消失：它退回通知列（F63），只是少了浮動視窗那個顯示面。
// F62 ③ ＋ F106 ③：精確鬧鐘被關時倒數會被系統延後，講出來而不是讓使用者以為壞了。
//
// ⚠ 出路住在副標，不在 switch 上。藥丸時代點整顆＝去開系統授權（**不是**關掉提醒），
// 那是把兩個動作綁在同一個目標上；switch 的點擊語意固定是切換，兼任跳轉會讓
// 想關提醒的人被丟到系統設定頁。
function restNotifyRow() {
  const on = restNotifyEnabled();
  const delayed = on && restNotifyDelayed();
  return switchRow({
    icon: "bell",
    label: "休息提醒",
    on,
    onToggle: () =>
      guard(async () => {
        if (on) {
          await disableRestNotify();
          render();
          return;
        }
        const res = await enableRestNotify();
        if (res.ok) render();
        else showError(res.reason);
      }),
    sub: delayed
      ? {
          text: "可能延遲 · 點此修正",
          onClick: () =>
            guard(async () => {
              await requestRestNotifyExact();
              render();
            }),
        }
      : null,
  });
}

function restOverlayRow() {
  const on = restOverlayEnabled();
  const locked = !on && !restOverlayPermitted();
  // 未授權時 enableRestOverlay() 本來就會把人送到系統授權頁（F64 ②），
  // 所以「撥開關」與「點副標」走的是同一條——差別只在副標把它講出來了。
  const toSettings = () =>
    guard(async () => {
      const res = await enableRestOverlay();
      if (res.ok) render();
      else showError(res.reason);
    });

  return switchRow({
    icon: "window",
    label: "浮動計時",
    on,
    onToggle: () =>
      guard(async () => {
        if (on) {
          await disableRestOverlay();
          render();
          return;
        }
        await toSettings();
      }),
    // F106 ③：出路從「點整顆」搬到這一行。F89 ⑥ 的三態語意不變——
    // 開／關由 switch 表達，「需系統授權」由副標表達，兩者仍分得出來。
    sub: locked ? { text: "需系統授權 · 點此前往設定", onClick: toSettings } : null,
  });
}

function renderSettings() {
  return el("section", { class: "screen settings-screen" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, ["設定"]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...weeklyTargetRow(),
    // F31/F62：休息結束提醒開關（不支援的環境不顯示）。
    // web 走 Web Push、app 走本機通知——同一顆按鈕，實作差異藏在 rest-notify.js
    ...(restNotifySupported() ? [restNotifyRow()] : []),
    // F64：浮動計時視窗。只在 app 版出現，且必須先開休息提醒——
    // overlay 是前景服務的第二個顯示面，服務沒跑就沒有秒數可畫
    ...(restOverlaySupported() && restNotifyEnabled() ? [restOverlayRow()] : []),
    versionTag(),
    ...envTag(),
    // F68 ⑦：手動檢查後沒有新版的短暫提示
    ...(updateFlash ? [el("div", { class: "update-flash" }, [updateFlash])] : []),
    // F68 ④：更新視窗在首頁與設定都掛得住——訓練途中的畫面一律不被它打斷
    ...(updateModalOpen && pendingUpdate ? [updateModal()] : []),
    el(
      "button",
      {
        class: "btn btn-ghost settings-back",
        onclick: () =>
          guard(async () => {
            await loadHome(); // 週目標可能剛改過，首頁的分母要跟著更新
            state.screen = "home";
            render();
          }),
      },
      [iconLabel("back", "回首頁")],
    ),
  ]);
}


// F68：更新視窗。內容與下載進度都在視窗內（⑤），下載邏輯沿用 F67 的原生路徑不重做。
function updateModal() {
  const mb = (pendingUpdate.sizeBytes / 1048576).toFixed(1);
  const downloading = updateProgress !== null;
  const confirmBtn = el(
    "button",
    {
      class: "btn btn-primary",
      // 條件展開：`disabled: false` 在 HTML 仍算停用（F67 踩過）
      ...(downloading ? { disabled: "" } : {}),
      onclick: () =>
        guard(async () => {
          updateProgress = 0;
          render();
          const res = await downloadAndInstall(pendingUpdate, (ratio) => {
            updateProgress = ratio;
            // 就地更新文字：下載期間整頁重繪會讓視窗狂閃
            const label = document.querySelector(".update-progress");
            if (label) label.textContent = `下載中 ${Math.round(ratio * 100)}%`;
          });
          updateProgress = null;
          if (!res.ok) {
            // ⑤：失敗訊息留在視窗內。原本關窗改用頁面層級 error-banner，
            // 驗收判定與條文不符（2026-07-28）——關掉視窗等於把使用者踢出他正在做的事
            updateError = res.reason;
            render();
            return;
          }
          render();
        }),
    },
    [downloading ? "下載中…" : "立即更新"],
  );
  return el(
    "div",
    {
      class: "modal-overlay",
      onclick: (e) => {
        // 下載中點遮罩不關窗——關了進度就看不到了
        if (e.target === e.currentTarget && !downloading) {
          dismissUpdate(pendingUpdate.versionCode);
          updateModalOpen = false;
          updateError = null;
          render();
        }
      },
    },
    [
      el("div", { class: "modal update-modal" }, [
        el("div", { class: "modal-head" }, [`有新版 v${pendingUpdate.versionCode}`]),
        ...(updateError ? [el("div", { class: "error-banner" }, [updateError])] : []),
        el("div", { class: "update-progress" }, [
          downloading ? `下載中 ${Math.round(updateProgress * 100)}%` : `檔案大小 ${mb} MB`,
        ]),
        el("div", { class: "modal-actions" }, [
          confirmBtn,
          el(
            "button",
            {
              class: "btn btn-ghost modal-cancel",
              ...(downloading ? { disabled: "" } : {}),
              onclick: () => {
                // ② 記住的是版號：出更新的版本時要重新提醒
                dismissUpdate(pendingUpdate.versionCode);
                updateModalOpen = false;
                updateError = null; // 下次開窗不要看到上一輪的錯誤
                render();
              },
            },
            ["稍後再說"],
          ),
        ]),
      ]),
    ],
  );
}

// ---------- templateSelect（開練：挑今日課表） ----------

let templateChoices = [];

function renderTemplateSelect() {
  // F82：今天排到的那份預設展開並用 --card-hi 站出來（F80 的排程）。沒排程就展開第一張——
  // 設計的視覺節奏靠「有一張是攤開的」，全部收合會變成一排一模一樣的長方形。
  const scheduledIds = new Set((homeData?.templates ?? []).map((t) => t.id));
  const highlightId = templateChoices.find((t) => scheduledIds.has(t.id))?.id
    ?? templateChoices[0]?.id;

  // F48：課表超過 2 份才固定高度＋內部捲動；「自由訓練」留在捲動區外（它不是課表，
  // 位置要固定才按得到）。此畫面不會在停留中重繪，故不需存還原 scrollTop。
  const scrollable = templateChoices.length > 2;
  return el("section", { class: "screen template-select fills" }, [
    el("header", { class: "screen-head" }, [
      el(
        "button",
        {
          class: "btn icon-btn back-btn",
          "aria-label": "回首頁",
          onclick: () => { state.screen = "home"; render(); },
        },
        [icon("back", { size: 20, label: "回首頁" })],
      ),
      el("div", { class: "screen-head-text" }, [
        el("h1", {}, ["挑今日課表"]),
        el("div", { class: "st" }, [`${templateChoices.length} 份課表`]),
      ]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    el("div", { class: "tpl-choice-wrap" }, [
      el(
        "div",
        { class: `tpl-choice-list${scrollable ? " scrollable" : ""}` },
        templateChoices.map((t) => templateChoiceCard(t, t.id === highlightId)),
      ),
      el(
        "button",
        { class: "btn btn-ghost free-choice", onclick: () => guard(() => startWorkout(null)) },
        ["自由訓練"],
      ),
    ]),
  ]);
}

// 挑課表的一張卡。展開的那張列動作 chips，其餘只講「上次練是什麼時候、練了多少」——
// 那是決定今天要不要練這份的資訊，動作清單反而是次要的。
function templateChoiceCard(template, expanded) {
  const totalSets = template.exercises.reduce((sum, e) => sum + (e.default_sets || 0), 0);
  return el(
    "button",
    {
      class: `tpl-choice${expanded ? " on" : ""}`,
      onclick: () => guard(() => startWorkout(template)),
    },
    [
      el("div", { class: "tpl-choice-head" }, [
        el("span", { class: "tpl-choice-name" }, [template.name]),
        el("span", { class: "tpl-choice-meta" }, [
          `${template.exercises.length} 動作 · ${totalSets} 組`,
        ]),
      ]),
      expanded
        ? el(
            "div",
            { class: "tpl-choice-chips" },
            template.exercises.map((e) =>
              el("span", { class: "chip" }, [getLang() === "zh" ? e.name_zh : e.name_en]),
            ),
          )
        : el("div", { class: "tpl-choice-last" }, [lastUsedText(template)]),
    ],
  );
}

// 「上次 7/27 · 4,820 kg」；沒練過就直說，不要留一行空的
function lastUsedText(template) {
  if (!template.last_used_date) return "還沒練過";
  const [, month, day] = template.last_used_date.split("-");
  const volume = Math.round(template.last_volume_kg ?? 0).toLocaleString("en-US");
  return `上次 ${Number(month)}/${Number(day)} · ${volume} kg`;
}

// ---------- picker ----------

let pickerExercises = [];
let customFormOpen = false; // F10 自訂動作視窗是否開啟（picker）
let addPanelOpen = false; // F49：有課表時的「臨時加動作」懸浮視窗是否開啟

// F49 review P2-3：搜尋回應排序保護——舊回應晚到不得覆蓋新結果（沿用 templates.js searchSeq 慣例）。
// 回傳 false＝這次回應已過期，呼叫端不要拿去重畫清單。
let pickerSearchSeq = 0;

async function loadExercises(q) {
  const seq = ++pickerSearchSeq;
  const found = await api.searchExercises(q || "");
  if (seq !== pickerSearchSeq) return false;
  pickerExercises = found;
  return true;
}

function openCustomForm() {
  customFormOpen = true;
  render();
}

// 收工／結束訓練：清 client 狀態並告訴伺服器這場結束了；已記錄的組在 server（SSOT），
// 佇列未同步的之後仍補傳進這個 workout（F91 ⑥ 刻意不擋已結束 workout 的寫入）。
// logger 的「收工」與 picker 的「結束訓練」共用（module 級 function 宣告會 hoist，logger 內引用不受順序影響）。
function endWorkout() {
  addPanelOpen = false; // F49：收工一併關窗
  stopRestTimer();
  state.pendingRestSeconds = null;
  editDraft = null;
  const ending = state.workoutId;
  // F92 ⑥：這場一組都沒記 → 刪掉它，不要留一場空的在資料庫。
  // 本地判斷可能不完整（另一台裝置在同一場記過組），所以伺服器端還有一道 409 擋著；
  // 撞到就退回正常的「結束」流程。
  const loggedNothing =
    Object.values(state.setCounts).reduce((sum, n) => sum + n, 0) === 0;
  // F91 ④：「發出」不等於「等它回來」——guard 的 async body 會同步執行到第一個 await，
  // 也就是 fetch 已經送出去了，下面才清狀態。使用者不會多等一毫秒，
  // 而伺服器收到請求時本地狀態仍在，順序與規格一致。
  // 失敗不回滾本地結束（那只會讓人卡在一場他已經結束的訓練裡），改進補送佇列：
  // 不補的話伺服器的 ended_at 永遠是 null，另一台裝置照樣能續接——那正是 F91 要解掉的東西。
  if (ending) {
    guard(async () => {
      if (loggedNothing) {
        try {
          await api.deleteWorkout(ending);
          return; // 刪掉了就沒有「結束」可言
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) return; // 已經不在了
          if (!(err instanceof ApiError) || err.status !== 409) {
            rememberPendingEnd(ending, "delete"); // 離線／5xx：回線上要**刪掉**，不是標記結束
            return;
          }
          /* 409＝伺服器上其實有組（別台記的）→ 往下走正常的結束流程 */
        }
      }
      try {
        await api.endWorkout(ending);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          rememberPendingEnd(ending); // 重新登入後補送
          throw err;
        }
        if (err instanceof ApiError && err.status === 404) return; // 那場已不在，不必補
        rememberPendingEnd(ending); // 離線／5xx
      }
    });
  }
  clearActiveWorkout(); // F90 起 setCounts 也由它清（單一來源）
  state.exercise = null;
  backHome(); // F81：這次訓練剛結束，本週進度與「上次訓練」都變了
}

// F10 picker 的自訂動作視窗（共用 customExerciseModal）。建立成功 → reload 動作庫並關窗，
// 新動作即出現在清單可直接記錄；離線刷新失敗用建立回傳值補進清單當 fallback（Codex P2）。
function pickerCustomModal() {
  const groups = [...new Set(pickerExercises.map((e) => e.muscle_group))];
  return customExerciseModal({
    groups,
    onCreated: (created) => {
      customFormOpen = false;
      state.searchQ = "";
      state.muscleFilter = null;
      guard(async () => {
        try {
          // loadExercises 現在會在「回應過期」時回 false（不是拋錯）——那條路也要補進清單，
          // 否則新建的自訂動作既沒 reload 也沒補上，使用者看不到剛建的動作（review P3-5）
          if (!(await loadExercises(""))) pickerExercises = [...pickerExercises, created];
        } catch {
          pickerExercises = [...pickerExercises, created];
        }
        render();
      });
    },
    onCancel: () => { customFormOpen = false; render(); },
    onFatal: (err) => guard(() => Promise.reject(err)), // 401 交全域 guard 導回 setup
  });
}

/**
 * 下一組的組號＝這個動作已用過的**最大組號** + 1。
 *
 * 不能用「完成組數 + 1」：刪掉中間某組後（伺服器剩 [1, 3]）組數是 2，下一組又會送 3，
 * 而後端沒有組號唯一約束——撞號是靜默的，資料裡就多一筆一樣的組號，沒有任何錯誤訊息。
 *
 * 與 setCounts 刻意分開：那個欄位是「完成組數」，menuCounts() 的課表進度（X/Y 組）靠它，
 * 拿最大組號去填會讓刪過組的動作提前顯示做完（Codex 複審 P2）。
 * 仍以 setCounts 當下限，是為了相容沒有鏡射的舊資料（那時只有組數可用）。
 */
function nextSetNumber(exerciseId) {
  const done = state.doneByExercise[exerciseId] ?? [];
  const maxUsed = done.reduce((max, s) => Math.max(max, s.set_number ?? 0), 0);
  return Math.max(maxUsed, state.setCounts[exerciseId] || 0) + 1;
}

// F32：把目前動作的完成組鏡射進 doneByExercise，換動作後回到該動作可原樣還原（同一次訓練內）。
function rememberDoneSets() {
  if (!state.exercise) return;
  state.doneByExercise = { ...state.doneByExercise, [state.exercise.id]: state.doneSets };
}

async function pickExercise(exercise) {
  addPanelOpen = false; // F49：選了動作就離開 picker，視窗狀態不留到下次回來（否則回 picker 會自己彈開）
  state.exercise = exercise;
  state.rpe = 6; // F40：進動作預設累度「輕鬆」
  state.doneSets = [];
  state.lastSetsOpen = false; // F101：換動作要關掉上次紀錄視窗，否則它會帶著舊動作的內容留在畫面上
  state.setNumber = nextSetNumber(exercise.id); // 回頭選同動作時接續編號（取最大組號，不是組數）

  // F32：同一次訓練已做過這個動作 → 還原本次的組，不重抓「上次」
  //（last-sets 取「最近一次 workout」＝今天這次，會把本次的組誤標成上次、done-list 也空掉）
  let resumed = state.doneByExercise[exercise.id];
  // P2：v31→v32 升級時舊 session 無鏡射，但 setCounts>0 代表本次做過 → 從伺服器回填一次，
  // 否則跨部署的進行中訓練仍會把本次組誤標成「上次」（Codex P2）。離線回填失敗就退回原流程。
  const missingMirror = !Array.isArray(resumed) || resumed.length === 0;
  if (missingMirror && (state.setCounts[exercise.id] || 0) > 0 && state.workoutId) {
    try {
      const detail = await api.workoutDetail(state.workoutId);
      const grouped = {};
      for (const s of detail.sets) (grouped[s.exercise_id] ??= []).push(s);
      // 既有鏡射優先（可能含尚未上 server 的離線組），只補伺服器有、鏡射缺的動作
      state.doneByExercise = { ...grouped, ...state.doneByExercise };
      saveActiveWorkout();
      resumed = state.doneByExercise[exercise.id];
    } catch {
      /* 離線/失敗：退回下方 lastSets 流程 */
    }
  }
  if (Array.isArray(resumed) && resumed.length > 0) {
    state.doneSets = resumed.map((s) => ({ ...s }));
    const lastSet = state.doneSets[state.doneSets.length - 1];
    state.weightKg = lastSet.weight_kg; // 續接本次：預設帶本次最後一組
    state.reps = lastSet.reps;
    // 「上次」仍要顯示——但查的是**前一次** workout（排除本次），不是把本次組誤標成上次。
    // 查不到前一次（第一次做這個動作）才退回顯示本次摘要。離線就略過參考。
    let prev = [];
    try {
      prev = await api.lastSets(exercise.id, state.workoutId);
    } catch (err) {
      if (!isOffline(err)) throw err; // 401/5xx 交給 guard（導回 setup／顯示錯誤），不當成查無上次
      /* 離線：略過上次參考，done-list 仍是本次的組 */
    }
    if (state.exercise !== exercise) return; // await 期間已換動作/結束訓練：丟棄過期結果，別把畫面拉回 logger
    state.lastHint =
      prev.length > 0
        ? `上次  ${prev.map((s) => `${s.weight_kg}×${s.reps}`).join("  ")}`
        : `本次  ${state.doneSets.map((s) => `${s.weight_kg}×${s.reps}`).join("  ")}`;
    const ref = prev.length > 0 ? prev[0] : state.doneSets[state.doneSets.length - 1];
    state.lastRef = ref
      ? { date: ref.workout_date ?? null, weight: ref.weight_kg, reps: ref.reps }
      : null;
    // F101：視窗列的是「上次那次訓練」的全部組。本次的組已經在 done-list 上了，
    // 拿本次的組去填「上次」視窗只會讓人看到同一份資料兩次。
    state.lastSets = prev;
    state.screen = "logger";
    render();
    return;
  }

  let last = [];
  let offline = false;
  try {
    // 排除進行中的 workout：即使本次剛做過，「上次」也指前一次訓練（F32）
    last = await api.lastSets(exercise.id, state.workoutId);
  } catch (err) {
    if (!isOffline(err)) throw err; // 離線拿不到「上次」——退而求其次，不擋記錄
    offline = true;
  }
  if (last.length > 0) {
    state.weightKg = last[0].weight_kg;
    state.reps = last[0].reps;
    state.lastHint = `上次  ${last.map((s) => `${s.weight_kg}×${s.reps}`).join("  ")}`;
    // F84：上次提示卡要的是結構化資料（日期＋代表值），顯示字串湊不回來
    state.lastRef = {
      date: last[0].workout_date ?? null,
      weight: last[0].weight_kg,
      reps: last[0].reps,
    };
    state.lastSets = last; // F101：視窗要列全部組
  } else if (offline) {
    // 離線：沿用本次已排隊的同動作組數當預設，沒有就用通用預設；不假裝是「第一次做」
    const queued = (await listQueued()).filter(
      (e) =>
        e.status === "pending" &&
        e.workout_id === state.workoutId &&
        e.payload.exercise_id === exercise.id,
    );
    if (queued.length > 0) {
      const newest = queued[queued.length - 1].payload;
      state.weightKg = newest.weight_kg;
      state.reps = newest.reps;
      state.lastHint = `本次（待同步）  ${queued
        .map((e) => `${e.payload.weight_kg}×${e.payload.reps}`)
        .join("  ")}`;
    } else {
      state.weightKg = exercise.is_bodyweight ? 0 : 20;
      state.reps = 8;
      state.lastHint = "離線中——載不到上次紀錄";
      state.lastRef = null;
      state.lastSets = [];
    }
  } else {
    state.weightKg = exercise.is_bodyweight ? 0 : 20;
    state.reps = 8;
    state.lastHint = null;
    state.lastRef = null; // 換動作沒清＝上一個動作的參考值殘留在卡片上
    state.lastSets = [];
  }
  if (state.exercise !== exercise) return; // await（lastSets/listQueued）期間已離開/換動作：丟棄過期結果
  state.screen = "logger";
  render();
}

// F38：開動作詳情頁（picker／logger 兩處入口共用）；記住來源畫面供返回
function openDetail(exercise, from) {
  return guard(async () => {
    const origin = state.screen;
    await openExerciseDetail(exercise, from);
    if (state.screen !== origin) return; // 載入期間使用者已離開來源畫面 → 不劫持導覽
    state.screen = "exerciseDetail";
    render();
  });
}

// F38：把「主按鈕＋📈 詳情入口」包成一列（picker 清單與今日菜單共用）
function exerciseRow(mainBtn, exercise, from) {
  return el("div", { class: "exercise-row" }, [
    mainBtn,
    el(
      "button",
      { class: "btn detail-link", "aria-label": "動作表現", onclick: () => openDetail(exercise, from) },
      [icon("trending", { size: 18, label: "動作表現" })],
    ),
  ]);
}

// F39：動作表現瀏覽——先選部位 chip 才出對應動作（同「加動作」操作），點進詳情頁
let trendsExercises = [];
let trendsMuscle = null; // 目前選的部位；null＝還沒選（不列動作）

async function openTrends() {
  trendsExercises = await api.exercisesWithData();
  trendsMuscle = null; // 每次從首頁進來重置為未選
}

function renderTrends() {
  const groups = [...new Set(trendsExercises.map((e) => e.muscle_group))];
  // 選的部位若已無資料（理論上不會），退回未選
  if (trendsMuscle && !groups.includes(trendsMuscle)) trendsMuscle = null;

  const body = [];
  if (trendsExercises.length === 0) {
    body.push(el("p", { class: "trends-empty" }, ["還沒有任何訓練紀錄——先去開練記幾組，這裡就會出現。"]));
  } else {
    // 部位 chips（只列有資料的部位）；點了才出對應動作，可重選切換
    body.push(
      el("div", { class: "chips" },
        groups.map((g) =>
          el("button", {
            class: `chip${trendsMuscle === g ? " on" : ""}`,
            onclick: () => { trendsMuscle = g; render(); },
          }, [g]),
        ),
      ),
    );
    if (trendsMuscle === null) {
      body.push(el("p", { class: "trends-hint" }, ["選一個部位，看該部位動作的表現。"]));
    } else {
      body.push(
        el("div", { class: "exercise-list" },
          trendsExercises
            .filter((e) => e.muscle_group === trendsMuscle)
            .map((exercise) =>
              el("button", {
                class: "btn exercise-item",
                onclick: () => openDetail(exercise, "trends"),
              }, [
                el("span", {}, [exerciseName(exercise)]),
                el("span", { class: "sub" }, [exerciseAlias(exercise)]),
              ]),
            ),
        ),
      );
    }
  }
  return el("section", { class: "screen trends" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, ["動作表現"]),
      el("button", { class: "btn btn-ghost chip", onclick: () => { toggleLang(); render(); } },
        [getLang() === "zh" ? "EN" : "中"]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...body,
    el("button", { class: "btn btn-ghost", onclick: () => { state.screen = "home"; render(); } }, ["← 回首頁"]),
  ]);
}

function exerciseButtons() {
  const shown = state.muscleFilter
    ? pickerExercises.filter((e) => e.muscle_group === state.muscleFilter)
    : pickerExercises;
  return shown.map((exercise) =>
    // F38：主鍵（選這動作開始記錄）＋📈 詳情入口分成兩顆並排鈕，點📈不誤觸開始記錄
    exerciseRow(
      el(
        "button",
        { class: "btn exercise-item", onclick: () => guard(() => pickExercise(exercise)) },
        [
          el("span", {}, [exerciseName(exercise)]),
          el("span", { class: "sub" }, [exerciseAlias(exercise)]),
        ],
      ),
      exercise,
      "picker",
    ),
  );
}

// F48：今日菜單的捲動位置——記完一組回 picker 會整頁重繪（進度數字更新），否則每次都跳回頂端
let menuScrollTop = 0;

// F83：今日菜單的兩份輔助資料。開始時間走伺服器（app 被系統回收後前端記的就沒了），
// 各動作的「上次」一次批次取回（逐個打會是 N 次往返）。
// ⚠ 一定要綁 workoutId：這是模組層狀態，換一場訓練若不歸零，新菜單的第一幀會用上一場的
// 開始時間畫出「已練 47 分」，等 API 回來才跳回 0（goPicker 是先 render 再載）。
let menuMeta = { workoutId: null, startedAt: null, lastValues: {} };

export async function loadMenuMeta() {
  const workoutId = state.workoutId;
  if (!workoutId || !state.template) {
    menuMeta = { workoutId: null, startedAt: null, lastValues: {} };
    return;
  }
  // 換場就先清空——寧可短暫沒有，也不要顯示上一場的數字
  if (menuMeta.workoutId !== workoutId) {
    menuMeta = { workoutId, startedAt: null, lastValues: {} };
  }
  const ids = state.template.exercises.map((e) => e.exercise_id);
  try {
    const [detail, values] = await Promise.all([
      api.workoutDetail(workoutId),
      api.lastSetValues(ids, workoutId),
    ]);
    if (state.workoutId !== workoutId) return; // await 期間換場了：丟棄過期結果
    menuMeta = {
      workoutId,
      startedAt: detail.created_at ? Date.parse(detail.created_at + "Z") : null,
      lastValues: Object.fromEntries(
        values.map((v) => [v.exercise_id, { weight: v.weight_kg, reps: v.reps }]),
      ),
    };
  } catch {
    // 離線或後端沒醒：**保留同一場已經拿到的值**，不要把畫面上好好的數字清掉
    //（訓練中途進電梯、從 logger 回菜單剛好失敗一次，就會整批消失）
  }
}

// 本次這個動作最後一組的數值——優先於「上次」，因為你正在做的才是當下的參考
function currentValues(exerciseId) {
  const done = state.doneByExercise?.[exerciseId] ?? [];
  const last = done[done.length - 1];
  return last ? { weight: last.weight_kg, reps: last.reps } : null;
}

function menuValuesText(item) {
  const values = currentValues(item.exercise_id) ?? menuMeta.lastValues[item.exercise_id];
  if (!values) return null; // 沒做過也沒歷史：不留一行空的
  return `${Number(values.weight)} kg × ${values.reps}`;
}

// 環形進度：SVG 圓環 ＋ 中央百分比。stroke-dasharray 走圓周長，dashoffset 表未完成的部分。
function progressRing(done, total) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const circumference = 2 * Math.PI * 19; // r=19（44px 圓、3px 環寬）
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNs, "svg");
  svg.setAttribute("viewBox", "0 0 44 44");
  svg.setAttribute("width", "44");
  svg.setAttribute("height", "44");
  svg.setAttribute("aria-hidden", "true");
  for (const [cls, offset] of [
    ["ring-track", 0],
    ["ring-value", circumference * (1 - pct / 100)],
  ]) {
    const circle = document.createElementNS(svgNs, "circle");
    circle.setAttribute("cx", "22");
    circle.setAttribute("cy", "22");
    circle.setAttribute("r", "19");
    circle.setAttribute("fill", "none");
    circle.setAttribute("stroke-width", "3");
    circle.setAttribute("class", cls);
    if (cls === "ring-value") {
      circle.setAttribute("stroke-dasharray", String(circumference));
      circle.setAttribute("stroke-dashoffset", String(offset));
      circle.setAttribute("stroke-linecap", "round");
    }
    svg.append(circle);
  }
  return el("div", { class: "progress-ring", role: "img", "aria-label": `完成 ${pct}%` }, [
    svg,
    el("span", { class: "ring-pct" }, [`${pct}%`]),
  ]);
}

// 「已練 N 分」要會跳動——它讀起來就是計時器。每 30 秒重畫一次，
// 且只在今日菜單上跑：離開畫面就停，不留一個永遠在背景燒電的 interval。
let menuTicker = null;

function startMenuTicker() {
  stopMenuTicker();
  if (!state.template) return;
  menuTicker = setInterval(() => {
    if (state.screen !== "picker" || !state.template) {
      stopMenuTicker();
      return;
    }
    if (menuMeta.startedAt) render();
  }, 30_000);
}

function stopMenuTicker() {
  if (menuTicker !== null) {
    clearInterval(menuTicker);
    menuTicker = null;
  }
}

function menuCounts() {
  const items = state.template?.exercises ?? [];
  const total = items.reduce((sum, i) => sum + (i.default_sets || 0), 0);
  const done = items.reduce(
    (sum, i) => sum + Math.min(state.setCounts[i.exercise_id] || 0, i.default_sets || 0),
    0,
  );
  return { done, total };
}

function elapsedText() {
  if (!menuMeta.startedAt) return null;
  const minutes = Math.max(0, Math.round((Date.now() - menuMeta.startedAt) / 60000));
  // 開著沒收工過夜的情況（restoreActiveWorkout 沒有時效檢查）——「已練 780 分」沒有意義，不如不講
  if (minutes >= 12 * 60) return null;
  if (minutes < 60) return `已練 ${minutes} 分`;
  return `已練 ${Math.floor(minutes / 60)} 小時 ${minutes % 60} 分`;
}

// 「接著做」＝第一個還沒做滿的動作。全做滿就不再推下一步，改講都做完了。
function nextUpItem() {
  return (state.template?.exercises ?? []).find(
    (item) => (state.setCounts[item.exercise_id] || 0) < (item.default_sets || 0),
  );
}

function nextUpBlock() {
  const item = nextUpItem();
  if (!item) {
    return [el("div", { class: "next-up-done" }, ["都做完了 —— 可以收工"])];
  }
  // 走同一支推導：用 setCounts + 1 的話，刪過中間組時這裡會顯示「第 3 組」，
  // 點進去卻記成第 4 組——建議與實際不一致（Codex P2）。
  const setNumber = nextSetNumber(item.exercise_id);
  const values = menuValuesText(item);
  const exercise = {
    id: item.exercise_id,
    name_zh: item.name_zh,
    name_en: item.name_en,
    muscle_group: item.muscle_group,
    is_bodyweight: item.is_bodyweight,
  };
  return [
    el("div", { class: "next-up-label" }, ["接著做"]),
    el(
      "button",
      {
        class: "btn btn-primary next-up",
        onclick: () => guard(() => pickExercise(exercise)),
      },
      [
        el("span", { class: "next-up-text" }, [
          el("span", { class: "next-up-name" }, [`${exerciseName(item)} · 第 ${setNumber} 組`]),
          ...(values ? [el("span", { class: "next-up-values" }, [values])] : []),
        ]),
        icon("arrow-right", { size: 20 }),
      ],
    ),
  ];
}

function templateMenu() {
  if (!state.template) return [];
  // F48：課表動作超過 2 個才固定高度＋內部捲動，下方的「接著做」與結束訓練不被推出畫面
  const scrollable = state.template.exercises.length > 2;
  const menuNode = el(
    "div",
    { class: `menu-list${scrollable ? " scrollable" : ""}` },
    state.template.exercises.map((item) => menuCard(item)),
  );
  if (scrollable) {
    requestAnimationFrame(() => { menuNode.scrollTop = menuScrollTop; });
  }
  return [menuNode];
}

// 每組一段的指示條。段數多到塞不下時退回文字——每段 20px＋6px gap 且不可壓縮，
// 360px 寬的手機上 8 段就快滿了，再多會把卡片撐出水平捲動（review LOW-6）。
const MAX_SET_BARS = 8;

function setBars(done, total) {
  if (total > MAX_SET_BARS) {
    return el("span", { class: "menu-card-count" }, [`${done}/${total} 組`]);
  }
  return el(
    "span",
    { class: "menu-card-bars" },
    Array.from({ length: total }, (_, i) =>
      el("span", { class: `menu-bar${i < done ? " done" : ""}` }, []),
    ),
  );
}

// F83：一個動作一張卡。進行中的那張站出來（--card-hi ＋「進行中」），
// 右側每組一段的指示條讓「還剩幾組」不必用讀的。
function menuCard(item) {
  const done = state.setCounts[item.exercise_id] || 0;
  const total = item.default_sets || 0;
  const inProgress = done > 0 && done < total;
  const complete = total > 0 && done >= total;
  const exercise = {
    id: item.exercise_id,
    name_zh: item.name_zh,
    name_en: item.name_en,
    muscle_group: item.muscle_group,
    is_bodyweight: item.is_bodyweight,
  };
  const values = menuValuesText(item);
  const card = el(
    "button",
    {
      class: `menu-card${inProgress ? " on" : ""}${complete ? " complete" : ""}`,
      onclick: () => guard(() => pickExercise(exercise)),
    },
    [
      el("div", { class: "menu-card-head" }, [
        el("span", { class: "menu-card-name" }, [exerciseName(item)]),
        inProgress ? el("span", { class: "menu-card-state" }, ["進行中"]) : setBars(done, total),
      ]),
      // 沒有數值又不是進行中＝這一行沒東西可放。空的 flex item 高度是 0，
      // 但 .menu-card 的 gap 照算，會讓卡片多 10px（review LOW-5）
      ...(values || inProgress
        ? [
            el("div", { class: "menu-card-foot" }, [
              el("span", { class: "menu-card-values" }, [values ?? ""]),
              ...(inProgress ? [setBars(done, total)] : []),
            ]),
          ]
        : []),
    ],
  );
  // F38：菜單每一列都要有「動作表現」入口——訓練中想查歷史曲線不該得退回首頁重選。
  // 改版把整張卡變成按鈕，巢狀按鈕不合法，所以入口與卡片並排（同 exerciseRow 的做法）。
  return exerciseRow(card, exercise, "picker");
}

// F49：選動作的三件套（搜尋框／部位 chips／清單）。自由訓練直接攤在畫面上、有課表時裝進懸浮視窗，
// 兩處共用同一份實作——搜尋與 chips 一律就地 replaceChildren 更新清單，不呼叫 render()：整頁重繪會
// 清掉正在輸入的搜尋字並讓鍵盤失焦（本專案第 N 次的「就地重畫」教訓，這次預先避開）。
function exercisePickerParts() {
  const groups = [...new Set(pickerExercises.map((e) => e.muscle_group))];
  // F23：pick-list＝動作清單，固定高度可捲動（不含今日菜單 .menu-list）
  const list = el("div", { class: "exercise-list pick-list" }, exerciseButtons());
  // list 可能在 await 期間被一次整頁重繪換掉（例如 online → syncQueue → renderUnlessTyping）——
  // 對已 detach 的節點 replaceChildren 不會報錯但更新靜默消失，故先確認還在文件裡（review P2-3 附帶）
  const repaint = () => {
    if (!list.isConnected) return;
    list.replaceChildren(...exerciseButtons());
  };

  const chips = el("div", { class: "chips" },
    groups.map((g) =>
      el(
        "button",
        {
          class: `chip${state.muscleFilter === g ? " on" : ""}`,
          onclick: (e) => {
            // 再點同一顆＝取消篩選（沿用既有語意）
            state.muscleFilter = state.muscleFilter === g ? null : g;
            for (const btn of chips.children) btn.classList.remove("on");
            if (state.muscleFilter === g) e.currentTarget.classList.add("on");
            repaint();
          },
        },
        [g],
      ),
    ),
  );

  const search = el("input", {
    type: "search",
    placeholder: "搜尋（中英皆可）",
    value: state.searchQ,
    oninput: (e) => {
      state.searchQ = e.target.value;
      guard(async () => {
        const fresh = await loadExercises(state.searchQ);
        if (fresh) repaint();
      });
    },
  });

  return [search, chips, list];
}

// F49：臨時加動作懸浮視窗（有課表時的選動作入口）。點動作即進 logger（pickExercise 換畫面，視窗隨之消失）。
function addExerciseModal() {
  const close = () => { addPanelOpen = false; render(); };
  return el(
    "div",
    {
      class: "modal-overlay",
      onclick: (e) => { if (e.target === e.currentTarget) close(); },
    },
    [
      el("div", { class: "modal pick-modal" }, [
        el("div", { class: "modal-head" }, ["臨時加動作"]),
        // F49 review P2-2：畫面上的 error-banner 會被這層遮罩蓋住——視窗內要自己顯示一份，
        // 否則視窗內搜尋失敗（離線／5xx）時使用者只看到「打了字清單沒反應」，得不到任何解釋
        ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
        ...exercisePickerParts(),
        el("button", { class: "btn add-custom-ex", onclick: openCustomForm }, ["＋ 自訂動作"]),
        el("button", { class: "btn btn-ghost", onclick: close }, ["取消"]),
      ]),
    ],
  );
}

function renderPicker() {
  // F49：有課表＝清單收進懸浮視窗（畫面留給今日菜單）；自由訓練＝選動作就是主畫面，維持攤開，
  // 否則每次開練都要多點一下才選得到動作。
  const inModal = Boolean(state.template);
  const { done, total } = menuCounts();
  const elapsed = elapsedText();

  return el("section", { class: "screen picker fills" }, [
    inModal
      ? // F83：課表名 ＋「已練 N 分 · X/Y 組」＋ 右側環形進度
        el("header", { class: "screen-head" }, [
          el(
            "button",
            {
              class: "btn icon-btn back-btn",
              "aria-label": "回首頁",
              onclick: () => { addPanelOpen = false; state.screen = "home"; render(); },
            },
            [icon("back", { size: 20, label: "回首頁" })],
          ),
          el("div", { class: "screen-head-text" }, [
            el("h1", {}, [state.template.name]),
            el("div", { class: "st" }, [
              [elapsed, `${done}/${total} 組`].filter(Boolean).join(" · "),
            ]),
          ]),
          // 動作名吃 getLang()，切換鈕若只留在自由訓練那支，用課表開練就沒地方切了
          el(
            "button",
            { class: "btn btn-ghost chip lang-toggle", onclick: () => { toggleLang(); render(); } },
            [getLang() === "zh" ? "EN" : "中"],
          ),
          progressRing(done, total),
        ])
      : el("header", { class: "topbar" }, [
          el("h1", {}, ["選動作"]),
          el(
            "button",
            { class: "btn btn-ghost chip", onclick: () => { toggleLang(); render(); } },
            [getLang() === "zh" ? "EN" : "中"],
          ),
        ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...templateMenu(),
    ...(inModal
      ? [
          el(
            "button",
            {
              class: "btn add-exercise-open",
              onclick: () =>
                guard(async () => {
                  // 每次開窗從乾淨狀態開始（同 F21 慣例）：上次無結果的搜尋字不該讓重開變空白
                  state.searchQ = "";
                  state.muscleFilter = null;
                  try {
                    await loadExercises("");
                  } catch (err) {
                    // 離線時仍要開得起來——沿用已載入的動作庫，否則有課表＋離線＝無法臨時加動作
                    // （F5 的離線記錄場景會被堵死）；非離線錯誤照舊上拋交 guard（401 導回 setup）
                    if (!isOffline(err)) throw err;
                  }
                  addPanelOpen = true;
                  render();
                }),
            },
            ["＋ 臨時加動作"],
          ),
          // F83：把下一步直接放在拇指旁邊——訓練中最常做的動作不該要人先讀完整份清單
          el("div", { class: "next-up-block" }, nextUpBlock()),
          // F29：直接從今日菜單結束訓練，不必先進 logger 才收工
          el("button", { class: "btn btn-ghost end-workout", onclick: endWorkout }, ["結束訓練"]),
        ]
      : [
          ...exercisePickerParts(),
          el("button", { class: "btn add-custom-ex", onclick: openCustomForm }, ["＋ 自訂動作"]),
          el("div", { class: "picker-foot" }, [
            el(
              "button",
              {
                class: "btn btn-ghost",
                onclick: () => { addPanelOpen = false; state.screen = "home"; render(); },
              },
              ["← 回首頁"],
            ),
            el("button", { class: "btn btn-danger", onclick: endWorkout }, ["結束訓練"]),
          ]),
        ]),
    // F49：臨時加動作視窗（有課表時）
    ...(inModal && addPanelOpen ? [addExerciseModal()] : []),
    // F10：自訂動作懸浮視窗（overlay，蓋在整個選動作畫面上；F49 起也可能疊在臨時加動作視窗上，同 F25）
    ...(customFormOpen ? [pickerCustomModal()] : []),
  ]);
}

// ---------- logger ----------

function startRestTimer() {
  state.restRestoreDropped = false; // F66 ④：開了新的一輪休息，上一輪的還原失敗提示就過去了
  state.restStartedAt = Date.now();
  state.restAccumulatedMs = 0; // F71：新的一輪休息，累計歸零
  state.restResumedAt = state.restStartedAt;
  restAlerted = false;
  // F70：目標秒數當場快照——之後換動作時倒數基準才不會跟著新動作的參考值跳掉
  state.restTargetSeconds = state.exercise
    ? restHintFor(state.exercise.id)
    : DEFAULT_REST_HINT_SECONDS;
  // F31/F62：排定「休息結束」提醒（切到別的 app 也收得到）；未開通知＝no-op
  // F89 ③：把「動作名 · 第 N 組」一起送下去給浮動視窗顯示——人在別的 app 裡時，
  // 光有秒數看不出這是哪一組（同時開兩個訓練頁的情況雖然沒有，回頭看一眼仍然要對得上）。
  if (state.exercise) {
    scheduleRestNotify(restHintFor(state.exercise.id), restHintText());
    // ⚠ 原生會在這一刻重建 overlay，所以可見性要**強制**重送一次、不吃去重。
    // 少了這一行就得倚賴原生記得上一輪的值——而那正是 2026-07-31 那個回歸的成因
    // （原生在每輪結束時把它清掉，前端因為值沒變而不再送）。兩層都修，誰忘記都不會出事。
    syncRestCardVisible(state.screen === "logger", true);
  }
  saveActiveWorkout(); // F66 ①：倒數一開始就要進持久化，否則下一秒被回收就沒了
  startRestTicker();
}

/**
 * F66 ②：只跑碼表，不碰狀態。
 *
 * 從 startRestTimer() 拆出來的原因是還原路徑——那時 state 已經由 localStorage 填好，
 * 再走一次 startRestTimer() 會把 restStartedAt 重設成「現在」，倒數就從頭開始，
 * 正是這條 feature 要消滅的行為。
 */
/** F89 ③：浮動視窗的動作提示。沒有動作時回空字串（那一行整條不畫）。 */
function restHintText() {
  if (!state.exercise) return "";
  return `${exerciseName(state.exercise)} · 第 ${state.setNumber} 組`;
}

function startRestTicker() {
  if (restTicker) clearInterval(restTicker);
  restTicker = setInterval(() => {
    // F84：休息卡是圓環了——每秒更新數字、環的比例與超時樣式。
    // 用 DOM 局部更新而不是整頁 render()：一秒一次的全畫面重繪會把使用者正在按的
    // 步進器與累度軸重建掉（原本用 .rest-led 也是同一個理由）。
    const ring = document.querySelector(".rest-ring");
    if (!ring) return;
    const remaining = restRemainingSeconds();
    if (remaining === null) return;
    const target = state.restTargetSeconds ?? DEFAULT_REST_HINT_SECONDS;
    const over = remaining <= 0;
    ring.querySelector(".digits").textContent = fmtRest(remaining);
    ring.classList.toggle("over", over);
    const value = ring.querySelector(".ring-value");
    if (value) {
      const circumference = 2 * Math.PI * 44;
      const ratio = target > 0 ? Math.min(1, Math.max(0, remaining / target)) : 0;
      value.setAttribute("stroke-dashoffset", String(circumference * (1 - ratio)));
    }
    const status = document.querySelector(".rest-status");
    if (status && !restPaused()) status.textContent = over ? "超時了" : "休息一下";
    // F84 ⑦：主按鈕與圓環同時轉 --over
    document.querySelector(".log-btn")?.classList.toggle("over", over);
    // F73 ①：跨越 0 的那一刻沒有 render()，停止鈕的警示色要在這裡一起切，
    // 否則要等下一次重繪才變——而鬧鐘正響的那幾秒正是最需要它醒目的時候
    const stopBtn = document.querySelector(".rest-controls .stop-rest");
    if (stopBtn) {
      const alarming = over && !restPaused();
      stopBtn.classList.toggle("btn-danger", alarming);
      stopBtn.classList.toggle("alarming", alarming);
    }
    if (!restAlerted && over) {
      restAlerted = true;
      // F72 ③：app 版由原生鬧鐘負責（循環鈴聲＋重複震動，響到使用者理它為止），
      // 這裡再震一次只會兩邊打架。web 版沒有那半，維持原本的單次震動。
      if (!restTimerRunning()) navigator.vibrate?.([200, 100, 200]);
    }
  }, 1000);
}

// F71 ①②：暫停／繼續。前端是狀態的事實來源，原生那半（通知列、浮動視窗）跟著同步，
// 這樣兩邊顯示才會一致——各自為政就會出現「畫面說暫停、通知還在跳」。
async function togglePauseRest() {
  if (state.restStartedAt === null) return;
  if (restPaused()) {
    resumeRest();
    restAlerted = false; // 繼續後重新武裝提醒
    // F66（review HIGH-1）：「叫醒既有服務」與「服務已經死了」是兩件事。
    // app 在暫停中被回收過的話，原生 RestTimerService 已經不存在——這時送 ACTION_RESUME
    // 會建出一個 remainingSeconds=0 的**全新實例**，CountDownTimer(0) 立刻 onFinish → 鬧鐘當場炸響，
    // 而真正該在剩餘秒數後響的那次從頭到尾沒排。所以服務不在時要用「排一次新的」重建。
    if (restTimerRunning()) await resumeRestNotify();
    else {
      const remaining = restRemainingSeconds();
      if (remaining !== null && remaining > 0) scheduleRestNotify(remaining);
    }
  } else {
    pauseRest();
    await pauseRestNotify();
  }
  saveActiveWorkout(); // F66 ⑤：暫停態與累計秒數都要落地，被回收後才還原得回同一態
  render();
}

// F71 ④：停止＝結束這段休息，等同「繼續下一組」——已累計的秒數凍結給下一組（F15 語意不變）。
async function stopRestFromUi() {
  if (state.restStartedAt === null) return;
  state.pendingRestSeconds = restElapsedSeconds();
  stopRestTimer();
  render();
}

/**
 * 結束這輪休息。
 *
 * @param {{ keepForegroundService?: boolean }} [opts] F100：原生端已經自己停好、
 *   而且要繼續活著撐住浮動視窗時傳 true——這時回送停止指令會把視窗一起關掉。
 */
function stopRestTimer({ keepForegroundService = false } = {}) {
  if (restTicker) clearInterval(restTicker);
  restTicker = null;
  state.restStartedAt = null;
  state.restAccumulatedMs = 0; // F71
  state.restResumedAt = null;
  state.restTargetSeconds = null; // F70：目標秒數的快照跟著這輪休息一起結束
  // F31/F62：休息被使用者結束（繼續下一組／收工／登出）→ 取消未觸發的提醒。
  // F70 起「換動作」不再走這裡——換個地方看不算休息結束。
  if (keepForegroundService) cancelRestNotifyScheduleOnly();
  else cancelRestNotify();
  saveActiveWorkout(); // F66：休息結束了，持久化的快照要跟著變 null（沒有 workout 時是 no-op）
}

function cycleRestHint(exerciseId) {
  const picks = [60, 90, 120, 180];
  const current = restHintFor(exerciseId);
  if (!picks.includes(current)) picks.unshift(current); // 課表自訂值（如 100s）留在循環裡
  const next = picks[(picks.indexOf(current) + 1) % picks.length];
  state.restHintOverrides = { ...state.restHintOverrides, [exerciseId]: next };
  saveActiveWorkout();
  // F70：快照要在算 remaining **之前**更新——restRemainingSeconds 現在以快照為準，
  // 慢一步就會拿舊基準算出剩餘秒數，畫面與重排的提醒各對各的（等於把 F62 那個 P2 放回來）
  if (state.restStartedAt !== null) state.restTargetSeconds = next;
  const remaining = restRemainingSeconds();
  if ((remaining ?? -1) > 0) restAlerted = false; // 目標調長回到未到點：重新武裝提醒
  // F31/F62：休息進行中改秒數 → 依新剩餘時間重排，否則仍照舊秒數響（Codex P2）
  if (state.restStartedAt !== null) {
    if (remaining !== null && remaining > 0) scheduleRestNotify(remaining, restHintText());
    else cancelRestNotify();
  }
}

// F84：±15s。設計拿掉了 60/90/120/180 的循環 chip，改成休息中直接加減——
// 「同時改剩餘與目標」是關鍵：只改剩餘的話圓環的分母不動，畫面上的比例會說謊。
const REST_STEP_SECONDS = 15;
const REST_MIN_SECONDS = 15;
const REST_MAX_SECONDS = 600;

function adjustRest(delta) {
  const exerciseId = state.exercise?.id;
  const current = state.restTargetSeconds
    ?? (exerciseId ? restHintFor(exerciseId) : DEFAULT_REST_HINT_SECONDS);
  const next = Math.min(REST_MAX_SECONDS, Math.max(REST_MIN_SECONDS, current + delta));
  if (next === current) return;
  // 寫回本次訓練的 override：這一組覺得要多休 15 秒，下一組多半也是（同 cycleRestHint 的語意）
  if (exerciseId) {
    state.restHintOverrides = { ...state.restHintOverrides, [exerciseId]: next };
    saveActiveWorkout();
  }
  if (state.restStartedAt === null) {
    render();
    return;
  }
  // 快照要在算 remaining 之前更新——慢一步就會拿舊基準算，畫面與重排的提醒各對各的
  state.restTargetSeconds = next;
  const remaining = restRemainingSeconds();
  if ((remaining ?? -1) > 0) restAlerted = false; // 調長回到未到點：重新武裝提醒
  if (remaining !== null && remaining > 0) scheduleRestNotify(remaining, restHintText());
  else cancelRestNotify();
  saveActiveWorkout(); // F66 ①：目標秒數改了，快照要跟著更新（否則還原後倒數用舊基準）
  render();
}

// 休息圓環：SVG 進度環 ＋ 中央剩餘秒數。超時時整組轉 --over（設計 ⑦）。
function restRing() {
  const target = state.restTargetSeconds
    ?? (state.exercise ? restHintFor(state.exercise.id) : DEFAULT_REST_HINT_SECONDS);
  const remaining = restRemainingSeconds() ?? target;
  const over = remaining <= 0;
  const ratio = target > 0 ? Math.min(1, Math.max(0, remaining / target)) : 0;
  const circumference = 2 * Math.PI * 44;
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNs, "svg");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("aria-hidden", "true");
  for (const cls of ["ring-track", "ring-value"]) {
    const circle = document.createElementNS(svgNs, "circle");
    circle.setAttribute("cx", "50");
    circle.setAttribute("cy", "50");
    circle.setAttribute("r", "44");
    circle.setAttribute("fill", "none");
    circle.setAttribute("stroke-width", "7");
    circle.setAttribute("class", cls);
    if (cls === "ring-value") {
      circle.setAttribute("stroke-dasharray", String(circumference));
      circle.setAttribute("stroke-dashoffset", String(circumference * (1 - ratio)));
      circle.setAttribute("stroke-linecap", "round");
    }
    svg.append(circle);
  }
  return el("div", { class: `rest-ring${over ? " over" : ""}` }, [
    svg,
    el("div", { class: "rest-ring-text" }, [
      el("span", { class: "digits" }, [fmtRest(remaining)]),
      el("span", { class: "target" }, [`/ ${target}s`]),
    ]),
  ]);
}

// 休息卡。取代就緒態的「上次提示卡＋快調列」那一整塊——其餘版面不動（設計 ④）。
function restCard() {
  const remaining = restRemainingSeconds() ?? 1;
  const paused = restPaused();
  const status = paused ? "已暫停" : remaining <= 0 ? "超時了" : "休息一下";
  return el("section", { class: "card rest-card" }, [
    el("div", { class: "rest-status" }, [status]),
    restRing(),
    el("div", { class: "rest-controls" }, [
      el(
        "button",
        { class: "btn chip", onclick: () => guard(togglePauseRest) },
        [paused ? iconLabel("play", "繼續") : iconLabel("pause", "暫停")],
      ),
      el(
        "button",
        {
          // F73 ①③：鬧鐘響著時才轉警示色（暫停中不算響）
          class: `btn chip stop-rest${
            !paused && remaining <= 0 ? " btn-danger alarming" : ""
          }`,
          onclick: () => guard(stopRestFromUi),
        },
        [iconLabel("stop", "停止")],
      ),
      el(
        "button",
        { class: "btn chip rest-minus", onclick: () => guard(() => adjustRest(-REST_STEP_SECONDS)) },
        ["−15s"],
      ),
      el(
        "button",
        { class: "btn chip rest-plus", onclick: () => guard(() => adjustRest(+REST_STEP_SECONDS)) },
        ["+15s"],
      ),
    ]),
  ]);
}

// 就緒態的「上次提示卡」。
//
// F101：原本卡片下面掛著「同上／+2.5kg／減量」三顆快調鈕，Ryan 判定多餘——±2.5 跟下方
// KG 步進器的 ±2.5 重複，「減量」語意也含糊；而卡片只顯示代表值那一組，看不到上次到底做了幾組。
// 現在卡片自己可點，點開列出上次那次訓練的**全部組**，點任一組就把值填進步進器。
// 這同時吃掉了「同上」——同上只能套代表值，這個能套任何一組。
function lastRefCard() {
  const ref = state.lastRef;
  const hasSets = state.lastSets.length > 0;
  const headline = ref
    ? `上次 ${refDateText(ref)}${ref.weight} kg × ${ref.reps}`
    : (state.lastHint ?? "第一次做這個動作");
  const delta = ref ? Math.round((state.weightKg - ref.weight) * 10) / 10 : 0;
  const head = el("div", { class: "last-ref-head" }, [
    el("span", { class: "last-ref-text" }, [headline]),
    ...(ref && delta !== 0
      ? [
          el("span", { class: `last-ref-delta${delta > 0 ? " up" : ""}` }, [
            `${delta > 0 ? "＋" : "−"}${Math.abs(delta)}`,
          ]),
        ]
      : []),
    // ⑤ 可點的線索。沒有上次紀錄時整個不畫——不要暗示一個打不開的東西
    ...(hasSets ? [el("span", { class: "last-ref-more" }, [`${state.lastSets.length} 組 ›`])] : []),
  ]);

  // ④ 第一次做這個動作＝沒得看，卡片維持純文字不可點，不要開一個空視窗
  if (!hasSets) return el("section", { class: "card last-ref" }, [head]);

  return el(
    "section",
    {
      class: "card last-ref tappable",
      role: "button",
      tabindex: "0",
      "aria-label": "看上次這個動作的全部紀錄",
      onclick: () => { state.lastSetsOpen = true; render(); },
      onkeydown: (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          state.lastSetsOpen = true;
          render();
        }
      },
    },
    [head],
  );
}

// F101 ②：上次那次訓練這個動作的全部組。資料用既有的 lastSets 回傳陣列，不新增 API。
function lastSetsModal() {
  const close = () => { state.lastSetsOpen = false; render(); };
  // ③ 點任一組＝把該組的重量與次數填進步進器並關窗。**只填值不送出**——
  // 沿用原本快調列的分寸；直接送出會讓「我只是想看看」變成一筆真的紀錄
  const applySet = (s) => {
    state.weightKg = s.weight_kg;
    state.reps = s.reps;
    state.lastSetsOpen = false;
    render();
  };
  const dateText = state.lastRef?.date ? refDateText(state.lastRef).replace(" · ", "") : "";
  return el(
    "div",
    { class: "modal-overlay", onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    [
      el("div", { class: "modal last-sets-modal" }, [
        el("div", { class: "modal-head" }, [
          `上次 ${dateText}${dateText ? " · " : ""}${exerciseName(state.exercise)}`,
        ]),
        el("p", { class: "confirm-text" }, ["點任一組把數值帶進來（不會直接記錄）"]),
        el(
          "div",
          { class: "last-sets-list" },
          state.lastSets.map((s, i) =>
            el("button", { class: "btn last-set-row", onclick: () => applySet(s) }, [
              el("span", { class: "set-no" }, [`#${i + 1}`]),
              el("span", { class: "n" }, [`${s.weight_kg} kg × ${s.reps}`]),
              ...(s.rpe != null ? [el("span", { class: "rpe" }, [RPE_WORDS[s.rpe] ?? ""])] : []),
            ]),
          ),
        ),
        el("div", { class: "modal-actions" }, [
          el("button", { class: "btn btn-ghost", onclick: close }, ["關閉"]),
        ]),
      ]),
    ],
  );
}

function refDateText(ref) {
  if (!ref.date) return "";
  const [, month, day] = ref.date.split("-");
  return `${Number(month)}/${Number(day)} · `;
}

function renderLogger() {
  const exercise = state.exercise;

  const logSet = async () => {
    if (state.submitting) return; // 防手機雙擊重複送出
    state.submitting = true;
    try {
      const payload = {
        client_uuid: crypto.randomUUID(),
        exercise_id: exercise.id,
        set_number: state.setNumber,
        weight_kg: state.weightKg,
        reps: state.reps,
        rpe: state.rpe, // F40：累度軸一律有值（6–10），新組必帶 rpe
        // F15：rest_seconds 來自按「繼續下一組」凍結的值（第一組無、故不帶）。
        // F70 ③ 不必在這裡加第二條來源：休息中按鈕一律是「繼續下一組」，
        // 所以「休息還在跑就直接記組」在 UI 上不存在——跨畫面回來記組仍會先經過凍結那一步。
        ...(state.pendingRestSeconds != null ? { rest_seconds: state.pendingRestSeconds } : {}),
      };
      let saved;
      try {
        saved = await api.logSet(state.workoutId, payload);
      } catch (err) {
        if (!isOffline(err)) throw err;
        await enqueueSet(state.workoutId, payload); // 離線：入列緩衝，恢復連線自動補傳
        saved = payload; // 標示由 state.queueStatus 推導，不另存旗標
        await refreshQueueCounts();
      }
      // 到這裡才代表這組已保住（線上成功 or 離線入列成功）——此時才清凍結休息值；
      // 若上面丟錯（非離線錯誤或入列失敗），pendingRestSeconds 保留，重試的 payload 仍帶 rest_seconds
      state.pendingRestSeconds = null;
      state.doneSets.push(saved);
      // setCounts＝**完成組數**（menuCounts 的課表進度靠它），不是組號。
      // 刪掉中間某組後兩者會分岔，下一組的編號改由 nextSetNumber() 從最大組號推。
      // 取 max 而非直接指派：doneSets 可能不完整——舊狀態（沒有 doneByExercise 鏡射）
      // 遇上離線時，pickExercise 的伺服器回填會失敗、doneSets 留空，
      // 這時直接用長度會把先前存下的 N 組進度覆寫成 1 並持久化（Codex P2）。
      // 刪組要讓數字降下來是走 reconcile 那條路，不受這裡的 max 影響。
      state.setCounts[exercise.id] = Math.max(
        state.doneSets.length,
        state.setCounts[exercise.id] || 0,
      );
      state.setNumber += 1;
      state.rpe = 6; // F40：記完重置回預設「輕鬆」（下一組不碰即帶 6）
      rememberDoneSets(); // F32：換動作後回到此動作可還原本次組
      saveActiveWorkout(); // setCounts/doneByExercise 持久化：重新整理後編號續接、組不丟
      startRestTimer(); // 招牌時刻：LED 亮起＝已記錄
    } finally {
      state.submitting = false;
    }
    render();
  };

  // F15：休息態按「繼續下一組」——凍結本次休息（含超時的絕對值）給下一組、停倒數、回就緒態
  const continueNext = () => {
    state.pendingRestSeconds = restElapsedSeconds();
    stopRestTimer();
    render();
  };

  const finish = () => {
    // F70 ①：換動作**不再**結束休息——「換個地方看」不等於「休息結束」。
    // 倒數、通知列與浮動視窗照常走完；真正結束休息的只有「繼續下一組」與收工（②）。
    state.pendingRestSeconds = null; // 換動作：未用的凍結休息值不跨動作帶
    // F66 ④（review MEDIUM-3）：「倒數沒還原」的提示看過一次就夠。離開 logger 就消掉，
    // 否則它會黏著整個 session——每次回到 logger 都再說一次同一件已經知道的事。
    state.restRestoreDropped = false;
    editDraft = null; // 離開 logger 清編輯草稿，否則殘留會讓下個動作的 scrollable 失效（F20/Codex P2）
    state.exercise = null;
    state.screen = "picker";
    render();
  };

  // ---------- F16 done-list 行內編輯/刪除 ----------
  const replaceInDone = (target, next) => {
    state.doneSets = state.doneSets.map((x) => (x === target ? next : x));
  };

  const deleteDoneSet = async (s) => {
    if (s.id != null) {
      try {
        await api.deleteSet(s.id); // 已同步：軟刪
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err; // 404＝已刪，視為成功（防連點重送）
      }
    } else {
      await removeQueued(s.client_uuid); // 未同步：移出佇列
      await refreshQueueCounts();
    }
    state.doneSets = state.doneSets.filter((x) => x !== s);
    // 同步本動作完成組數（否則課表選單仍顯示 3/3、menu-done 誤標）＋續接編號避開缺口（Codex P2）
    state.setCounts = { ...state.setCounts, [state.exercise.id]: state.doneSets.length };
    state.setNumber = state.doneSets.reduce((m, x) => Math.max(m, x.set_number), 0) + 1;
    rememberDoneSets(); // F32：刪組後鏡射同步，換動作後還原不含已刪組
    saveActiveWorkout();
    render();
  };

  const saveEditDoneSet = async (s) => {
    const { weight: w, reps: r, rpe } = editDraft; // 值由 steppers 就地維護，邊界已保證
    if (s.id != null) {
      const updated = await api.updateSet(s.id, {
        weight_kg: w,
        reps: r,
        ...(rpe ? { rpe } : {}),
        ...(s.rest_seconds != null ? { rest_seconds: s.rest_seconds } : {}),
      });
      replaceInDone(s, updated); // 原位 PATCH
    } else {
      const payload = { ...s, weight_kg: w, reps: r, rpe }; // 未同步：覆蓋佇列同 client_uuid
      await enqueueSet(state.workoutId, payload);
      replaceInDone(s, payload);
    }
    editDraft = null;
    rememberDoneSets(); // F32：編輯後鏡射同步，換動作後還原帶回修改值
    saveActiveWorkout();
    render();
  };

  const doneRow = (s) => {
    const key = setRowKey(s);
    if (editDraft && editDraft.key === key) {
      return el("div", { class: "done-row editing" }, [
        el("div", { class: "edit-head" }, [`編輯 #${s.set_number}`]),
        el("div", { class: "steppers" }, [
          stepper(exercise.is_bodyweight ? "負重 KG" : "KG", editDraft.weight, [
            ["−2.5", -2.5],
            ["+2.5", +2.5],
          ], (d) => { editDraft.weight = Math.max(0, Math.round((editDraft.weight + d) * 10) / 10); }, render,
          { set: (v) => { editDraft.weight = v; }, parse: parseWeight }),
          stepper("REPS", editDraft.reps, [
            ["−1", -1],
            ["+1", +1],
          ], (d) => { editDraft.reps = Math.max(1, editDraft.reps + d); }, render,
          { set: (v) => { editDraft.reps = v; }, parse: parseReps }),
        ]),
        rpePicker(editDraft.rpe, (v) => { editDraft.rpe = v; }, render),
        el("div", { class: "edit-actions" }, [
          el("button", { class: "btn btn-primary sm save-edit", onclick: () => guard(() => saveEditDoneSet(s)) }, ["儲存"]),
          el("button", { class: "btn btn-ghost sm", onclick: () => { editDraft = null; render(); } }, ["取消"]),
        ]),
      ]);
    }
    const queued = state.queueStatus[s.client_uuid]; // pending | failed | undefined（已同步）
    // F76：同步狀態標示改向量圖示——emoji 在不同 Android 版本長相不一，而這裡要一眼分辨
    // 「還在傳」與「傳失敗」，兩者的後果差很多
    const mark = queued === "pending"
      ? [icon("hourglass", { size: 14, label: "待同步" })]
      : queued === "failed"
        ? [icon("warning", { size: 14, label: "同步失敗" })]
        : [];
    return el("div", { class: `done-row${queued ? ` ${queued}` : ""}` }, [
      el("span", { class: "set-no" }, [`#${s.set_number}`, ...mark]),
      el("span", { class: "n" }, [`${s.weight_kg} kg × ${s.reps}`]),
      // F84 ③：顯示口語詞而不是 @6——記錄時選的就是詞，回看時卻要自己換算數字
      ...(s.rpe ? [el("span", { class: "done-rpe" }, [RPE_WORDS[s.rpe] ?? `@${s.rpe}`])] : []),
      el("button", {
        class: "btn icon-btn edit-set",
        onclick: () => {
          editDraft = { key, weight: s.weight_kg, reps: s.reps, rpe: s.rpe ?? 6 };
          render();
        },
      }, [icon("pencil", { size: 18, label: "編輯這組" })]),
      el("button", {
        // F19：單擊即刪（軟刪／未同步移出佇列，資料非真的消失），不再兩段式確認
        class: "btn icon-btn del-set",
        onclick: () => guard(() => deleteDoneSet(s)),
      }, [icon("trash", { size: 18, label: "刪除這組" })]),
    ]);
  };

  const resting = state.restStartedAt !== null;
  const overtime = resting && (restRemainingSeconds() ?? 1) <= 0;

  return el("section", { class: "screen logger" }, [
    // F84 ①：返回 ＋ 動作名／英文名 · 第 N 組 ＋ 動作表現
    el("header", { class: "exercise-head" }, [
      // F42：左上返回箭頭——回動作選擇 picker（等同原『換動作』，不結束訓練、workout 保留）
      el("button", {
        class: "btn icon-btn logger-back", "aria-label": "回動作選擇",
        onclick: finish,
      }, [icon("back", { size: 20, label: "回動作選擇" })]),
      el("div", { class: "exercise-head-name" }, [
        el("h2", {}, [exerciseName(exercise)]),
        el("span", { class: "alias" }, [
          `${exerciseAlias(exercise)} · 第 ${state.setNumber} 組`,
        ]),
      ]),
      // F38：練到一半查當前動作歷史；返回不丟進行中訓練
      el("button", {
        class: "btn detail-link logger-detail", "aria-label": "動作表現",
        onclick: () => openDetail(exercise, "logger"),
      }, [icon("trending", { size: 18, label: "動作表現" })]),
    ]),
    // F84 ④：休息態把「上次提示卡＋快調列」整塊換成休息卡，其餘版面不動
    resting ? restCard() : lastRefCard(),
    // F66 ④：存過休息但還原不了時，在倒數本來該在的地方講一句。
    // 不得靜默——不然使用者以為倒數還在跑，回頭一看什麼都沒有。
    ...(!resting && state.restRestoreDropped
      ? [el("div", { class: "notice-banner" }, ["休息倒數已過期，沒有還原（訓練本身還在）"])]
      : []),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...syncStatusLine(),
    // F20：新→舊排序（最新在最上）；組數 > 2 時固定高度內部捲動（編輯中不限高，讓編輯表單完整可見）
    ...(state.doneSets.length > 0
      ? [
          el("section", {
            class: `card done-list${
              state.doneSets.length > 2 && !editDraft ? " scrollable" : ""
            }`,
          }, [...state.doneSets].reverse().map(doneRow)),
        ]
      : []),
    el("div", { class: "logger-foot" }, [
      el("div", { class: "steppers" }, [
        stepper(exercise.is_bodyweight ? "負重 KG" : "KG", state.weightKg, [
          ["−2.5", -2.5],
          ["+2.5", +2.5],
        ], (d) => { state.weightKg = Math.max(0, Math.round((state.weightKg + d) * 10) / 10); }, render,
        { set: (v) => { state.weightKg = v; }, parse: parseWeight }),
        stepper("REPS", state.reps, [
          ["−1", -1],
          ["+1", +1],
        ], (d) => { state.reps = Math.max(1, state.reps + d); }, render,
        { set: (v) => { state.reps = v; }, parse: parseReps }),
      ]),
      rpePicker(state.rpe, (v) => { state.rpe = v; }, render),
      el(
        "button",
        {
          // F15 兩態切換：就緒態（未在休息）＝記錄；休息態＝繼續下一組（停倒數）
          // F84 ⑦：超時時主按鈕也轉 --over，與圓環、數字同步
          class: `btn btn-primary log-btn${resting ? " resting" : ""}${
            overtime ? " over" : ""
          }`,
          ...(state.submitting ? { disabled: "" } : {}),
          onclick: () => guard(resting ? continueNext : logSet),
        },
        [resting ? el("span", {}, ["繼續下一組"]) : iconLabel("check", "完成這組")],
      ),
    ]),
    // F42：底部『換動作』『收工』已移除——換動作改左上←，結束訓練走 picker 的『結束訓練』
    // F101：上次全部紀錄的視窗（點上次提示卡開啟）
    ...(state.lastSetsOpen && state.lastSets.length > 0 ? [lastSetsModal()] : []),
  ]);
}

// ---------- render ----------

// F48：每次重繪前先把可捲清單當下的位置抓下來（唯一事實來源＝DOM）。
// 放在 render() 開頭是因為畫面切換（picker → logger）不會呼叫另一個畫面的 render 函式，
// 位置只能在舊 DOM 還在時抓；掛 onscroll 記錄則會被節點拆除時補送的 scrollTop=0 覆寫。
function captureScrollPositions() {
  const menu = document.querySelector(".menu-list");
  if (menu) menuScrollTop = menu.scrollTop;
  captureTemplateListScroll();
  captureBodyScroll(); // F53：體重頁紀錄清單
}

// F81：回首頁前先把首頁那三張卡的資料重抓一次——記完組回來，本週進度與上次訓練都變了。
// 失敗不擋路（loadHome 內部吞掉），首頁照樣開得起來。
function backHome() {
  guard(async () => {
    await loadHome(); // 401 會在這裡拋出 → guard 導回重新登入，不會再往下設 home
    state.screen = "home";
    render();
  });
}

function render() {
  captureScrollPositions();
  // F49 review P2-1：回到 setup／home＝離開訓練情境，picker 的兩個懸浮視窗一律關閉。
  // 收斂成不變式而不是在每個離場點手動歸零——401（guard 導回 setup）就是漏掉的那條路：
  // 重新登入後按「繼續訓練」，picker 會自己蓋上視窗。刻意不含 logger／exerciseDetail：
  // 前者由 pickExercise 歸零，後者的往返要保留視窗（瀏覽中途離開，回來接續）。
  if (state.screen === "setup" || state.screen === "home") {
    addPanelOpen = false;
    customFormOpen = false;
  }
  const screens = {
    setup: renderSetup,
    home: renderHome,
    settings: renderSettings,
    templateSelect: renderTemplateSelect,
    picker: renderPicker,
    trends: renderTrends,
    logger: renderLogger,
    templates: () =>
      renderTemplates(render, backHome, guard),
    templateEdit: () => renderTemplateEdit(render, guard),
    calendar: () => renderCalendar(render, backHome, guard),
    body: () => renderBody(render, backHome, guard),
    exerciseDetail: () =>
      renderExerciseDetail(
        render,
        () => {
          state.screen = detailReturnScreen(); // F38：返回來源畫面（picker／logger），狀態不丟
          render();
        },
        guard,
      ),
  };
  root.replaceChildren(screens[state.screen]());
  syncWakeLock(); // fire-and-forget：logger 畫面取得、其他畫面釋放
  // F69 ①③：浮動視窗只在看不到 app 內倒數時出現。判準跟畫面本身綁在一起——
  // REST 卡片就是在 logger 且休息中才畫，這裡照抄同一個條件，不另立一套（另立就會走鐘）
  // F103 ②：判斷依據是「人在計時頁面」，不是「REST 卡片可見」。
  // 舊條件在停止之後不成立（前端那份倒數已收掉、畫面上沒有卡片），視窗於是賴在 app 上面
  // ——而那正是使用者按「回 app 記下一組」之後看到的畫面。
  syncRestCardVisible(state.screen === "logger");
}

// F67：查有沒有新版。失敗一律當作沒有更新（checkForUpdate 內部吞掉），
// 所以不需要 catch，也不會因為伺服器沒發佈版本就在畫面上留下錯誤。
function runUpdateCheck() {
  checkForUpdate().then((update) => {
    if (!update) return;
    pendingUpdate = update;
    // F68 ①②：沒被「稍後再說」靜音過的版本就自動彈窗；靜音過的只留橫幅當入口
    if (!isDismissed(update.versionCode)) updateModalOpen = true;
    if (state.screen === "home") render();
  });
}

// ---------- 啟動 ----------

// F61：app 版不註冊 SW——資產已打包在 APK 內，殼快取毫無用處，反而多一層可能供出舊資產的來源；
// F13/F14/F24 的線上更新鏈本來就只對 web 版成立（app 版改版靠重 build，見 README 已知限制）。
// 離線寫入不受影響：佇列在 js/queue.js 走 IndexedDB，與 SW 無關。
if (!isNativeApp() && "serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {
    /* SW 註冊失敗不影響線上使用 */
  });
  // F14 部署自動到位：新 SW 接管（controllerchange）就自動重載一次，開 app 即是新版。
  // 「首次安裝」的初次接管不重載（頁面本來就已是最新，多刷一次多餘）——但只跳過那一次；
  // 之後任何一次接管（部署新版）都要重載，否則首訪者若不關頁面，下次部署就更新不到。
  const hadController = Boolean(navigator.serviceWorker.controller);
  let skippedInitialClaim = false;
  let refreshing = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (refreshing) return; // 防 reload 循環：每次接管只 reload 一次
    if (!hadController && !skippedInitialClaim) {
      skippedInitialClaim = true; // 首裝的初次接管跳過，但下次部署的接管仍會重載
      return;
    }
    refreshing = true;
    // 若課表未儲存，beforeunload 提示可能讓使用者取消重載、頁面存活——復原 latch，
    // 否則之後的接管都被忽略、F14 自動更新永久失效（Codex P2）。reload 成功時頁面已卸載，此計時器不會執行
    setTimeout(() => { refreshing = false; }, 3000);
    location.reload();
  });
}
// 課表編輯有未儲存變更時，重整/關閉分頁/離開前跳瀏覽器原生警告，避免手滑丟失編輯。
// 只在編輯畫面且草稿與進場基準不同才攔截——其他畫面（記錄每組即時寫入、表單 POST 即存）無未存資料。
window.addEventListener("beforeunload", (e) => {
  saveTemplateDraft(); // F30：卸載前先存草稿（手機上 beforeunload 提示常不顯示，但這行仍會執行）
  if (hasUnsavedTemplate()) {
    e.preventDefault();
    e.returnValue = ""; // Chrome 需設 returnValue 才觸發原生確認框
  }
});
window.addEventListener("online", () => guard(syncQueue)); // 恢復連線：自動補傳佇列
document.addEventListener("visibilitychange", () => {
  syncWakeLock();
  if (document.hidden) saveTemplateDraft(); // F30：切背景/OS 準備殺分頁前存草稿（手機最可靠的存檔時機）
  // F62 review HIGH：原生殼切回前景**不會重新載入頁面**，只在開機 refresh 的話，
  // 「跑去系統設定改通知／精確鬧鐘再切回來」永遠反映不到——⑤ 的靜默失敗會從這條路復活，
  // 而照 README 去開精確鬧鐘的人也會看到按鈕永遠停在「可能延遲」。
  if (!document.hidden) {
    refreshRestNotifyState().then(() => {
      // ⚠ 不能只在首頁重繪。F81 把通知開關搬進**設定畫面**之後，「跑去系統設定關掉
      // 這類通知再切回來」剛好落在唯一不重繪的畫面上——開關繼續顯示舊狀態，
      // 上面那條 F62 review HIGH 就這樣悄悄復活了（2026-07-30 真機實測抓到）。
      // 兩個畫面都會顯示這些狀態，兩個都要更新。
      if (state.screen === "home" || state.screen === "settings") render();
    });
  }
});

loadEnvLabel(); // F93：開站就問一次「我連到哪一站」（免 auth，setup 畫面也顯示得出來）
restoreActiveWorkout();
resumeRestAfterRestore();

/**
 * F66 ②③④：restoreActiveWorkout() 只把狀態填回 state，碼表與提醒要在這裡接回去。
 *
 * 分成兩支的理由同 F90：state.js 那半是純粹的同步狀態還原（好測、無副作用），
 * 碼表（setInterval）與通知（原生外掛）是副作用，留在 app.js。
 */
async function resumeRestAfterRestore() {
  // 沒有 token 就停在 setup 畫面——那個 app 連不進去，卻讓碼表跑著、鬧鐘照排，
  // 幾分鐘後在一個進不去的畫面上響（review LOW-5）。401 那條路有 guard 的
  // stopRestTimer() 擋著，開機這條原本沒有。
  if (!getToken()) return;
  // ④ 存過休息但還原不了（過舊或壞資料）→ 旗標留著，由 logger 在「倒數本來該在的位置」
  // 講出來。**不要**用 state.error：那個一換畫面就被清掉，而還原後人是先落在首頁的，
  // 等他走回 logger 時提示早就沒了——那還是靜默沒有倒數。
  if (state.restRestoreDropped) return;
  if (state.restStartedAt === null) return;

  const remaining = restRemainingSeconds();
  // 已經超時的話不要再武裝一次提醒——還原當下立刻震動／響鈴，等於把使用者嚇一跳，
  // 而該響的那一次在被回收之前就已經由原生鬧鐘響過了。
  restAlerted = remaining !== null && remaining <= 0;
  startRestTicker(); // 碼表先跑——它是同步的，不該等權限查詢

  // ⚠ 排通知前**必須先等權限快取回來**。app 版的「有沒有授權」是非同步查的，
  // 開機當下 cache 還是空的，直接排會被 nativeNotifyEnabled() 擋掉而**靜默失敗**——
  // 畫面有倒數、通知卻沒排，正是這條 feature 要消滅的那種無聲落差。
  await refreshRestNotifyState();

  // ③ 依**剩餘**秒數重排（不是原本的目標秒數）；已超時則不排。
  // 暫停中也不排——F71 的暫停語意是「時間不走」，排了就會在不該響的時候響。
  // 秒數在等待期間會往前走，所以重算一次而不是沿用上面那個。
  const now = restRemainingSeconds();
  if (!restPaused() && now !== null && now > 0) scheduleRestNotify(now, restHintText());
}

/**
 * F90 ③④：向伺服器確認還原出來的 workout 還在，並用伺服器的組數重建 set 編號。
 *
 * 伺服器是唯一事實來源，localStorage 只是快取——快取可能指向已被刪掉的 workout（④），
 * 也可能因為某次寫入沒成功而少算組數，那會讓下一組撞號。
 *
 * 三條路徑刻意分開：
 * - 404：那場 workout 真的不在了 → 清掉本地，退回「開始訓練」
 * - status 0（連不上）：**不能清**。離線時清掉等於健身房沒網路就把進行中的訓練弄丟，
 *   比原本的 bug 更糟（handoff 記過「權限/環境問題會偽裝成資料不存在」）
 * - 其他（含 401）：交給既有的全域 guard，這裡不動狀態
 */
async function confirmActiveWorkout() {
  const confirming = state.workoutId; // 送出當下的 id，用來擋過期回應（Codex P1）
  if (!confirming) return;

  /** 這個回應是不是還對應「現在」這場訓練。 */
  const stillCurrent = () => state.workoutId === confirming;

  /** 快取指向的訓練不存在／不是今天 → 清掉，並把人帶離已經沒有依據的畫面。 */
  const dropStale = (message) => {
    // F66（review HIGH-2）：這場訓練沒了，掛在它上面的休息倒數也要一起收掉。
    // 不收的話：①鬧鐘仍會在幾分鐘後為一場已不存在的訓練響 ②下一場訓練一進 logger
    // 就顯示上一場殘留的休息卡（restStartedAt 還不是 null）。
    // F66 之前撞不到——開機時 restStartedAt 恆為 null，是這次還原路徑新開的洞。
    stopRestTimer(); // 內含 cancelRestNotify()
    clearActiveWorkout();
    state.error = message;
    // 慢網路下使用者可能已經按「繼續訓練」進了 picker，清掉 workoutId 後留在那裡的話，
    // 下一次記組會送去 /api/workouts/null/sets（Codex P2）。
    // **同步**切畫面再重繪，不走 backHome()——那支要等 loadHome() 回來才換畫面，
    // 首頁資料慢或失敗時，那段空窗仍然可以從 picker 進 logger 記組（Codex 複審 P2）。
    state.screen = "home";
    render();
    guard(async () => {
      await loadHome(); // 資料稍後補上；這時人已經不在訓練畫面了
      render();
    });
  };

  let detail;
  try {
    detail = await api.workoutDetail(confirming);
  } catch (err) {
    if (!stillCurrent()) return; // 期間已換了一場訓練，這個 404 不是在講它
    if (err instanceof ApiError && err.status === 404) {
      dropStale("先前的訓練已不存在，請重新開始一場");
    }
    return; // 離線／401：保留本地狀態
  }
  if (!stillCurrent()) return;

  // F91 ⑤：伺服器說這場已經結束了 → 不續接。這是跨裝置的那條路——
  // 在手機按結束，網頁那份快取不知道，重整就會把已結束的訓練接下去。
  if (detail.ended_at) {
    dropStale("這場訓練已經結束了");
    return;
  }
  // ②：日期以伺服器為準。本地快取可能是遷移過來的、或跨午夜後被舊版寫歪的。
  if (detail.date !== todayIso()) {
    dropStale("上一場訓練是別天的，已為你收起");
    return;
  }
  state.workoutDate = detail.date;

  // 伺服器是基礎，離線佇列是唯一的例外——只把「確實還躺在佇列裡、屬於這場訓練」的組加回來。
  // 反過來（本地鏡射整段覆蓋伺服器）會讓別處刪掉的組復活、改過的值退回舊快照（Codex P2）。
  let queued = [];
  try {
    queued = (await listQueued()).filter(
      (e) => e.status === "pending" && e.workout_id === confirming,
    );
  } catch {
    /* 佇列讀不到就只信伺服器 */
  }
  if (!stillCurrent()) return;

  const grouped = {};
  for (const s of detail.sets) (grouped[s.exercise_id] ??= []).push(s);
  // 用 client_uuid 排掉「已經送達伺服器、但佇列裡還留著」的殘影：POST 成功而回應途中斷線時，
  // 那筆會同時出現在 detail.sets 與待送佇列，無條件附加就會重複計組（SetOut 為此補了這個欄位）。
  const onServer = new Set(detail.sets.map((s) => s.client_uuid));
  for (const e of queued) {
    if (onServer.has(e.client_uuid)) continue;
    (grouped[e.payload.exercise_id] ??= []).push(e.payload);
  }
  for (const arr of Object.values(grouped)) {
    arr.sort((a, b) => (a.set_number ?? 0) - (b.set_number ?? 0));
  }

  state.doneByExercise = grouped;
  // setCounts＝完成組數（課表進度用）。下一組的編號不從這裡推，由 nextSetNumber() 取
  // doneByExercise 的最大組號——上面剛把鏡射換成伺服器版本，那份才是組號的依據。
  state.setCounts = Object.fromEntries(
    Object.entries(grouped).map(([id, arr]) => [id, arr.length]),
  );
  saveActiveWorkout();
  render();
}
guard(confirmActiveWorkout);
// F62：app 版的通知權限／精確鬧鐘狀態是非同步查詢，但 render() 是同步的——
// 啟動時先查一次填進 cache，查完重繪讓開關顯示真實狀態（web 版是同步判定，這裡 no-op）。
// ⚠ 這裡只更新「權限狀態」，**不重排通知**：休息倒數（state.restStartedAt）本來就不持久化，
// app 被重啟後倒數與已排定的通知都會消失且畫面無提示。那是 F62 之前就有的行為，不在本 feature 範圍。
refreshRestNotifyState().then(() => {
  if (state.screen === "home") render();
});
// F71 ⑥：原生端（浮動視窗）的暫停／繼續／停止回傳。只訂閱一次，事件驅動不輪詢。
// 前端仍是狀態的事實來源——原生只回報「使用者按了什麼」，實際的計時狀態在這裡改。
subscribeRestControl((action, seconds) => {
  // F103 ③：「再開始」是唯一在「前端這份倒數已經停掉」時仍要處理的動作——
  // 其餘動作沒有進行中的休息就無事可做。這個判斷要放在 restStartedAt 檢查之前。
  if (action === "restart") {
    if (seconds === null) return; // 舊版 APK 不帶秒數：寧可不動，也不要憑空猜一個起點
    restartRestFromNative(seconds, haltedRestElapsed);
    haltedRestElapsed = 0;
    startRestTicker();
    render();
    return;
  }
  if (state.restStartedAt === null) return;
  if (action === "pause" && !restPaused()) pauseRest();
  else if (action === "resume" && restPaused()) resumeRest();
  else if (action === "stop") {
    state.pendingRestSeconds = restElapsedSeconds(); // ④：等同繼續下一組
    stopRestTimer();
  } else if (action === "halt") {
    // F100：浮動視窗的停止＝停鈴並歸位，服務與視窗都留著。前端只收掉自己那份倒數，
    // **不得**回送停止指令——那會把剛剛要留下的視窗一起關掉。
    // F103 ③：記下這輪已經休息掉多少，「再開始」時接回去（同一輪休息不該從零重算）。
    haltedRestElapsed = restElapsedSeconds() ?? 0;
    state.pendingRestSeconds = haltedRestElapsed;
    stopRestTimer({ keepForegroundService: true });
  } else if (action === "plus15" || action === "minus15") {
    // F103 ⑥：原生早就在送這兩個事件，但前端一直沒接——在視窗調完秒數回到 app，
    // 卡片與通知列的倒數是對不上的。
    if (seconds === null || !syncRestTargetFromNative(seconds)) return;
  } else return;
  render();
});
// F67：查有沒有新版（見上方 runUpdateCheck 的說明）。只在已有 token 時查——
// setup 畫面查一定 401，而且那次失敗會讓首次設定的人到下次開 app 才看得到更新。
if (getToken()) runUpdateCheck();
if (!getToken()) {
  state.screen = "setup";
  render();
} else {
  restoreTemplateDraft(); // F30：有未存的課表草稿就還原進編輯畫面（比 beforeunload 提示可靠）
  render();
  // F81：首頁三張卡的資料。先畫再補——沒有它首頁也開得起來，不讓網路擋住第一次繪製
  guard(async () => {
    await loadHome();
    if (state.screen === "home") render();
  });
  guard(loadExercises); // 預載動作庫，token 失效會導回 setup
  guard(syncQueue); // 開站補傳上次離線留下的佇列
}
