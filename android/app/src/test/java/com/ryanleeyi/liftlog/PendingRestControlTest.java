package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;

import org.junit.Before;
import org.junit.Test;

import java.util.List;

/** F124 ⑥：Activity 不在時的事件暫存區。 */
public class PendingRestControlTest {

    private static final long NOW = 1_700_000_000_000L;

    @Before
    public void setUp() {
        PendingRestControl.reset();
    }

    /** ② 順序即送出順序——F123 的 focus→stop 反過來會靜默失效。 */
    @Test
    public void drainsInEmissionOrder() {
        PendingRestControl.offer("focus", -1, -1L, NOW);
        PendingRestControl.offer("stop", -1, -1L, NOW);
        PendingRestControl.offer("nextround", 90, NOW, NOW);

        List<PendingRestControl.Event> events = PendingRestControl.drain(NOW);

        assertEquals(3, events.size());
        assertEquals("focus", events.get(0).action);
        assertEquals("stop", events.get(1).action);
        assertEquals("nextround", events.get(2).action);
        assertEquals(90, events.get(2).seconds);
        assertEquals(NOW, events.get(2).startedAt);
    }

    /** drain 是取出並清空：重放過的事件不會在下一次 load() 再送一次。 */
    @Test
    public void drainClearsQueue() {
        PendingRestControl.offer("stop", -1, -1L, NOW);
        assertEquals(1, PendingRestControl.drain(NOW).size());
        assertEquals(0, PendingRestControl.drain(NOW).size());
    }

    /** ③ 超過 5 分鐘的丟掉——冷啟動不該重播幾小時前按的 focus。 */
    @Test
    public void dropsExpiredEvents() {
        PendingRestControl.offer("focus", -1, -1L, NOW - PendingRestControl.TTL_MS - 1);
        PendingRestControl.offer("stop", -1, -1L, NOW - PendingRestControl.TTL_MS);

        List<PendingRestControl.Event> events = PendingRestControl.drain(NOW);

        assertEquals(1, events.size());
        assertEquals("stop", events.get(0).action);
    }

    /** ② 上限滿了丟最舊的，不是丟最新的——最新的才是使用者剛按下的那一顆。 */
    @Test
    public void capsQueueAndDropsOldest() {
        for (int i = 0; i < PendingRestControl.MAX + 3; i++) {
            PendingRestControl.offer("plus15", i, -1L, NOW);
        }

        List<PendingRestControl.Event> events = PendingRestControl.drain(NOW);

        assertEquals(PendingRestControl.MAX, events.size());
        assertEquals(3, events.get(0).seconds);
        assertEquals(PendingRestControl.MAX + 2, events.get(events.size() - 1).seconds);
    }
}
