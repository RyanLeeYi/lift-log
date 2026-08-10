"""F103 E2E：浮動視窗停止後的「再開始」、回 app 時視窗消失、±15s 兩邊同步。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f103.py`

F103 的 ③④ 主體在原生 Java（那顆「再開始」鈕的長相與可見性），Playwright 碰不到，
一律真機驗。**這支只驗前端那一半**——也就是 ⑤ 點名的實作風險所在：

  ② 回計時頁面時的可見性判斷（改成「人在計時頁面」，不是「REST 卡片可見」）
  ⑤ 收到 restart 要從原生給的秒數把自己那份倒數對上來，而且**不得回送原生指令**
  ⑥ plus15／minus15 以前根本沒接，回到 app 卡片與通知列對不上

⚠ 「不得回送原生指令」要有反面斷言。少了它，「收到 restart 就照常走開始休息流程」也會全綠
——那條路會再叫一次原生服務，同一輪被啟動兩次、秒數互相覆蓋
（與 F100 第一版 halt→stop 互相抵銷是同一族的 bug，那次是真機才發現的）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    reroute_public_host,
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
    wait_home,
)

NOTIFY_FLAG = "liftlog.nativeNotifyEnabled"
OVERLAY_FLAG = "liftlog.restOverlayEnabled"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


FAKE = """
window.__native = { starts: 0, stops: 0, halts: 0, restarts: 0, visible: [], handler: null };
window.__emit = (action, seconds) => {
  const h = window.__native.handler;
  if (!h) return false;
  h(seconds === undefined ? { action } : { action, seconds });
  return true;
};
const local = {
  exercises: [{ id: 1, name_zh: '深蹲', name_en: 'Squat', muscle_group: '腿', is_bodyweight: 0 }],
  templates: [], workouts: [], sets: [], body_metrics: [], daily_status: [], settings: [],
};
let nextWorkout = 1;
let nextSet = 1;
window.Capacitor = {
  isNativePlatform: () => true,
  getPlatform: () => 'android',
  Plugins: {
    LocalStore: {
      initialize: async () => ({ schemaVersion: 2, seededExercises: 1, pendingMutations: 0 }),
      snapshot: async () => structuredClone(local),
      createWorkout: async (o) => {
        const row = { id: nextWorkout++, date: o.date, template_id: o.templateId ?? null,
          note: o.note ?? null, created_at: new Date().toISOString(), ended_at: null };
        local.workouts.push(row);
        return structuredClone(row);
      },
      addSet: async (o) => {
        const row = { id: nextSet, client_uuid: o.clientUuid, workout_id: o.workoutId,
          exercise_id: o.exerciseId, set_number: o.setNumber ?? nextSet++,
          weight_kg: o.weightKg, reps: o.reps, rpe: o.rpe ?? null,
          rest_seconds: o.restSeconds ?? null };
        local.sets.push(row);
        return structuredClone(row);
      },
      status: async () => ({ schemaVersion: 2, pendingMutations: 0 }),
    },
    LocalNotifications: {
      schedule: async () => ({}),
      cancel: async () => ({}),
      checkPermissions: async () => ({ display: 'granted' }),
      requestPermissions: async () => ({ display: 'granted' }),
      areEnabled: async () => ({ value: true }),
      listChannels: async () => ({ channels: [
        { id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 },
      ] }),
    },
    RestTimer: {
      available: async () => ({ available: true }),
      start: async () => { window.__native.starts += 1; return {}; },
      stop: async () => { window.__native.stops += 1; return {}; },
      pause: async () => ({}),
      resume: async () => ({}),
      overlayPermitted: async () => ({ granted: true }),
      requestOverlayPermission: async () => {},
      setRestCardVisible: async (opts) => {
        window.__native.visible.push(Boolean(opts && opts.visible));
        return {};
      },
      addListener: async (name, cb) => {
        if (name === 'restControl') window.__native.handler = cb;
        return { remove: () => {} };
      },
    },
    NotifyStatus: { openSettings: async () => {} },
  },
};
"""


def open_app(browser, base: str):
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    page.add_init_script(FAKE)
    reroute_public_host(page, base)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input, .home-head", timeout=10_000)
    setup_and_home(page)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    page.evaluate(f"() => localStorage.setItem('{OVERLAY_FLAG}', '1')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return ctx, page


def into_rest(page) -> None:
    """開一次訓練、記一組——記完就進休息態，這輪休息由前端發起（與真機一致）。"""
    wait_home(page)
    start_from_home(page)
    page.wait_for_timeout(1200)
    page.locator(".exercise-item").first.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(400)
    page.locator(".log-btn").first.click()
    page.wait_for_selector(".rest-card", timeout=8000)
    page.wait_for_timeout(600)


def emit(page, action: str, seconds=None) -> None:
    if seconds is None:
        page.evaluate(f"() => window.__emit({action!r})")
    else:
        page.evaluate(f"() => window.__emit({action!r}, {seconds})")
    page.wait_for_timeout(700)


def remaining(page) -> int | None:
    """卡片上顯示的剩餘秒數（讀渲染結果，不讀內部狀態）。"""
    digits = page.locator(".rest-ring-text .digits")
    if not digits.count():
        return None
    text = digits.first.inner_text().strip()  # m:ss
    parts = text.replace("-", "").split(":")
    if len(parts) != 2:
        return None
    return int(parts[0]) * 60 + int(parts[1])


def native(page) -> dict:
    return page.evaluate("() => window.__native")


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f103-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    try:
        run_checks(base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    if passed != len(results):
        print("\nFAILED:")
        for ok, label in results:
            if not ok:
                print(f"  - {label}")
    return 0 if passed == len(results) else 1


def run_checks(base: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ── ⑥ ±15s 兩邊同步 ─────────────────────────────────────
        ctx, page = open_app(browser, base)
        into_rest(page)
        before = remaining(page)
        check(before is not None, f"前提：記一組之後進入休息態（剩 {before}）")
        emit(page, "plus15", 999)  # 原生說「調完剩 999 秒」——刻意用一個不可能自己走到的值
        after = remaining(page)
        check(
            after is not None and abs(after - 999) <= 1,
            f"⑥ plus15 帶秒數 → 卡片的倒數對到原生給的值（{before} → {after}，期望 ~999）",
        )
        emit(page, "minus15", 30)
        check(
            (remaining(page) or 0) <= 31,
            f"⑥ minus15 同樣對得上（實際剩 {remaining(page)}）",
        )
        # 反面：沒帶秒數就不要亂動（舊版 APK 的事件）
        held = remaining(page)
        emit(page, "plus15")
        check(
            abs((remaining(page) or 0) - (held or 0)) <= 1,
            "⑥ 反面：沒帶秒數的舊事件不得憑空改動倒數",
        )
        ctx.close()

        # ── ⑤ halt → restart 的整條路 ───────────────────────────
        ctx, page = open_app(browser, base)
        into_rest(page)
        starts_before = native(page)["starts"]
        stops_before = native(page)["stops"]

        emit(page, "halt", 90)
        check(
            page.locator(".rest-card").count() == 0,
            "F100 不回歸：收到 halt 之後前端這份倒數收掉（卡片消失）",
        )
        check(
            native(page)["stops"] == stops_before,
            "⑦ F100 不回歸：halt **不得**回送原生停止指令（那會把視窗一起關掉）",
        )

        emit(page, "restart", 45)
        check(
            page.locator(".rest-card").count() == 1,
            "③⑤ 收到 restart → app 內的 REST 卡片回來了",
        )
        back = remaining(page)
        check(
            back is not None and abs(back - 45) <= 2,
            f"③⑤ 從原生給的秒數重新倒數（實際剩 {back}，期望 ~45）",
        )
        check(
            native(page)["starts"] == starts_before,
            f"⑤ 反面：restart **不得**回送原生開始指令"
            f"（原生 start 次數 {starts_before} → {native(page)['starts']}）——"
            f"回送會讓同一輪被啟動兩次、秒數互相覆蓋",
        )
        ctx.close()

        # ── ⑤ 反面：不帶秒數的 restart 不動作 ────────────────────
        ctx, page = open_app(browser, base)
        into_rest(page)
        emit(page, "halt", 90)
        emit(page, "restart")
        check(
            page.locator(".rest-card").count() == 0,
            "⑤ 反面：restart 沒帶秒數就不動作——寧可不動，也不要憑空猜一個起點",
        )
        ctx.close()

        # ── ② 可見性判斷改成「人在計時頁面」 ─────────────────────
        ctx, page = open_app(browser, base)
        into_rest(page)
        check(
            native(page)["visible"][-1] is True,
            f"② 人在計時頁面 → 回報可見（實際 {native(page)['visible'][-1]}）",
        )
        # 關鍵情境：停止之後前端那份倒數收掉了，但人還在計時頁面
        emit(page, "halt", 90)
        check(
            page.locator(".rest-card").count() == 0,
            "② 前提：停止之後畫面上確實沒有 REST 卡片了",
        )
        check(
            native(page)["visible"][-1] is True,
            f"② **停止之後仍回報可見**——舊規則（卡片可見才藏）在這裡不成立，"
            f"視窗就賴在 app 上面（實際 {native(page)['visible'][-1]}）",
        )
        # 反面：離開計時頁面就要回報不可見，否則 F69 整條沒了
        page.locator(".logger-back").first.click()
        page.wait_for_timeout(700)
        page.get_by_role("button", name="回首頁").first.click()
        page.wait_for_timeout(900)
        check(
            native(page)["visible"][-1] is False,
            f"② 反面：離開計時頁面回報不可見（F69 不回歸；實際 {native(page)['visible'][-1]}）",
        )
        ctx.close()

        # ── ② 回歸：第二輪休息開始時要**重新宣告**可見性 ──────────
        # 2026-07-31 Ryan 真機回報：人沒離開計時頁，第二組休息一開始視窗就冒出來。
        # 成因是兩層各記一份而且都以為對方會記得——原生在每輪結束的 hide() 裡把
        # restCardVisible 清成 false，前端因為值沒變（人一直在 logger）被去重擋下不再送。
        # F103 之前的條件含 restStartedAt，每輪 true↔false 來回跳，才碰巧把它蓋回來。
        ctx, page = open_app(browser, base)
        into_rest(page)
        trues = sum(1 for v in native(page)["visible"] if v)
        check(trues >= 1, f"前提：第一輪已宣告過可見（{trues} 次）")
        # 繼續下一組 → 再記一組 ＝ 開第二輪休息
        page.get_by_role("button", name="繼續下一組").first.click()
        page.wait_for_timeout(700)
        page.locator(".log-btn").first.click()
        page.wait_for_selector(".rest-card", timeout=8000)
        page.wait_for_timeout(900)
        after = sum(1 for v in native(page)["visible"] if v)
        check(
            after > trues,
            f"② 回歸：第二輪休息開始時強制重送可見性（{trues} → {after} 次）——"
            f"少了這一次就要倚賴原生記得上一輪的值，而它在每輪結束時清掉了",
        )
        ctx.close()

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
