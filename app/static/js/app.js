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
import { el, rpePicker, stepper } from "./dom.js";
import { isNativeApp } from "./env.js";
import {
  detailReturnScreen,
  openExerciseDetail,
  renderExerciseDetail,
} from "./exercise-detail.js";
// F62：休息提醒改走 rest-notify 這層統一入口（web＝F31 Web Push／app＝手機端本機通知）
import {
  cancelRestNotify,
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
  restOverlaySupported,
  scheduleRestNotify,
  subscribeRestControl,
  syncRestCardVisible,
} from "./rest-notify.js";
import {
  discardFailed,
  enqueueSet,
  flushQueue,
  listQueued,
  queueCounts,
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
  restPaused,
  restRemainingSeconds,
  restoreActiveWorkout,
  resumeRest,
  saveActiveWorkout,
  state,
  toggleLang,
} from "./state.js";

const root = document.getElementById("app");
let restTicker = null;
let wakeLock = null; // R10：logger 畫面保持螢幕常亮，離開時釋放
let wakeLockPending = false; // request 進行中——完成時要重驗畫面狀態，避免離開後鎖洩漏
let restAlerted = false; // 本段休息是否已提醒過；調長目標後重新武裝
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
  // R10 倒數顯示：到 0 之後轉負數（-00:15＝超時 15 秒），實際量測照舊
  return remaining < 0 ? `-${fmtClock(-remaining)}` : fmtClock(remaining);
}

// F24：畫面角落的版本標記——手機載入哪版一眼可辨（快取過期會顯示舊版號）
function versionTag() {
  // F68 ③⑦：app 版的版號身兼三職——顯示目前版本、提示有新版（`v67 → v68`）、
  // 以及手動檢查的入口。原本另有一條更新橫幅，2026-07-28 回簽核拿掉：
  // 兩個入口重疊，而提示併進版號就不必多佔一行版面。
  // web 版維持純文字：那邊部署完自動到位，沒有「檢查更新」這回事。
  if (!isNativeApp()) return el("div", { class: "version-tag" }, [APP_VERSION]);
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
              if (state.screen === "home") render();
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
  state.doneByExercise = Object.fromEntries(
    Object.entries(state.doneByExercise).map(([id, arr]) => [id, mapArr(arr)]),
  );
  saveActiveWorkout();
}

async function syncQueue() {
  const before = state.queue;
  const synced = await flushQueue(api.logSet);
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
  if (changed) renderUnlessTyping();
}

function syncStatusLine() {
  const { pending, failed } = state.queue;
  if (pending === 0 && failed === 0) return [];
  const parts = [];
  if (pending > 0) parts.push(el("span", { class: "sync-pending" }, [`⏳ 待同步 ${pending} 組`]));
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
        [`⚠ 同步失敗 ${failed} 組（點此捨棄）`],
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
    state.screen = "home";
    render();
    runUpdateCheck(); // F67：剛設好 token 才查得動——開機那次在 setup 畫面必然 401
  };
  return el("section", { class: "screen setup" }, [
    el("div", { class: "mark" }, ["🏋️"]),
    el("h1", {}, ["lift-log"]),
    el("p", {}, ["輸入 API token 開始使用（存在這支手機上）"]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    input,
    el("button", { class: "btn btn-primary", onclick: () => guard(save) }, ["連線"]),
    versionTag(),
  ]);
}

// ---------- home ----------

async function goPicker() {
  if (pickerExercises.length === 0) await loadExercises("");
  state.screen = "picker";
  render();
}

async function startWorkout(template) {
  const workout = await api.createWorkout(template ? { template_id: template.id } : {});
  state.workoutId = workout.id;
  state.template = template; // 課表快照跟著這次訓練走，之後刪課表不受影響
  menuScrollTop = 0; // F48（Codex P2）：捲動位置屬於「這次訓練的菜單」——換一次訓練要從頂端開始，
  //                    否則舊偏移量會蓋在新課表上，前幾個動作被藏在捲動區上方
  saveActiveWorkout();
  await goPicker();
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
  return el("section", { class: "screen" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, ["lift-log"]),
      el("span", { class: "date" }, [todayLabel()]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...syncStatusLine(),
    el("p", { class: "today-summary" }, [
      state.workoutId ? "今天的訓練還開著——繼續。" : "還沒開始。按下去，就是今天的第一組。",
    ]),
    el(
      "button",
      { class: "btn btn-primary home-start", onclick: () => guard(start) },
      [state.workoutId ? "繼續訓練" : "開練"],
    ),
    el(
      "button",
      {
        class: "btn",
        onclick: () =>
          guard(async () => {
            await openTemplates();
            resetTemplateListScroll(); // F48：從首頁進課表頁一律從頂端
            state.screen = "templates";
            render();
          }),
      },
      ["📋 課表"],
    ),
    el(
      "button",
      {
        class: "btn",
        onclick: () =>
          guard(async () => {
            await openCalendar();
            state.screen = "calendar";
            render();
          }),
      },
      ["📅 日曆"],
    ),
    el(
      "button",
      {
        class: "btn",
        // F39：不必先開練，直接瀏覽有資料的動作看表現
        onclick: () =>
          guard(async () => {
            const origin = state.screen;
            await openTrends();
            if (state.screen !== origin) return; // 載入期間離開首頁 → 不劫持導覽
            state.screen = "trends";
            render();
          }),
      },
      ["📈 動作表現"],
    ),
    el(
      "button",
      {
        class: "btn",
        onclick: () =>
          guard(async () => {
            await openBody();
            state.screen = "body";
            render();
          }),
      },
      ["⚖️ 體重"],
    ),
    // F31/F62：休息結束提醒開關（不支援的環境不顯示）。
    // web 走 Web Push、app 走本機通知——同一顆按鈕，實作差異藏在 rest-notify.js
    ...(restNotifySupported()
      ? [
          el(
            "button",
            {
              class: `btn push-toggle${restNotifyEnabled() ? " on" : ""}`,
              onclick: () =>
                guard(async () => {
                  // ③ 的出路：已開但精確鬧鐘被關 → 點擊改成開系統授權頁，
                  // 而不是把提醒關掉（只標示「可能延遲」卻不告訴人去哪開，等於沒有出路）
                  if (restNotifyEnabled() && restNotifyDelayed()) {
                    await requestRestNotifyExact();
                    render();
                    return;
                  }
                  if (restNotifyEnabled()) {
                    await disableRestNotify();
                    render();
                    return;
                  }
                  const res = await enableRestNotify();
                  if (res.ok) render();
                  else showError(res.reason);
                }),
            },
            [
              restNotifyEnabled()
                ? // F62 ③：精確鬧鐘被關時倒數會被系統延後，講出來而不是讓使用者以為壞了
                  restNotifyDelayed()
                  ? "🔔 休息提醒：開（可能延遲，點此修正）"
                  : "🔔 休息提醒：開"
                : "🔔 休息提醒：關",
            ],
          ),
        ]
      : []),
    // F64：浮動計時視窗。只在 app 版出現，且必須先開休息提醒——
    // overlay 是前景服務的第二個顯示面，服務沒跑就沒有秒數可畫
    ...(restOverlaySupported() && restNotifyEnabled()
      ? [
          el(
            "button",
            {
              class: `btn push-toggle${restOverlayEnabled() ? " on" : ""}`,
              onclick: () =>
                guard(async () => {
                  if (restOverlayEnabled()) {
                    await disableRestOverlay();
                    render();
                    return;
                  }
                  const res = await enableRestOverlay();
                  if (res.ok) render();
                  else showError(res.reason);
                }),
            },
            [restOverlayEnabled() ? "🪟 浮動計時：開" : "🪟 浮動計時：關"],
          ),
        ]
      : []),
    versionTag(),
    // F68 ⑦：手動檢查後沒有新版的短暫提示
    ...(updateFlash ? [el("div", { class: "update-flash" }, [updateFlash])] : []),
    // F68 ①④：更新視窗只掛在首頁——其他畫面即使有新版也不會被打斷
    ...(updateModalOpen && pendingUpdate ? [updateModal()] : []),
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
  // F48：課表超過 2 份才固定高度＋內部捲動；「自由訓練」與「← 回首頁」留在捲動區外（它們不是課表，
  // 位置要固定才按得到）。此畫面不會在停留中重繪，故不需存還原 scrollTop。
  const scrollable = templateChoices.length > 2;
  return el("section", { class: "screen template-select fills" }, [
    el("header", { class: "topbar" }, [el("h1", {}, ["今天練哪份？"])]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    // 課表清單與「自由訓練」同一組（間距不變），但只有課表清單會捲動
    el("div", { class: "exercise-list tpl-choice-wrap" }, [
      el(
        "div",
        { class: `exercise-list tpl-choice-list${scrollable ? " scrollable" : ""}` },
        templateChoices.map((template) =>
          el(
            "button",
            { class: "btn exercise-item", onclick: () => guard(() => startWorkout(template)) },
            [
              el("span", {}, [template.name]),
              el("span", { class: "sub" }, [`${template.exercises.length} 動作`]),
            ],
          ),
        ),
      ),
      el(
        "button",
        { class: "btn exercise-item free-choice", onclick: () => guard(() => startWorkout(null)) },
        [
          el("span", {}, ["自由訓練"]),
          el("span", { class: "sub" }, ["不用課表"]),
        ],
      ),
    ]),
    el("button", { class: "btn btn-ghost", onclick: () => { state.screen = "home"; render(); } }, ["← 回首頁"]),
  ]);
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

// 收工／結束訓練：只清 client 狀態回首頁；已記錄的組在 server（SSOT），佇列未同步的之後仍補傳進這個 workout。
// logger 的「收工」與 picker 的「結束訓練」共用（module 級 function 宣告會 hoist，logger 內引用不受順序影響）。
function endWorkout() {
  addPanelOpen = false; // F49：收工一併關窗
  stopRestTimer();
  state.pendingRestSeconds = null;
  editDraft = null;
  clearActiveWorkout();
  state.setCounts = {};
  state.exercise = null;
  state.screen = "home";
  render();
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
  state.setNumber = (state.setCounts[exercise.id] || 0) + 1; // 回頭選同動作時接續編號

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
    }
  } else {
    state.weightKg = exercise.is_bodyweight ? 0 : 20;
    state.reps = 8;
    state.lastHint = null;
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
      ["📈"],
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

function templateMenu() {
  if (!state.template) return [];
  // F48：課表動作超過 2 個才固定高度＋內部捲動，下方「臨時加動作」搜尋/chips/清單不被推出畫面
  const scrollable = state.template.exercises.length > 2;
  const menuNode = el(
    "div",
    { class: `exercise-list menu-list${scrollable ? " scrollable" : ""}` },
    state.template.exercises.map((item) => {
      const done = state.setCounts[item.exercise_id] || 0;
      const exercise = {
        id: item.exercise_id,
        name_zh: item.name_zh,
        name_en: item.name_en,
        muscle_group: item.muscle_group,
        is_bodyweight: item.is_bodyweight,
      };
      const mainBtn = el(
        "button",
        {
          class: `btn exercise-item${done >= item.default_sets ? " menu-done" : ""}`,
          onclick: () => guard(() => pickExercise(exercise)),
        },
        [
          el("span", {}, [exerciseName(item)]),
          el("span", { class: `sub${done > 0 ? " lit" : ""}` }, [
            `${done}/${item.default_sets} 組`,
          ]),
        ],
      );
      // F38：今日菜單列也要有 📈 詳情入口（Codex：原本只有臨時加動作清單有）
      return exerciseRow(mainBtn, exercise, "picker");
    }),
  );
  if (scrollable) {
    requestAnimationFrame(() => { menuNode.scrollTop = menuScrollTop; });
  }
  return [
    el("div", { class: "menu-head" }, [`今日菜單 · ${state.template.name}`]),
    menuNode,
    el("div", { class: "menu-head" }, ["臨時加動作"]),
  ];
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

  return el("section", { class: "screen picker fills" }, [
    el("header", { class: "topbar" }, [
      el("h1", {}, [state.template ? "今日菜單" : "選動作"]),
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
        ]
      : [
          ...exercisePickerParts(),
          el("button", { class: "btn add-custom-ex", onclick: openCustomForm }, ["＋ 自訂動作"]),
        ]),
    el("div", { class: "picker-foot" }, [
      el(
        "button",
        {
          class: "btn btn-ghost",
          // F49：回首頁要一併關窗——訓練沒結束，回來時若還記著 addPanelOpen 就會自己彈出視窗。
          // （進「動作表現」詳情頁的往返刻意不關：那是瀏覽中途離開，回來接續才對）
          onclick: () => { addPanelOpen = false; state.screen = "home"; render(); },
        },
        ["← 回首頁"],
      ),
      // F29：直接從今日菜單結束訓練，不必先進 logger 才收工（與 logger「收工」同一動作）
      el("button", { class: "btn btn-danger", onclick: endWorkout }, ["結束訓練"]),
    ]),
    // F49：臨時加動作視窗（有課表時）
    ...(inModal && addPanelOpen ? [addExerciseModal()] : []),
    // F10：自訂動作懸浮視窗（overlay，蓋在整個選動作畫面上；F49 起也可能疊在臨時加動作視窗上，同 F25）
    ...(customFormOpen ? [pickerCustomModal()] : []),
  ]);
}

// ---------- logger ----------

function startRestTimer() {
  state.restStartedAt = Date.now();
  state.restAccumulatedMs = 0; // F71：新的一輪休息，累計歸零
  state.restResumedAt = state.restStartedAt;
  restAlerted = false;
  // F70：目標秒數當場快照——之後換動作時倒數基準才不會跟著新動作的參考值跳掉
  state.restTargetSeconds = state.exercise
    ? restHintFor(state.exercise.id)
    : DEFAULT_REST_HINT_SECONDS;
  // F31/F62：排定「休息結束」提醒（切到別的 app 也收得到）；未開通知＝no-op
  if (state.exercise) scheduleRestNotify(restHintFor(state.exercise.id));
  if (restTicker) clearInterval(restTicker);
  restTicker = setInterval(() => {
    const led = document.querySelector(".rest-led");
    if (!led) return;
    const remaining = restRemainingSeconds();
    if (remaining === null) return;
    led.querySelector(".digits").textContent = fmtRest(remaining);
    led.classList.toggle("over", remaining <= 0); // 與震動同門檻：到 0 那一刻就變色
    if (!restAlerted && remaining <= 0) {
      restAlerted = true;
      navigator.vibrate?.([200, 100, 200]); // iOS Safari 不支援——只有視覺提示
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
    await resumeRestNotify();
  } else {
    pauseRest();
    await pauseRestNotify();
  }
  render();
}

// F71 ④：停止＝結束這段休息，等同「繼續下一組」——已累計的秒數凍結給下一組（F15 語意不變）。
async function stopRestFromUi() {
  if (state.restStartedAt === null) return;
  state.pendingRestSeconds = restElapsedSeconds();
  stopRestTimer();
  render();
}

function stopRestTimer() {
  if (restTicker) clearInterval(restTicker);
  restTicker = null;
  state.restStartedAt = null;
  state.restAccumulatedMs = 0; // F71
  state.restResumedAt = null;
  state.restTargetSeconds = null; // F70：目標秒數的快照跟著這輪休息一起結束
  // F31/F62：休息被使用者結束（繼續下一組／收工／登出）→ 取消未觸發的提醒。
  // F70 起「換動作」不再走這裡——換個地方看不算休息結束。
  cancelRestNotify();
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
    if (remaining !== null && remaining > 0) scheduleRestNotify(remaining);
    else cancelRestNotify();
  }
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
      state.setCounts[exercise.id] = state.setNumber;
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
          ], (d) => { editDraft.weight = Math.max(0, Math.round((editDraft.weight + d) * 10) / 10); }, render),
          stepper("REPS", editDraft.reps, [
            ["−1", -1],
            ["+1", +1],
          ], (d) => { editDraft.reps = Math.max(1, editDraft.reps + d); }, render),
        ]),
        rpePicker(editDraft.rpe, (v) => { editDraft.rpe = v; }, render),
        el("div", { class: "edit-actions" }, [
          el("button", { class: "btn btn-primary sm save-edit", onclick: () => guard(() => saveEditDoneSet(s)) }, ["儲存"]),
          el("button", { class: "btn btn-ghost sm", onclick: () => { editDraft = null; render(); } }, ["取消"]),
        ]),
      ]);
    }
    const queued = state.queueStatus[s.client_uuid]; // pending | failed | undefined（已同步）
    const mark = queued === "pending" ? " ⏳" : queued === "failed" ? " ⚠" : "";
    return el("div", { class: `done-row${queued ? ` ${queued}` : ""}` }, [
      el("span", {}, [`#${s.set_number}${mark}`]),
      el("span", { class: "n" }, [
        `${s.weight_kg} kg × ${s.reps}${s.rpe ? `  @${s.rpe}` : ""}`,
      ]),
      el("button", {
        class: "btn icon-btn edit-set",
        onclick: () => {
          editDraft = { key, weight: s.weight_kg, reps: s.reps, rpe: s.rpe ?? 6 };
          render();
        },
      }, ["✎"]),
      el("button", {
        // F19：單擊即刪（軟刪／未同步移出佇列，資料非真的消失），不再兩段式確認
        class: "btn icon-btn del-set",
        onclick: () => guard(() => deleteDoneSet(s)),
      }, ["🗑"]),
    ]);
  };

  return el("section", { class: "screen logger" }, [
    el("header", { class: "exercise-head" }, [
      // F42：左上返回箭頭——回動作選擇 picker（等同原『換動作』，不結束訓練、workout 保留）
      el("button", {
        class: "btn btn-ghost logger-back", "aria-label": "回動作選擇",
        onclick: finish,
      }, ["←"]),
      el("div", { class: "exercise-head-name" }, [
        el("h2", {}, [exerciseName(exercise)]),
        el("span", { class: "alias" }, [exerciseAlias(exercise)]),
      ]),
      // F38：練到一半查當前動作歷史；返回不丟進行中訓練
      el("button", {
        class: "btn detail-link logger-detail", "aria-label": "動作表現",
        onclick: () => openDetail(exercise, "logger"),
      }, ["📈"]),
    ]),
    el("div", { class: "last-hint" }, [state.lastHint || "第一次做這個動作"]),
    el("div", { class: "rest-hint-row" }, [
      el(
        "button",
        {
          class: "btn chip rest-hint",
          // 點擊循環 60→90→120→180（課表自訂值也留在循環內）；僅本次訓練，不寫回課表
          onclick: () => {
            cycleRestHint(exercise.id);
            render();
          },
        },
        [`⏱ 休息 ${restHintFor(exercise.id)}s`],
      ),
    ]),
    el(
      "div",
      {
        class: `rest-led${state.restStartedAt ? " on" : ""}${
          (restRemainingSeconds() ?? 1) <= 0 ? " over" : ""
        }`,
      },
      [
        el("span", { class: "label" }, [restPaused() ? "PAUSED" : "REST"]),
        el("span", { class: "digits" }, [
          state.restStartedAt
            ? fmtRest(restRemainingSeconds())
            : fmtClock(restHintFor(exercise.id)),
        ]),
      ],
    ),
    // F71 ①：暫停／繼續與停止。只在休息中出現——沒在休息時這兩顆沒有意義，
    // 而且底部的「✓ 完成這組」本來就是那個狀態下唯一該按的東西
    ...(state.restStartedAt
      ? [
          el("div", { class: "rest-controls" }, [
            el(
              "button",
              { class: "btn btn-ghost", onclick: () => guard(togglePauseRest) },
              [restPaused() ? "▶ 繼續" : "⏸ 暫停"],
            ),
            el(
              "button",
              { class: "btn btn-ghost", onclick: () => guard(stopRestFromUi) },
              ["⏹ 停止"],
            ),
          ]),
        ]
      : []),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    ...syncStatusLine(),
    // F20：新→舊排序（最新在最上）；組數 > 2 時固定高度內部捲動（編輯中不限高，讓編輯表單完整可見）
    el("div", {
      class: `done-list${state.doneSets.length > 2 && !editDraft ? " scrollable" : ""}`,
    }, [...state.doneSets].reverse().map(doneRow)),
    el("div", { class: "steppers" }, [
      stepper(exercise.is_bodyweight ? "負重 KG" : "KG", state.weightKg, [
        ["−2.5", -2.5],
        ["+2.5", +2.5],
      ], (d) => { state.weightKg = Math.max(0, Math.round((state.weightKg + d) * 10) / 10); }, render),
      stepper("REPS", state.reps, [
        ["−1", -1],
        ["+1", +1],
      ], (d) => { state.reps = Math.max(1, state.reps + d); }, render),
    ]),
    rpePicker(state.rpe, (v) => { state.rpe = v; }, render),
    el(
      "button",
      {
        // F15 兩態切換：就緒態（未在休息）＝記錄；休息態＝繼續下一組（停倒數）
        class: `btn btn-primary log-btn${state.restStartedAt ? " resting" : ""}`,
        ...(state.submitting ? { disabled: "" } : {}),
        onclick: () => guard(state.restStartedAt ? continueNext : logSet),
      },
      [state.restStartedAt ? "繼續下一組" : "✓ 完成這組"],
    ),
    // F42：底部『換動作』『收工』已移除——換動作改左上←，結束訓練走 picker 的『結束訓練』
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
    templateSelect: renderTemplateSelect,
    picker: renderPicker,
    trends: renderTrends,
    logger: renderLogger,
    templates: () =>
      renderTemplates(
        render,
        () => {
          state.screen = "home";
          render();
        },
        guard,
      ),
    templateEdit: () => renderTemplateEdit(render, guard),
    calendar: () =>
      renderCalendar(
        render,
        () => {
          state.screen = "home";
          render();
        },
        guard,
      ),
    body: () =>
      renderBody(
        render,
        () => {
          state.screen = "home";
          render();
        },
        guard,
      ),
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
  syncRestCardVisible(state.screen === "logger" && state.restStartedAt !== null);
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
      if (state.screen === "home") render();
    });
  }
});

restoreActiveWorkout();
// F62：app 版的通知權限／精確鬧鐘狀態是非同步查詢，但 render() 是同步的——
// 啟動時先查一次填進 cache，查完重繪讓開關顯示真實狀態（web 版是同步判定，這裡 no-op）。
// ⚠ 這裡只更新「權限狀態」，**不重排通知**：休息倒數（state.restStartedAt）本來就不持久化，
// app 被重啟後倒數與已排定的通知都會消失且畫面無提示。那是 F62 之前就有的行為，不在本 feature 範圍。
refreshRestNotifyState().then(() => {
  if (state.screen === "home") render();
});
// F71 ⑥：原生端（浮動視窗）的暫停／繼續／停止回傳。只訂閱一次，事件驅動不輪詢。
// 前端仍是狀態的事實來源——原生只回報「使用者按了什麼」，實際的計時狀態在這裡改。
subscribeRestControl((action) => {
  if (state.restStartedAt === null) return;
  if (action === "pause" && !restPaused()) pauseRest();
  else if (action === "resume" && restPaused()) resumeRest();
  else if (action === "stop") {
    state.pendingRestSeconds = restElapsedSeconds(); // ④：等同繼續下一組
    stopRestTimer();
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
  guard(loadExercises); // 預載動作庫，token 失效會導回 setup
  guard(syncQueue); // 開站補傳上次離線留下的佇列
}
