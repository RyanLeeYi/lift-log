"""F104 E2E（前端那一半）：浮動視窗直接記錄下一組。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f104.py`

視窗的長相（待記組那一行、± 兩顆、主按鈕、失敗態）是原生 Java，Playwright 碰不到，
一律真機驗。這支驗的是 ④ 定下的那條界線所在的一側——**實際寫入一律由前端 JS 執行**：

  ① 開始休息時把「待記組」（重量／次數／是否自體重）送給原生
  ③ 收到 logset → 走既有的記錄路徑寫入，並開新的一輪休息
  ⑤ 成功與失敗**都要回報**給原生；失敗時**不得**開新的一輪休息
  ⑦ 就地記的組 rpe 留 null，回 logger 時給提示（不擋操作）

⚠ ⑤ 的反面斷言是這支的重點。少了它，「壞掉的 payload 就拿當前值硬記」也會全綠，
而那正好製造出一筆使用者沒按過的紀錄。
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
window.__native = { starts: [], results: [], handler: null };
window.__emitLog = (weight, reps) => {
  const h = window.__native.handler;
  if (!h) return false;
  const payload = { action: 'logset' };
  if (weight !== undefined) payload.weight = weight;
  if (reps !== undefined) payload.reps = reps;
  h(payload);
  return true;
};
window.Capacitor = {
  isNativePlatform: () => true,
  getPlatform: () => 'android',
  Plugins: {
    LocalNotifications: {
      schedule: async () => ({}), cancel: async () => ({}),
      checkPermissions: async () => ({ display: 'granted' }),
      requestPermissions: async () => ({ display: 'granted' }),
      areEnabled: async () => ({ value: true }),
      listChannels: async () => ({ channels: [
        { id: 'default', importance: 3 }, { id: 'rest-timer', importance: 2 },
      ] }),
    },
    RestTimer: {
      available: async () => ({ available: true }),
      start: async (o) => { window.__native.starts.push(o); return {}; },
      stop: async () => ({}), pause: async () => ({}), resume: async () => ({}),
      overlayPermitted: async () => ({ granted: true }),
      requestOverlayPermission: async () => {},
      setRestCardVisible: async () => ({}),
      logResult: async (o) => { window.__native.results.push(Boolean(o && o.ok)); return {}; },
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
    page.wait_for_selector("input", timeout=10_000)
    setup_and_home(page)
    page.evaluate(f"() => localStorage.setItem('{NOTIFY_FLAG}', '1')")
    page.evaluate(f"() => localStorage.setItem('{OVERLAY_FLAG}', '1')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return ctx, page


def into_rest(page) -> None:
    wait_home(page)
    start_from_home(page)
    page.wait_for_timeout(1200)
    page.locator(".exercise-item").first.click()
    page.wait_for_selector(".logger-foot", timeout=8000)
    page.wait_for_timeout(400)
    page.locator(".log-btn").first.click()
    page.wait_for_selector(".rest-card", timeout=8000)
    page.wait_for_timeout(800)


def native(page) -> dict:
    return page.evaluate("() => window.__native")


def emit_log(page, weight=None, reps=None) -> None:
    args = []
    args.append("undefined" if weight is None else repr(weight))
    args.append("undefined" if reps is None else repr(reps))
    page.evaluate(f"() => window.__emitLog({args[0]}, {args[1]})")
    page.wait_for_timeout(1600)


def main() -> int:
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f104-"))
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

        # ── ① 開始休息時把待記組送下去 ──────────────────────────
        ctx, page = open_app(browser, base)
        into_rest(page)
        starts = native(page)["starts"]
        check(len(starts) >= 1, f"前提：休息交給了原生前景服務（{len(starts)} 次）")
        first = starts[-1]
        check(
            isinstance(first.get("weight"), (int, float))
            and isinstance(first.get("reps"), (int, float)),
            f"① start 帶了待記組的重量與次數（{first}）",
        )
        check("bodyweight" in first, f"① 帶了是否自體重（供視窗顯示「自體重」）（{first}）")
        check(
            isinstance(first.get("hint"), str) and first["hint"] != "",
            f"① F89 ③ 不回歸：動作提示仍照送（{first.get('hint')!r}）",
        )

        # ── ③ 收到 logset → 記進去、開新的一輪 ───────────────────
        rows_before = page.locator(".done-row").count()
        starts_before = len(native(page)["starts"])
        emit_log(page, 47.5, 6)
        check(
            page.locator(".done-row").count() == rows_before + 1,
            f"③ 就地記錄真的寫進去了（{rows_before} → {page.locator('.done-row').count()} 列）",
        )
        top = page.locator(".done-row").first.inner_text()
        check(
            "47.5" in top and "6" in top,
            f"③ 記的是**視窗上調整後**的值，不是 app 裡的舊值（{top!r}）",
        )
        check(
            len(native(page)["starts"]) == starts_before + 1,
            "③ 記完接著開新的一輪休息（又交給原生一次）",
        )
        check(native(page)["results"][-1] is True, "⑤ 成功要回報給視窗")
        # 新一輪的待記組要更新成剛記的值
        latest = native(page)["starts"][-1]
        check(
            latest.get("weight") == 47.5 and latest.get("reps") == 6,
            f"③ 新一輪的待記組更新成剛記的值（{latest}）",
        )

        # ── ⑦ 就地記的組 rpe 留 null ＋ logger 給提示 ────────────
        banner = page.locator(".notice-banner")
        banner_text = banner.first.inner_text() if banner.count() else "(無)"
        check(
            banner.count() >= 1 and "累度" in banner_text,
            f"⑦ 回 logger 有「還沒填累度」的提示（{banner_text}）",
        )
        check(
            page.locator(".modal-overlay").count() == 0,
            "⑦ 反面：提示**不得**是 modal——當下不想填是正常的，補記是選項不是義務",
        )
        # ⑦ 那一組真的沒有累度：組列上不得出現累度詞（app 內記的那組有，這組沒有）
        # ——驗渲染結果，不驗內部狀態。靜默沿用上一組的實作會在這裡掛掉。
        rows = page.locator(".done-row")
        overlay_row = rows.first.inner_text()   # 最新在最上（F20）
        app_row = rows.nth(1).inner_text()
        check(
            "輕鬆" in app_row,
            f"⑦ 前提：app 內記的那組有累度詞（{app_row!r}）",
        )
        check(
            "輕鬆" not in overlay_row,
            f"⑦ 就地記的那組**沒有**累度——不是靜默沿用上一組（{overlay_row!r}）",
        )
        ctx.close()

        # ── ⑤ 反面：壞掉的 payload 不得硬記 ──────────────────────
        ctx, page = open_app(browser, base)
        into_rest(page)
        rows_before = page.locator(".done-row").count()
        starts_before = len(native(page)["starts"])
        emit_log(page)  # 不帶重量與次數（舊版 APK）
        check(
            page.locator(".done-row").count() == rows_before,
            "⑤ 反面：payload 壞掉時**不記**——寧可回報失敗，也不要製造一筆沒人按過的紀錄",
        )
        check(native(page)["results"][-1] is False, "⑤ 失敗也要回報（不得靜默吞掉）")
        check(
            len(native(page)["starts"]) == starts_before,
            "⑤ **失敗不得開新的一輪休息**——休息開始了但組沒記到是最糟的組合",
        )
        ctx.close()

        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
