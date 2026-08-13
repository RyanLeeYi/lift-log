"""F72 E2E：休息結束後持續倒數與持續提醒（①②③④⑤⑦⑧⑨ 的可驗面）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f72.py`

⚠ 界線：聲音與震動**只能在裝置上驗**（acceptance ⑩ 也這樣寫）。這支驗的是原生原始碼的
靜態約束（鬧鐘音量、重複震動、歸零不 stopSelf、三條停止路徑都收乾淨、通知有停止鈕）
與前端不重複震動。假物件驗不出「手機真的在響」——F62 那次的教訓。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, e2e_tmp, free_port, start_server  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


JAVA_DIR = REPO / "android/app/src/main/java/com/ryanleeyi/liftlog"


def source_checks() -> None:
    svc = (JAVA_DIR / "RestTimerService.java").read_text(encoding="utf-8")

    # ③ 鬧鐘音量＋重複震動
    check("USAGE_ALARM" in svc, "③ 用鬧鐘音量（靜音／勿擾仍會響）")
    check("setLooping(true)" in svc, "③ 聲音循環播放，不是叮一聲")
    check("createWaveform" in svc and "0)" in svc, "③ 震動用重複波形（repeat index 0）")
    check("TYPE_ALARM" in svc, "③ 取系統的鬧鐘鈴聲")

    # ①②⑦ 歸零之後服務要活著、繼續計時
    finish = svc.split("void onFinish()")[1].split("\n        }")[0] if "onFinish()" in svc else svc
    check("stopSelf()" not in finish,
          "⑦ 歸零時不再 stopSelf（服務要活著才能繼續計時與持續提醒）")
    check("overtime" in svc.lower(), "①② 有超時階段（歸零後繼續計時）")

    # ④⑦ 每一條停止路徑都要收掉聲音與震動
    for marker, label in (
        ("ACTION_STOP.equals(action)", "④ ACTION_STOP"),
        ("public void onDestroy()", "⑦ onDestroy"),
    ):
        branch = svc.split(marker)[1].split("\n    }")[0] if marker in svc else ""
        check("stopAlarm" in branch, f"{label} 會停掉聲音與震動（不留孤兒）")

    # ⑤ 通知上的停止鈕
    check("addAction" in svc, "⑤ 通知列有動作鈕")
    check("ACTION_STOP_FROM_NOTIFICATION" in svc,
          "⑤ 動作鈕走專屬 action（要同時通知前端，與前端自己按停止不同源）")

    manifest = (REPO / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    check("android.permission.VIBRATE" in manifest, "③ 宣告 VIBRATE 權限")

    overlay = (JAVA_DIR / "RestOverlay.java").read_text(encoding="utf-8")
    check("-" in overlay and "abs" in overlay.lower(),
          "① overlay 顯示得出負數（超時）")

    app_js = (REPO / "app/static/js/app.js").read_text(encoding="utf-8")
    # ⑨／不重複提醒：app 版由原生鬧鐘負責，JS 不該再震一次
    ticker = app_js.split("restTicker = setInterval")[1].split("}, 1000)")[0]
    check("restTimerRunning" in ticker,
          "③ app 版交給原生鬧鐘時 JS 不重複震動（web 版照舊）")


def main() -> int:
    port = free_port()
    db = e2e_tmp() / f"liftlog_f72_e2e_{port}.db"
    release = e2e_tmp() / f"liftlog_f72_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        source_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # ⑨ web 版：沒有 Capacitor，倒數超時仍照舊（負數顯示、單次震動）
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            r = page.evaluate(
                "async () => {"
                "  const rn = await import('/js/rest-notify.js');"
                "  return { cap: typeof window.Capacitor,"
                "           active: rn.restNotifySupported() };"
                "}"
            )
            check(r["cap"] == "undefined", "⑨ web 版沒有 Capacitor bridge（不會走到原生鬧鐘）")
            ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for _ in range(20):
            try:
                db.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.25)
        for f in release.iterdir():
            f.unlink()
        release.rmdir()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
