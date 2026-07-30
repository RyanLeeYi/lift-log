// F87 ⑨：時間窗檔位的共用規則。
//
// 這套規則先前在 body.js（F58 寫的）與 exercise-detail.js（F59 逐字複製過去）各有一份，
// 兩邊的註解都寫著「改一邊要改另一邊」——那句話本身就是缺陷報告。F86 把動作表現頁的
// 檔位收成五顆之後兩邊終於一致，這裡收成一份。
//
// ⚠ PRESETS 必須由短到長遞增：longestAvailable() 取 filter 後的最後一個當「最長可用」。
// months === null 代表「全部」（從最早紀錄日起算）。

export const PRESETS = [
  ["1M", 1], ["3M", 3], ["6M", 6], ["1Y", 12], ["全部", null],
];

/** 本地日期 YYYY-MM-DD。刻意不用 toISOString——那是 UTC，台灣早上八點前會算成昨天。 */
export function iso(d) {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function todayIso() {
  return iso(new Date());
}

/** n 個**日曆月**前；月底日期會 clamp（7/31 減 3 個月＝4/30）。 */
export function monthsAgo(d, months) {
  const y = d.getFullYear();
  const m = d.getMonth() - months;
  const lastDay = new Date(y, m + 1, 0).getDate();
  return new Date(y, m, Math.min(d.getDate(), lastDay));
}

/**
 * 檔位起始日。`firstDate` 是該資料集的最早紀錄日（「全部」要用它當起點）。
 */
export function startOfPreset(months, firstDate) {
  if (months === null) return firstDate || "2000-01-01";
  return iso(monthsAgo(new Date(), months));
}

/**
 * 這個檔位有意義嗎？
 *
 * 規則＝「起始日落在資料範圍內」的檔位 ＋ **第一個完整涵蓋所有資料的檔位**。
 * 後面那個例外是必要的：只留「起始日 ≥ 最早紀錄」的話，資料 100 天時最大只能選 3M（90 天），
 * 最舊的 10 天用任何檔位都看不到——那不是「限制住」而是「藏起來」。
 * 完全沒有紀錄時不限制（否則變成全部灰掉的死狀態）。
 */
export function presetAvailable(months, firstDate) {
  if (months === null) return true; // 「全部」的定義就是資料的全長
  if (!firstDate) return true;
  const startOf = (m) => iso(monthsAgo(new Date(), m));
  if (startOf(months) >= firstDate) return true;
  const covering = PRESETS.map(([, m]) => m).filter((m) => m !== null && startOf(m) < firstDate);
  return covering.length > 0 && months === covering[0];
}

/** 切換資料集後若當前檔位不可用，退到「最長的可用檔位」。 */
export function longestAvailable(firstDate) {
  const usable = PRESETS.filter(([, m]) => presetAvailable(m, firstDate));
  return usable.length ? usable[usable.length - 1][1] : PRESETS[0][1];
}
