// 動作表現頁（F36 起，F86 改版）：三張全期 PR 卡 ＋ 五檔時間窗 ＋ 每次最佳組長條圖 ＋ 歷來紀錄卡。
// 資料源＝GET /api/exercises/{id}/history（F35；F86 起 prs 多了 top_est_1rm 與 top_session_volume）。

import { api } from "./api.js";
import { el } from "./dom.js";
import { icon } from "./icons.js";
import {
  PRESETS,
  iso,
  longestAvailable,
  monthsAgo,
  presetAvailable as presetUsable,
} from "./range.js";
import { exerciseName, state } from "./state.js";

// 本模組畫面狀態（不進全域 state：換畫面即重置無妨）
const detail = {
  exerciseId: null,
  exercise: null, // {id, name_zh, name_en}
  returnScreen: "picker", // 返回目的地（F38 兩入口各自帶入）
  range: { kind: "preset", months: 3 }, // months=null＝「全部」
  rangeNote: null, // F59：點到停用檔位時的一次性說明（初次退檔是靜默的，同 F58 的 openBody）
  data: { prs: {}, sessions: [] },
  bodyweight: 0, // F37：自體重動作噸位用（取最新體重，同日曆的近似）
};

function datesFor(range) {
  const today = new Date();
  // 「全部」：從最早訓練日起。還不知道最早日（第一次開頁）時退到一個夠早的日期，
  // 不用 null——後端的 from 是必填，少一個參數會變成 422。
  if (range.months === null) {
    return { from: detail.data.first_session_date || "2000-01-01", to: iso(today) };
  }
  return { from: iso(monthsAgo(today, range.months)), to: iso(today) };
}

let reqSeq = 0; // 過期回應丟棄：快速連點時只採用最新一次查詢

// 取新 range 的資料，成功才原子提交 range＋data；失敗（拋出）時 range/data 均不動，
// 由 guard 接住並以舊狀態重繪（新檔位不會殘留高亮、圖表不與檔位不一致）
async function loadRange(newRange) {
  const { from, to } = datesFor(newRange);
  const seq = ++reqSeq;
  const data = await api.exerciseHistory(detail.exerciseId, from, to);
  if (seq !== reqSeq) return; // 較舊但較慢的回應——丟棄
  detail.range = newRange;
  detail.data = data;
}

export function detailReturnScreen() {
  return detail.returnScreen;
}

// 入口（F38 的 picker／logger 兩處呼叫）：載入預設 3M 資料
export async function openExerciseDetail(exercise, returnScreen = "picker") {
  detail.exerciseId = exercise.id;
  detail.exercise = exercise;
  detail.returnScreen = returnScreen;
  detail.range = { kind: "preset", months: 3 };
  detail.data = { prs: {}, sessions: [] }; // 清掉上一個動作殘留
  // 自體重動作：取最新體重，噸位才不會把引體向上算成 0（同日曆 set_tonnage 的近似）
  detail.bodyweight = 0;
  if (exercise.is_bodyweight) {
    try {
      const metrics = await api.listBodyMetrics();
      if (metrics.length) {
        detail.bodyweight = metrics.reduce((a, b) => (b.date > a.date ? b : a)).weight_kg;
      }
    } catch {
      /* 拿不到體重就當 0，不擋開頁 */
    }
  }
  detail.rangeNote = null;
  const myId = exercise.id; // review P2-1：載入期間使用者可能又點了別的動作
  await loadRange({ kind: "preset", months: 3 });
  // review P2-1：本函式在 await 後才切畫面，期間可再點另一個動作。若 detail.exerciseId 已被換掉，
  // 這裡的續行就不該再動任何狀態（同 app.js pickExercise 的 `state.exercise !== exercise` 手法）
  if (detail.exerciseId !== myId) return;
  // F59（同 F58 P3-4）：first_session_date 要等第一次查詢回來才知道；若 3M 其實不可用就退檔，
  // 否則畫面會出現「被選中的那顆是灰的」。
  // review P2-2：**不再發第二次請求**——可以證明它必然多餘：presetUsable(3, detail.data.first_session_date) 為 false
  // ⇒ 資料全落在最近一個月內 ⇒ 可用集合恆為 {1M} ⇒ 1M 的資料是剛拿到的 3M 的嚴格子集。
  // 而那次請求若失敗會讓使用者「明明資料在手上卻進不去頁面」。所以就地過濾。
  if (!presetUsable(3, detail.data.first_session_date)) {
    const months = longestAvailable(detail.data.first_session_date);
    // F121：起始日走本模組的 datesFor（同一份規則），**不要自己再算一次 monthsAgo**——
    // F86 ③ 加了「全部」檔位（months === null）之後 longestAvailable 的答案就是它，而
    // `getMonth() - null` 是 `getMonth() - 0`，算出來是**今天**：於是「唯一一次訓練在 10 天前」
    // 的動作退檔後被濾成空清單（退檔本來是為了「別給一張空圖」，結果自己造了一張）。
    // datesFor 早就處理了 null 這個情形——重複的第二份算式才是 bug 的來源。
    const { from } = datesFor({ kind: "preset", months });
    detail.range = { kind: "preset", months };
    detail.data = {
      ...detail.data,
      sessions: detail.data.sessions.filter((x) => x.date >= from),
    };
  }
}

// ---------- F86：每次最佳組 ----------

// 一次訓練的「最佳組」＝重量最大者；同重量取次數多的。
// ⚠ 這是整個畫面的軸心（長條圖的高度、chip 的獎盃、右上角的最大值都問它），
// 所以只能有一個定義。先前 dayBlock 自己用 `Math.max(weight)` 判當日最重，
// 遇到同重量不同次數會同時標兩顆——那不是「最佳組」，是「最重的重量」。
function bestSet(session) {
  return session.sets.reduce((a, b) => {
    if (b.weight_kg !== a.weight_kg) return b.weight_kg > a.weight_kg ? b : a;
    return b.reps > a.reps ? b : a;
  });
}

function sessionTonnage(session) {
  // 自體重動作以（最新體重＋額外負重）計，同日曆 set_tonnage 規則
  const bw = detail.exercise?.is_bodyweight && detail.bodyweight ? detail.bodyweight : 0;
  return session.sets.reduce((a, x) => a + (x.weight_kg + bw) * x.reps, 0);
}

// ---------- render ----------

function fmtNum(v) {
  // 26px 的數字欄位放不下無意義的小數：整數就不補 .0
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

function prCards() {
  const prs = detail.data.prs || {};
  const top = prs.top_weight;
  const cards = [
    // 主卡（--card-hi 底 ＋ --accent 數字）：推估 1RM 是三者中最能一眼看出進步的
    ["推估 1RM", prs.top_est_1rm == null ? "—" : fmtNum(Math.round(prs.top_est_1rm)), "", true],
    ["最重", top ? fmtNum(top.weight_kg) : "—", "", false],
    [
      "單次量",
      prs.top_session_volume == null ? "—" : fmtNum(Math.round(prs.top_session_volume / 100) / 10),
      "t",
      false,
    ],
  ];
  return el(
    "div",
    { class: "pr-cards" },
    cards.map(([label, value, unit, hi]) =>
      el("div", { class: `pr-card${hi ? " hi" : ""}` }, [
        el("div", { class: "pr-k" }, [label]),
        el("div", { class: "pr-v" }, [value, ...(unit ? [el("span", { class: "pr-u" }, [unit])] : [])]),
      ]),
    ),
  );
}

/**
 * 每次最佳組長條圖。
 *
 * 高度＝值／最大值，所以最高那根一定滿格——這是設計稿的規則，代價是「全部都很接近」
 * 時看起來差距被放大。可接受：這張圖要回答的是「有沒有在進步」，不是絕對值比較
 * （絕對值在右上角與 chips 上都有）。
 *
 * PR 那次的判定用**累進**最佳（到那次為止的最高），不是「等於全期最大值」——
 * 後者只會標到最後一次，而設計稿裡的星號是一路上的每一次突破。
 */
function barChart() {
  const sessions = detail.data.sessions;
  if (!sessions.length) {
    return el("div", { class: "bars-card" }, [
      el("p", { class: "bars-empty" }, ["這個區間內沒有紀錄"]),
    ]);
  }
  const points = sessions.map((s) => ({ date: s.date, best: bestSet(s) }));
  const max = Math.max(...points.map((x) => x.best.weight_kg));
  let running = -Infinity;
  for (const point of points) {
    point.isPr = point.best.weight_kg > running;
    if (point.isPr) running = point.best.weight_kg;
  }
  const monthOf = (d) => `${+d.slice(5, 7)}月`;
  return el("div", { class: "bars-card" }, [
    el("div", { class: "bars-head" }, [
      el("span", { class: "bars-title" }, ["每次最佳組"]),
      el("span", { class: "bars-max" }, [`${fmtNum(max)} kg`]),
    ]),
    el(
      "div",
      { class: "bars" },
      points.map((point) =>
        el("div", { class: "bar-col" }, [
          // ⚠ 獎盃那一列**每一欄都要有**（非 PR 的隱藏起來）。只在 PR 欄放的話，
          // 有獎盃的欄可用高度少 12px，最高那根被擠短，長條比例就不再是「值／最大值」
          // ——60/75 會量到 0.88 而不是 0.80。這是實際量出來才發現的。
          el("span", { class: `bar-flag${point.isPr ? " on" : ""}` },
            [icon("trophy", { size: 9, label: point.isPr ? "個人紀錄" : "" })]),
          // 長條放在自己的軌道裡，百分比才是「值／最大值」——直接掛在 bar-col 上的話
          // 100% 會連同獎盃列一起超出欄高，被 flex 壓縮，最高那根反而變矮（比例失真）
          el("div", { class: "bar-track" }, [
            el("div", {
              class: `bar${point.isPr ? " pr" : ""}`,
              // 高度用 style 而非 class：值是連續的，沒辦法用固定幾檔 class 表達
              style: `height:${Math.max(4, (point.best.weight_kg / max) * 100)}%`,
              "aria-label": `${point.date} 最佳組 ${point.best.weight_kg}kg × ${point.best.reps}`,
            }, []),
          ]),
        ]),
      ),
    ),
    el("div", { class: "bars-foot" }, [
      el("span", {}, [monthOf(points[0].date)]),
      el("span", { class: "bars-legend" }, [icon("trophy", { size: 9 }), "個人紀錄"]),
      el("span", {}, [monthOf(points[points.length - 1].date)]),
    ]),
  ]);
}

function relTime(dateStr) {
  const days = Math.round((new Date(iso(new Date())) - new Date(dateStr)) / 864e5);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 30) return `${days} 天前`;
  if (days < 365) return `${Math.round(days / 30)} 個月前`;
  return `${Math.floor(days / 365)} 年前`;
}

// F86 ⑥：一次訓練一張卡。F37 的月份摺疊拿掉——改版後每張卡本來就只有兩行，
// 摺疊層級反而讓「最近練得如何」要多點兩下才看得到。
function sessionCard(session) {
  const best = bestSet(session);
  return el("div", { class: "hist-card" }, [
    el("div", { class: "hist-head" }, [
      el("span", { class: "hist-date" }, [session.date.slice(5).replace("-", "/")]),
      el("span", { class: "hist-rel" }, [relTime(session.date)]),
      el("span", { class: "hist-vol" }, [`${Math.round(sessionTonnage(session)).toLocaleString()} kg`]),
    ]),
    el(
      "div",
      { class: "hist-sets" },
      session.sets.map((x) =>
        el("span", { class: `set-chip${x === best ? " best" : ""}` }, [
          `${fmtNum(x.weight_kg)}×${x.reps}`,
          ...(x.rpe ? [el("span", { class: "rpe" }, [`@${x.rpe}`])] : []),
          ...(x === best ? [icon("trophy", { size: 11, label: "當次最佳組" })] : []),
        ]),
      ),
    ),
  ]);
}

function renderHistory() {
  const sessions = [...detail.data.sessions].reverse(); // 新→舊
  if (!sessions.length) return [el("p", { class: "hist-empty" }, ["這個區間內沒有紀錄"])];
  return sessions.map(sessionCard);
}

export function renderExerciseDetail(rerender, goBack, guard) {
  const presetBtn = ([label, months]) => {
    // F86 ④（承 F59）：超出資料範圍的檔位灰掉但**仍可點**——點了顯示說明。
    // 不能用 disabled／aria-disabled：前者點不到，後者宣告「不可互動」會讓 Playwright 拒絕點擊。
    const available = presetUsable(months, detail.data.first_session_date);
    const on = detail.range.months === months;
    return el("button", {
      class: `range-pill${on ? " on" : ""}${available ? "" : " off"}`,
      ...(available ? {} : { "aria-label": `${label}（超出資料範圍，點擊查看說明）` }),
      onclick: () => {
        if (!available) {
          detail.rangeNote = `這個動作最早的訓練是 ${detail.data.first_session_date}，還沒有更早的資料`;
          rerender();
          return;
        }
        guard(async () => {
          detail.rangeNote = null;
          await loadRange({ kind: "preset", months }); // 成功才提交檔位＋資料
          rerender();
        });
      },
    }, [label]);
  };

  return el("section", { class: "screen exercise-detail" }, [
    // 沿用 F81 起的 .screen-head 慣例（.back-btn／.screen-head-text／.st），
    // 不另立一套類名——版面規則已經在 CSS 那邊定義過一次了
    el("header", { class: "screen-head" }, [
      el("button", {
        class: "btn btn-ghost back-btn", "aria-label": "返回", onclick: goBack,
      }, [icon("back", { size: 20, label: "返回" })]),
      el("div", { class: "screen-head-text" }, [
        el("h1", {}, [exerciseName(detail.exercise)]),
        el("span", { class: "st" }, [
          `${detail.exercise?.name_en ?? ""} · ${detail.data.sessions.length} 次紀錄`,
        ]),
      ]),
    ]),
    ...(state.error ? [el("div", { class: "error-banner" }, [state.error])] : []),
    prCards(),
    el("div", { class: "range-pills" }, PRESETS.map(presetBtn)),
    ...(detail.rangeNote ? [el("p", { class: "range-note" }, [detail.rangeNote])] : []),
    barChart(),
    el("div", { class: "hist-list" }, renderHistory()),
  ]);
}
