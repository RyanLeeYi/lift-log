package com.ryanleeyi.liftlog;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import android.provider.Settings;
import android.view.View;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

/**
 * F89 ⑨：原生層的 reduced-motion。
 *
 * <p>這條在 2026-07-31 的真機驗收只驗到「animator_duration_scale=0 時不崩」——
 * 沒有任何東西能證明「有動效」與「取消動效」是兩種不同的結果，而靜態截圖本來就看不出來。
 * 所以兩個方向各一條：關掉時直接就位，開著時**確實**從 0.92／alpha 0 起跑。
 * 只驗前者的話，「動效整條被拿掉」的實作也全綠。
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 36)
public class RestOverlayMotionTest {

    private Context context;

    @Before
    public void setUp() {
        context = RuntimeEnvironment.getApplication();
    }

    private void setAnimatorScale(float scale) {
        Settings.Global.putFloat(
            context.getContentResolver(), Settings.Global.ANIMATOR_DURATION_SCALE, scale);
    }

    /** 系統把動畫比例關掉＝使用者要求減少動態。 */
    @Test
    public void reduceMotionFollowsAnimatorDurationScale() {
        setAnimatorScale(0f);
        assertTrue(RestOverlay.reduceMotion(context));

        setAnimatorScale(1f);
        assertFalse(RestOverlay.reduceMotion(context));
    }

    /** 查不到就當作要動效——判不出來時給正常體驗，不要反過來把所有人的動效都關掉。 */
    @Test
    public void reduceMotionDefaultsToAnimating() {
        assertFalse(RestOverlay.reduceMotion(context));
    }

    /** reduced-motion：直接就位，不做過場（沒有中間的透明／縮小狀態）。 */
    @Test
    public void animateInLandsImmediatelyWhenMotionReduced() {
        setAnimatorScale(0f);
        View target = new View(context);
        target.setAlpha(0f);
        target.setScaleX(0f);
        target.setScaleY(0f);

        RestOverlay.animateIn(context, target);

        assertEquals(1f, target.getAlpha(), 0f);
        assertEquals(1f, target.getScaleX(), 0f);
        assertEquals(1f, target.getScaleY(), 0f);
    }

    /** 反面：動效開著時**確實**從 alpha 0 / 0.92 起跑，不是靜靜地就位。 */
    @Test
    public void animateInStartsFromTransitionStateWhenMotionAllowed() {
        setAnimatorScale(1f);
        View target = new View(context);

        RestOverlay.animateIn(context, target);

        assertEquals(0f, target.getAlpha(), 0f);
        assertEquals(.92f, target.getScaleX(), 1e-6f);
        assertEquals(.92f, target.getScaleY(), 1e-6f);
    }

    /** null 進來不得炸——服務回收時 view 參照已清掉，這條路真的會走到。 */
    @Test
    public void animateInIgnoresNullTarget() {
        setAnimatorScale(1f);
        RestOverlay.animateIn(context, null);
    }
}
