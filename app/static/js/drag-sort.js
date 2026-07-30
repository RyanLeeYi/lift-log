// F97：垂直清單的拖曳排序。目前只有編輯課表在用，但這裡不知道課表這回事——
// 它只認「一個容器、一批子元素」，順序怎麼存由呼叫端的 onReorder 決定。
//
// 為什麼是 Pointer Events 而不是 HTML5 drag-and-drop：後者在行動版瀏覽器與 WebView 裡
// 根本不觸發（桌面 API），而這個畫面主要在手機上用。
//
// 三個難點各自的解法：
//   1. **搶手勢**（②）：`.tpl-items` 超過 2 個動作就是可捲容器，按下去可能是「捲清單」也可能是
//      「拖卡片」。用 300ms 長按當閘門——手指在門檻前移動超過 SLOP 就判定是捲動，取消長按。
//   2. **座標**（④）：一律用「內容座標」= clientY - 容器上緣 + scrollTop。邊緣自動捲動時
//      scrollTop 會變，用視窗座標算會整批錯位。
//   3. **中斷**（⑥）：任何離開拖曳的路徑都走同一個 cleanup，且 cleanup 可重複呼叫。
//      半拖曳的卡片留在畫面上比「拖不動」更糟——它會讓人以為 app 壞了。

const LONG_PRESS_MS = 300;
const SLOP_PX = 8; // 長按門檻前允許的手指晃動；超過就當作是在捲清單
const EDGE_PX = 48; // 距離清單上下緣多近開始自動捲動
const EDGE_SPEED = 10; // 每一幀捲多少 px

let session = null; // 同時只允許一個拖曳（多指同時拖沒有合理語意）

/** 取消進行中的拖曳並復原版面。重複呼叫安全；沒有拖曳時是 no-op。 */
export function cancelDragSort() {
  if (session) cleanup(session);
}

/**
 * 讓容器內的子元素可以拖曳排序。
 *
 * @param {HTMLElement} list 捲動容器（也是拖曳範圍）
 * @param {object} options
 * @param {string} options.itemSelector 可拖曳的子元素選擇器
 * @param {(from: number, to: number) => void} options.onReorder 放開且順序真的變了才呼叫
 * @param {string} [options.ignoreSelector] 這些元素上按下去不觸發拖曳（按鈕、輸入框）
 */
export function attachDragSort(list, {
  itemSelector,
  onReorder,
  ignoreSelector = "button, input, select, textarea, a",
}) {
  list.addEventListener("pointerdown", (e) => {
    if (e.button !== undefined && e.button !== 0) return; // 只認主鍵／單指
    if (session) return;
    const target = e.target instanceof Element ? e.target : null;
    if (!target) return;
    // ⑦：刪除鈕與組數加減鈕還在卡片上，按它們不能變成拖曳
    if (target.closest(ignoreSelector)) return;
    const card = target.closest(itemSelector);
    if (!card || !list.contains(card)) return;

    const pending = {
      list,
      card,
      itemSelector,
      onReorder,
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      lastClientY: e.clientY,
      dragging: false,
      timer: null,
      raf: null,
      metrics: null,
      fromIndex: -1,
      toIndex: -1,
    };
    session = pending;
    pending.timer = setTimeout(() => begin(pending), LONG_PRESS_MS);

    const onMove = (ev) => {
      if (ev.pointerId !== pending.pointerId) return;
      pending.lastClientY = ev.clientY;
      if (!pending.dragging) {
        // ② 門檻前的移動 = 使用者在捲清單，不是要拖卡片
        if (Math.abs(ev.clientY - pending.startY) > SLOP_PX
            || Math.abs(ev.clientX - pending.startX) > SLOP_PX) {
          cleanup(pending);
        }
        return;
      }
      ev.preventDefault(); // 進入拖曳後不要讓瀏覽器同時捲清單
      moveTo(pending, ev.clientY);
    };
    const onUp = (ev) => {
      if (ev.pointerId !== pending.pointerId) return;
      finish(pending);
    };
    const onCancel = (ev) => {
      if (ev && ev.pointerId !== undefined && ev.pointerId !== pending.pointerId) return;
      cleanup(pending); // ⑥ 中斷＝不變更順序
    };
    pending.detach = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("blur", onCancel);
      document.removeEventListener("visibilitychange", onHidden);
    };
    const onHidden = () => {
      if (document.visibilityState === "hidden") cleanup(pending);
    };
    window.addEventListener("pointermove", onMove, { passive: false });
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("blur", onCancel);
    document.addEventListener("visibilitychange", onHidden);
  });
}

/** 長按門檻到了：量測版面、進入拖曳態。 */
function begin(s) {
  s.timer = null;
  if (!s.list.isConnected || !s.card.isConnected) {
    cleanup(s);
    return;
  }
  const cards = [...s.list.querySelectorAll(s.itemSelector)];
  const listRect = s.list.getBoundingClientRect();
  const scroll = s.list.scrollTop;
  // 內容座標：加回 scrollTop，之後邊緣自動捲動才不會讓整批量測失效
  const tops = cards.map((c) => c.getBoundingClientRect().top - listRect.top + scroll);
  const heights = cards.map((c) => c.getBoundingClientRect().height);
  const gap = cards.length > 1 ? Math.max(0, tops[1] - (tops[0] + heights[0])) : 0;

  s.metrics = { cards, tops, heights, gap };
  s.fromIndex = cards.indexOf(s.card);
  s.toIndex = s.fromIndex;
  s.startContentY = s.startY - listRect.top + scroll;
  s.dragging = true;

  try {
    s.card.setPointerCapture(s.pointerId);
  } catch {
    /* 有些環境（含部分測試工具）不支援 capture：拖曳照走，只是手指移出元素時靠 window 監聽接住 */
  }
  // ③ 正在拖的那張站出來——這就是 F96 拿掉的高亮回來的方式，它現在對應一個真實狀態
  s.card.classList.add("dragging");
  s.list.classList.add("drag-active");
  moveTo(s, s.lastClientY);
}

/** 手指移到 clientY：更新被拖卡片的位移、其餘卡片讓位、必要時邊緣自動捲動。 */
function moveTo(s, clientY) {
  s.lastClientY = clientY;
  const { cards, tops, heights, gap } = s.metrics;
  const listRect = s.list.getBoundingClientRect();
  const contentY = clientY - listRect.top + s.list.scrollTop;
  const dy = contentY - s.startContentY;
  s.card.style.transform = `translateY(${dy}px)`;

  // 目標位置：被拖卡片的中心跨過誰的中心，就排到誰的前／後
  const draggedCenter = tops[s.fromIndex] + heights[s.fromIndex] / 2 + dy;
  let target = 0;
  for (let j = 0; j < cards.length; j += 1) {
    if (j === s.fromIndex) continue;
    if (tops[j] + heights[j] / 2 < draggedCenter) target += 1;
  }
  s.toIndex = target;

  // ③ 其餘卡片讓位：位移一整張被拖卡片的高度（含間距）
  const shift = heights[s.fromIndex] + gap;
  cards.forEach((c, j) => {
    if (j === s.fromIndex) return;
    let offset = 0;
    if (s.fromIndex < j && j <= target) offset = -shift;
    else if (target <= j && j < s.fromIndex) offset = shift;
    c.style.transform = offset ? `translateY(${offset}px)` : "";
  });

  scheduleEdgeScroll(s, listRect);
}

/** ④ 拖到上下邊緣時自動捲動，否則長清單根本拖不到目的地。 */
function scheduleEdgeScroll(s, listRect) {
  const dir = edgeDirection(s, listRect);
  if (dir === 0) {
    if (s.raf !== null) {
      cancelAnimationFrame(s.raf);
      s.raf = null;
    }
    return;
  }
  if (s.raf !== null) return; // 已經在捲了
  const step = () => {
    s.raf = null;
    if (!s.dragging) return;
    // 排這一幀到它真的跑，手指可能已經離開邊緣了——執行當下重判一次，
    // 否則會多捲一格（回到中央仍在捲＝手感失控，也是這條的反面測試在守的東西）
    if (edgeDirection(s, s.list.getBoundingClientRect()) !== dir) return;
    const before = s.list.scrollTop;
    s.list.scrollTop = before + dir * EDGE_SPEED;
    if (s.list.scrollTop === before) return; // 捲到底了，不用再排下一幀
    moveTo(s, s.lastClientY); // 捲動改變了內容座標，位移與讓位要跟著重算（並排下一幀）
  };
  s.raf = requestAnimationFrame(step);
}

/** 手指目前在哪個邊緣：-1 往上捲、1 往下捲、0 不捲（不可捲的清單一律 0）。 */
function edgeDirection(s, listRect) {
  if (s.list.scrollHeight <= s.list.clientHeight + 1) return 0;
  if (s.lastClientY - listRect.top < EDGE_PX) return -1;
  if (listRect.bottom - s.lastClientY < EDGE_PX) return 1;
  return 0;
}

/** 放開：順序真的變了才回報（⑤），沒變＝取消（⑥）。 */
function finish(s) {
  const { dragging, fromIndex, toIndex, onReorder } = s;
  cleanup(s);
  if (!dragging || fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return;
  onReorder(fromIndex, toIndex);
}

/** ⑥ 唯一的收尾路徑：復原所有位移與 class，解除監聽。重複呼叫安全。 */
function cleanup(s) {
  if (s.timer !== null) {
    clearTimeout(s.timer);
    s.timer = null;
  }
  if (s.raf !== null) {
    cancelAnimationFrame(s.raf);
    s.raf = null;
  }
  if (s.metrics) {
    s.metrics.cards.forEach((c) => { c.style.transform = ""; });
  }
  s.card.classList.remove("dragging");
  s.list.classList.remove("drag-active");
  try {
    if (s.card.hasPointerCapture?.(s.pointerId)) s.card.releasePointerCapture(s.pointerId);
  } catch {
    /* 已經被瀏覽器自動釋放 */
  }
  s.dragging = false;
  s.detach?.();
  if (session === s) session = null;
}
