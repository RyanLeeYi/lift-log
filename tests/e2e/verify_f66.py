"""F66 E2E：休息倒數持久化——app 被回收後倒數與提醒不消失（①–⑥）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f66.py`

**回收怎麼模擬**：沿用 F90 的做法（清 sessionStorage 後 reload）。時間相關的情境
則直接改寫 localStorage 裡的 `rest.startedAt`——那比真的等 30 秒可靠，也才測得到
「12 小時前開始的休息」這種等不起的門檻。

⚠ 量測一律問渲染結果（圓環上的數字、狀態文字、通知外掛真的收到什麼），
不問實作手段。handoff 記過四次「測試綠但東西是壞的」，型態都是問了 class 名稱。

⚠ 每個限定詞都要有一條斷言。④ 的「12 小時」、⑤ 的「回收期間不計入」、③ 的
「已超時則不排」都是條文裡的限定詞，各自有獨立的一條——F91 的教訓是
「E2E 全綠只證明我做的事我測了」。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import (  # noqa: E402
    PHONE,
    reroute_public_host,
    safe_port,
    setup_and_home,
    start_from_home,
    start_server,
)

WORKOUT_KEY = "liftlog.activeWorkout"
TWELVE_HOURS_MS = 12 * 60 * 60 * 1000

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


# ---------- 共用操作 ----------


def stored(page) -> dict | None:
    raw = page.evaluate(f"() => localStorage.getItem('{WORKOUT_KEY}')")
    return json.loads(raw) if raw else None


def patch_stored(page, mutate_js: str) -> None:
    """就地改寫 localStorage 的 payload（mutate_js 是一段以 `p` 為參數的敘述）。"""
    page.evaluate(
        f"""() => {{
            const p = JSON.parse(localStorage.getItem('{WORKOUT_KEY}'));
            {mutate_js}
            localStorage.setItem('{WORKOUT_KEY}', JSON.stringify(p));
        }}"""
    )


def recycle(page, base: str, *, to_logger: bool = True) -> None:
    """模擬被系統回收：清掉 sessionStorage（分頁級）後重新載入。

    還原後人會落在首頁（F90 的行為），倒數要回到 logger 才看得見——所以預設把這段
    導覽一起走完（繼續訓練 → 挑動作），那才是條文 ② 說的「回到 logger」。
    """
    page.evaluate("() => sessionStorage.clear()")
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if to_logger:
        back_to_logger(page)


def back_to_logger(page) -> None:
    resume = page.get_by_role("button", name="繼續訓練")
    if not resume.count():
        return  # 訓練本身沒還原（⑥ 的反向情境）——交給呼叫端斷言
    resume.first.click()
    page.wait_for_timeout(800)
    row = page.locator(".ex-row, .exercise-row, button").filter(has_text="深蹲")
    if row.count():
        row.first.click()
        page.wait_for_timeout(800)


def start_free_workout(page) -> None:
    start_from_home(page)
    free = page.get_by_role("button", name="自由訓練")
    if free.count():
        free.click()
        page.wait_for_timeout(600)
    page.locator(".ex-row, .exercise-row, button").filter(has_text="深蹲").first.click()
    page.wait_for_timeout(600)


def enter_rest(page) -> None:
    """記一組 → 進入休息態（主按鈕變「繼續下一組」、圓環出現）。"""
    page.get_by_role("button", name="完成這組").click()
    page.wait_for_timeout(1200)


def ring_digits(page) -> str:
    loc = page.locator(".rest-ring .digits")
    return loc.first.inner_text().strip() if loc.count() else ""


def resting(page) -> bool:
    return page.locator(".rest-ring").count() > 0


def secs(text: str) -> int | None:
    """「0:47」→ 47；「-0:12」→ -12；空字串 → None。"""
    if not text:
        return None
    neg = text.startswith("-")
    body = text.lstrip("-")
    if ":" not in body:
        return None
    m, s = body.split(":")
    total = int(m) * 60 + int(s)
    return -total if neg else total


# ---------- 通知外掛替身（③ 用） ----------

# 記錄原生層真的收到什麼。**不要**照著實作寫期待——這裡只錄事實，斷言在外面下。
FAKE_LOCAL_NOTIFICATIONS = """
window.__notifyLog = [];
window.Capacitor = {
  isNativePlatform: () => true,
  getPlatform: () => 'android',
  Plugins: {
    LocalNotifications: {
      schedule: async (opts) => {
        // 只錄「幾秒後響」——那才是斷言看得懂的事實（Date 物件跨橋序列化不可靠）
        const at = opts && opts.notifications && opts.notifications[0]
          && opts.notifications[0].schedule && opts.notifications[0].schedule.at;
        const delay = at ? Math.round((new Date(at).getTime() - Date.now()) / 1000) : null;
        window.__notifyLog.push(['schedule', delay]);
        return {};
      },
      cancel: async () => { window.__notifyLog.push(['cancel', null]); return {}; },
      checkPermissions: async () => ({ display: 'granted' }),
      requestPermissions: async () => ({ display: 'granted' }),
      listChannels: async () => ({ channels: [{ id: 'default', importance: 4 }] }),
      areEnabled: async () => ({ value: true }),
    },
  },
};
"""


def main() -> int:  # noqa: C901
    port = safe_port()
    # F94 ④ 的方向先在這支新腳本落實：暫存 DB 建在系統暫存目錄，不落在 repo 內。
    # Windows 檔案鎖會讓 unlink 偶發失敗，留在 repo 就會慢慢累積（7/30 清過 12 顆）。
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f66-"))
    db = tmp / "e2e.db"
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        run_checks(base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)  # 鎖住就留給 OS 回收，不重試也不污染 repo

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    if passed != len(results):
        print("\nFAILED:")
        for ok, label in results:
            if not ok:
                print(f"  - {label}")
    return 0 if passed == len(results) else 1


def run_checks(base: str) -> None:  # noqa: C901
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---------- ①②⑤⑥：web 版的還原行為 ----------
        ctx = browser.new_context(viewport=PHONE)
        page = ctx.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("input", timeout=10_000)
        setup_and_home(page)
        start_free_workout(page)
        enter_rest(page)

        check(resting(page), "前提：記一組後進入休息態（圓環出現）")

        payload = stored(page)
        rest = (payload or {}).get("rest")
        check(
            isinstance(rest, dict) and isinstance(rest.get("startedAt"), int),
            "① restStartedAt 進了 saveActiveWorkout 的 payload",
        )
        check(
            isinstance(rest, dict)
            and "accumulatedMs" in rest
            and "resumedAt" in rest
            and "targetSeconds" in rest,
            "① F71 的累計／續跑時間戳與 F70 的目標秒數一起持久化（缺一就算不出剩餘秒數）",
        )

        # ② 倒數依實際經過時間續算：把開始時間往前挪 30 秒，回收後應該少 30 秒
        before = secs(ring_digits(page))
        patch_stored(page, "p.rest.startedAt -= 30000; p.rest.resumedAt -= 30000;")
        recycle(page, base)
        after = secs(ring_digits(page))
        check(resting(page), "② 回收後回到 logger，休息倒數還在（不是消失）")
        check(
            before is not None and after is not None and 27 <= (before - after) <= 33,
            f"② 倒數依實際經過時間續算而非重置（回收前 {before}s → 回收後 {after}s）",
        )

        # ⑤ 暫停中被回收：仍是暫停態，且回收期間不計入
        page.get_by_role("button", name="暫停").first.click()
        page.wait_for_timeout(600)
        paused_before = secs(ring_digits(page))
        # 暫停後把「回收期間」拉長 10 分鐘：resumedAt 為 null，這段不該被算進去
        patch_stored(page, "p.rest.startedAt -= 600000;")
        recycle(page, base)
        paused_after = secs(ring_digits(page))
        check(
            page.get_by_role("button", name="繼續").count() > 0,
            "⑤ 暫停中被回收，還原後仍是暫停態",
        )
        check(
            paused_before is not None
            and paused_after is not None
            and abs(paused_before - paused_after) <= 2,
            f"⑤ 回收期間不計入（暫停前 {paused_before}s → 還原後 {paused_after}s，差 ≤2s）",
        )
        acc = ((stored(page) or {}).get("rest") or {}).get("accumulatedMs")
        check(
            isinstance(acc, int) and acc > 0,
            f"⑤ F71 的 restAccumulatedMs 不因回收而歸零（{acc} ms）",
        )

        # ④ 12 小時門檻：剛好超過就不還原倒數，但訓練本身仍在，且畫面要有提示
        patch_stored(
            page,
            f"p.rest.startedAt = Date.now() - {TWELVE_HOURS_MS + 60000};"
            f"p.rest.resumedAt = p.rest.startedAt;",
        )
        recycle(page, base)
        check(not resting(page), "④ 距休息開始超過 12 小時 → 不還原倒數")
        banner = page.locator(".error-banner, .notice-banner")
        text = banner.first.inner_text() if banner.count() else ""
        check(
            banner.count() > 0 and ("休息" in text or "倒數" in text),
            f"④ 畫面有明確提示，不是靜默沒有倒數（訊息：{text[:40] or '(無)'}）",
        )
        check(
            (stored(page) or {}).get("workoutId") is not None
            and page.locator(".log-btn").count() > 0,
            "④⑥ 倒數沒還原，但訓練本身仍依 F90 還原（人還在 logger）",
        )

        # ⑥ 一邊失敗不影響另一邊：rest 區段壞掉，訓練照樣還原
        patch_stored(page, "p.rest = '這不是物件';")
        recycle(page, base)
        check(
            (stored(page) or {}).get("workoutId") is not None
            and page.locator(".log-btn").count() > 0,
            "⑥ rest 區段是壞資料時，訓練仍正常還原（不是整包當壞資料丟掉）",
        )
        check(not resting(page), "⑥ 壞掉的 rest 不會被硬解出一個假的倒數")

        # 反向：訓練還原不了（workoutId 被拿掉）時不該把人留在 logger
        page.evaluate(
            f"""() => {{
                const p = JSON.parse(localStorage.getItem('{WORKOUT_KEY}'));
                delete p.workoutId;
                localStorage.setItem('{WORKOUT_KEY}', JSON.stringify(p));
            }}"""
        )
        recycle(page, base, to_logger=False)
        check(
            page.locator(".log-btn").count() == 0,
            "⑥ 反向：訓練還原不了時不會因為 rest 還在就把人留在 logger",
        )
        ctx.close()

        # ---------- ③：app 版還原時重排本機通知 ----------
        ctx2 = browser.new_context(viewport=PHONE)
        page2 = ctx2.new_page()
        page2.add_init_script(FAKE_LOCAL_NOTIFICATIONS)
        reroute_public_host(page2, base)
        page2.goto(base, wait_until="domcontentloaded")
        page2.wait_for_selector("input", timeout=10_000)
        setup_and_home(page2)
        start_free_workout(page2)
        enter_rest(page2)

        # ③ 的前提是「使用者開著休息提醒」——沒開的話 scheduleRestNotify 本來就是 no-op，
        # 那樣測出來的「有排／沒排」兩條都會是假綠。把開關打開再測。
        page2.evaluate("() => localStorage.setItem('liftlog.nativeNotifyEnabled', '1')")

        # 還沒過點：還原時要依「剩餘秒數」重排（不是照原本的目標秒數）
        patch_stored(page2, "p.rest.startedAt -= 40000; p.rest.resumedAt -= 40000;")
        page2.evaluate("() => { window.__notifyLog = []; sessionStorage.clear(); }")
        page2.goto(base, wait_until="domcontentloaded")
        page2.wait_for_timeout(1800)
        log = page2.evaluate("() => window.__notifyLog || []")
        back_to_logger(page2)
        scheduled = [e for e in log if e[0] == "schedule"]
        check(len(scheduled) > 0, f"③ 還原時重新排定本機通知（收到 {len(scheduled)} 次 schedule）")
        remaining_now = secs(ring_digits(page2))
        check(
            remaining_now is not None and 0 < remaining_now < 30,
            f"③ 前提：此時確實只剩不到 30 秒（畫面 {remaining_now}s）",
        )

        # 已超時：不排
        patch_stored(
            page2,
            "p.rest.startedAt = Date.now() - 600000; p.rest.resumedAt = p.rest.startedAt;",
        )
        page2.evaluate("() => { window.__notifyLog = []; sessionStorage.clear(); }")
        page2.goto(base, wait_until="domcontentloaded")
        page2.wait_for_timeout(1800)
        log2 = page2.evaluate("() => window.__notifyLog || []")
        back_to_logger(page2)
        check(
            not [e for e in log2 if e[0] == "schedule"],
            "③ 還原時已超時 → 不排通知（排了等於一還原就立刻響）",
        )
        check(resting(page2), "③ 已超時仍要顯示倒數（超時是往上數，不是沒有倒數）")

        # review HIGH-1 的回歸：在**暫停中**被回收，還原後按「繼續」。
        # 原生服務已經隨 app 一起死了，送 ACTION_RESUME 只會建一個 remainingSeconds=0
        # 的新實例 → CountDownTimer(0) 立刻 onFinish → 鬧鐘當場響，而該響的那次沒排。
        # 正確行為是重新排一次（時間點要對得上畫面上的剩餘秒數）。
        patch_stored(
            page2,
            "p.rest.startedAt = Date.now() - 20000;"
            "p.rest.accumulatedMs = 20000;"
            "p.rest.resumedAt = null;",  # null＝暫停中
        )
        page2.evaluate("() => { window.__notifyLog = []; sessionStorage.clear(); }")
        page2.goto(base, wait_until="domcontentloaded")
        page2.wait_for_timeout(1800)
        back_to_logger(page2)
        check(
            not page2.evaluate("() => (window.__notifyLog || []).some(e => e[0] === 'schedule')"),
            "③ 暫停態還原時不排通知（暫停的語意是時間不走）",
        )
        remaining_before_resume = secs(ring_digits(page2))
        page2.get_by_role("button", name="繼續").first.click()
        page2.wait_for_timeout(900)
        resumed_log = page2.evaluate(
            "() => (window.__notifyLog || []).filter(e => e[0] === 'schedule')"
        )
        check(
            len(resumed_log) == 1,
            f"③ 暫停態還原後按「繼續」要重新排一次通知（實際 {len(resumed_log)} 次）",
        )
        check(
            remaining_before_resume is not None and remaining_before_resume > 0,
            f"③ 前提：按繼續時畫面確實還有剩餘秒數（{remaining_before_resume}s）",
        )
        delay = resumed_log[0][1] if resumed_log else None
        check(
            delay is not None
            and remaining_before_resume is not None
            and abs(delay - remaining_before_resume) <= 3,
            f"③ 重排的時間點對得上畫面（畫面剩 {remaining_before_resume}s，排在 {delay}s 後）",
        )
        ctx2.close()

        browser.close()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
