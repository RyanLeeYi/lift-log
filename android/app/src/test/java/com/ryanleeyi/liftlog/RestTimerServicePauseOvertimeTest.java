package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import android.content.Intent;

import java.lang.reflect.Field;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

/**
 * F89 ⑧/⑩（F71① 回歸）：超時中暫停→繼續，服務不得把超時秒數當剩餘秒數開新倒數。
 *
 * <p>2026-08-24 真機驗收抓到的 P1：stopTimer() 會清 overtime，ACTION_RESUME 一律
 * startTimer(remainingSeconds)，於是 +6:55 的超時累計變成 6:53 的新倒數，
 * overlay 與 REST 卡片從此各數各的。這裡釘住兩個方向：
 * 超時中 resume 要留在超時（不開新 CountDownTimer）；未超時 resume 照舊接續倒數。
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 36)
public class RestTimerServicePauseOvertimeTest {

    private static void set(RestTimerService svc, String name, Object value) throws Exception {
        Field f = RestTimerService.class.getDeclaredField(name);
        f.setAccessible(true);
        f.set(svc, value);
    }

    private static Object get(RestTimerService svc, String name) throws Exception {
        Field f = RestTimerService.class.getDeclaredField(name);
        f.setAccessible(true);
        return f.get(svc);
    }

    private RestTimerService service() {
        return Robolectric.buildService(RestTimerService.class).create().get();
    }

    @Test
    public void resumeDuringOvertimeStaysOvertime() throws Exception {
        RestTimerService svc = service();
        set(svc, "overtime", true);
        set(svc, "remainingSeconds", 415); // +6:55 的超時累計

        svc.onStartCommand(new Intent(RestTimerService.ACTION_PAUSE), 0, 0);
        assertTrue("暫停不得忘記自己在超時", (Boolean) get(svc, "overtime"));

        svc.onStartCommand(new Intent(RestTimerService.ACTION_RESUME), 0, 0);
        assertTrue("繼續後仍是超時狀態", (Boolean) get(svc, "overtime"));
        assertNull("不得把超時秒數當剩餘秒數開新倒數", get(svc, "timer"));
    }

    @Test
    public void resumeWithinTargetStartsCountdown() throws Exception {
        RestTimerService svc = service();
        set(svc, "remainingSeconds", 30);

        svc.onStartCommand(new Intent(RestTimerService.ACTION_PAUSE), 0, 0);
        assertFalse((Boolean) get(svc, "overtime"));

        svc.onStartCommand(new Intent(RestTimerService.ACTION_RESUME), 0, 0);
        assertFalse((Boolean) get(svc, "overtime"));
        assertNotNull("未超時的繼續照舊接續倒數", get(svc, "timer"));
    }
}
