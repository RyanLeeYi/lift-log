package com.ryanleeyi.liftlog;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;

/**
 * F124 ②③：Activity 完全不存在時的原生→前端事件暫存區。
 *
 * <p>Capacitor 的 {@code notifyListeners(..., retainUntilConsumed=true)} 已經能處理
 * 「plugin 在、但 JS 還沒訂閱」（① 用的就是它），但它把事件存在 plugin **instance** 上——
 * Activity 被回收後 instance 是 null，那層無處可存。這裡補的就是那一段：
 * 事件先進 static FIFO，等 {@link RestTimerPlugin#load()} 把它們重放回 Capacitor 的
 * retain 佇列。
 *
 * <p>刻意只存基本型別、不存 JSObject：這樣它能用純 JUnit 驗（⑥），不必拖 Robolectric。
 */
final class PendingRestControl {

    /** 上限：滿了丟最舊的。休息控制事件本來就只有個位數量級，32 是「絕不可能是正常狀況」的線。 */
    static final int MAX = 32;

    /** ③ 過期線：冷啟動不該把幾小時前按的 focus／stop 重播出來（focus 會無預警導頁）。 */
    static final long TTL_MS = 5 * 60 * 1000L;

    static final class Event {
        final String action;
        final int seconds;
        final long startedAt;
        final long emittedAt;

        Event(String action, int seconds, long startedAt, long emittedAt) {
            this.action = action;
            this.seconds = seconds;
            this.startedAt = startedAt;
            this.emittedAt = emittedAt;
        }
    }

    private static final Deque<Event> QUEUE = new ArrayDeque<>();

    private PendingRestControl() {}

    static synchronized void offer(String action, int seconds, long startedAt, long emittedAt) {
        QUEUE.addLast(new Event(action, seconds, startedAt, emittedAt));
        while (QUEUE.size() > MAX) QUEUE.removeFirst();
    }

    /** 取出並清空。順序即送出順序——F123 的 focus→stop 反過來會靜默失效。 */
    static synchronized List<Event> drain(long now) {
        List<Event> out = new ArrayList<>();
        for (Event event : QUEUE) {
            if (now - event.emittedAt <= TTL_MS) out.add(event);
        }
        QUEUE.clear();
        return out;
    }

    /** 只給測試用：static 佇列跨測試會殘留。 */
    static synchronized void reset() {
        QUEUE.clear();
    }
}
