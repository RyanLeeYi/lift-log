"""F67 E2E：app 內自我更新（①③④⑤⑥⑦）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f67.py`

⚠ 界線：假 plugin 證明的是「前端在對的時機呼叫了對的東西」，**不是** APK 真的裝得起來。
真正的安裝（④ 的系統安裝器、⑤ 的未知來源授權）只能在裝置上驗——F62 那次的教訓是
假物件會複製實作者的誤解，所以這裡刻意不宣稱涵蓋安裝行為。
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
TOKEN = "e2e-f67-token"
PHONE = {"width": 390, "height": 844}

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server(port: int, db: Path, release_dir: Path) -> subprocess.Popen:
    import os

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app_factory", "--factory",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO,
        env={**dict(os.environ), "LIFTLOG_TOKEN": TOKEN, "LIFTLOG_DB": str(db),
             "LIFTLOG_RELEASE_DIR": str(release_dir)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("server did not come up")


# canInstall 由 window.__canInstall 控制，才能同時驗「已授權」與「未授權」兩條路。
FAKE_PLUGIN = """
(currentVersion, canInstall) => {
  window.__au = { downloads: [], installs: [], openedSettings: 0 };
  window.__canInstall = canInstall;
  window.Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => 'android',
    Plugins: {
      AppUpdate: {
        currentVersion: async () => ({ versionCode: currentVersion }),
        canInstall: async () => ({ allowed: window.__canInstall }),
        openInstallSettings: async () => { window.__au.openedSettings += 1; },
        addListener: async (name, cb) => { window.__cb = cb; return { remove: () => {} }; },
        download: async (opts) => {
          window.__au.downloads.push(opts);
          window.__cb && window.__cb({ written: 5, total: 10 });
          return { path: '/data/updates/lift-log-update.apk' };
        },
        install: async (opts) => { window.__au.installs.push(opts); },
      },
    },
  };
}
"""


def gradle_checks() -> None:
    """① versionCode 不得寫死。"""
    gradle = (REPO / "android/app/build.gradle").read_text(encoding="utf-8")
    check("versionCode liftlogVersion" in gradle, "① versionCode 由 APP_VERSION 推導，不再寫死")
    check(re.search(r"versionCode\s+1\b", gradle) is None,
          "① build.gradle 已無寫死的 versionCode 1")
    manifest = (REPO / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    check("REQUEST_INSTALL_PACKAGES" in manifest, "⑤ Manifest 宣告 REQUEST_INSTALL_PACKAGES")
    paths = (REPO / "android/app/src/main/res/xml/file_paths.xml").read_text(encoding="utf-8")
    check("external-files-path" in paths and "updates" in paths,
          "④ FileProvider 已開放 updates 目錄（否則安裝器讀不到檔案）")


PUBLIC_HOST = "https://lift-log.my-super-dev-server.work"


def native(page, base: str, current: int, can_install: bool = True):
    args = f"({current}, {str(can_install).lower()})"
    page.add_init_script(FAKE_PLUGIN.strip().join(["(", f"){args}"]))

    # app 版的 API 會打向公開站（F61 ③）——導回本機測試伺服器，別碰正式站。
    # 不能用 continue_(url=...)：Playwright 不允許改協定（https→http）。
    # 補 ACAO 是模擬環境的權宜；真機的 origin 是 https://localhost，由後端白名單放行。
    def reroute(route):
        req = route.request
        allow = {"access-control-allow-origin": base, "access-control-allow-headers": "*"}
        if req.method == "OPTIONS":
            route.fulfill(status=200, headers={**allow, "access-control-allow-methods": "*"})
            return
        resp = page.context.request.fetch(
            req.url.replace(PUBLIC_HOST, base),
            method=req.method,
            headers=req.headers,
            data=req.post_data,
        )
        route.fulfill(response=resp, headers={**resp.headers, **allow})

    page.route(f"{PUBLIC_HOST}/**", reroute)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    return page


def setup_and_home(page) -> None:
    page.fill("input", TOKEN)
    page.get_by_role("button").first.click()
    page.wait_for_timeout(1200)


def dismiss_modal(page) -> None:
    """F68 起有更新時會自動彈視窗蓋住首頁——先收起來才點得到底下的東西。

    F67 的條文（③ 顯示、④ 點了會下載安裝）目的不變，只是手段多了一層視窗，
    所以這裡改的是測試路徑而非凍結條文（見 handoff 的「上游 feature 讓下游測試失效」）。
    """
    later = page.get_by_role("button", name="稍後再說")
    if later.count():
        later.click()
        page.wait_for_timeout(300)


def start_update_from_banner(page) -> None:
    """經由橫幅 → 視窗 → 立即更新，走完 F68 之後的更新路徑。"""
    page.locator(".update-banner").click()
    page.wait_for_timeout(300)
    page.get_by_role("button", name="立即更新").click()


def main() -> int:
    port = free_port()
    db = REPO / f"liftlog_f67_e2e_{port}.db"
    release = REPO / f"liftlog_f67_release_{port}"
    release.mkdir(exist_ok=True)
    (release / "lift-log-v99.apk").write_bytes(b"PK\x03\x04" + b"x" * 2_000_000)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        gradle_checks()
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # ⑦ web 版：完全不該出現更新橫幅
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10_000)
            setup_and_home(page)
            check(page.locator(".update-banner").count() == 0, "⑦ web 版首頁沒有更新橫幅")
            check(page.evaluate(
                "async () => (await import('/js/app-update.js')).checkForUpdate()") is None,
                "⑦ web 版 checkForUpdate 回 null（不查、不顯示）")
            ctx.close()

            # ③ app 版有新版 → 橫幅出現且帶版號與大小
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=64)
            setup_and_home(page)
            dismiss_modal(page)
            banner = page.locator(".update-banner")
            check(banner.count() == 1, f"③ app 版有新版時首頁顯示橫幅（{banner.count()}）")
            text = banner.inner_text() if banner.count() else ""
            check("v99" in text, f"③ 橫幅帶伺服器版號：{text!r}")
            check("MB" in text, "③ 橫幅顯示下載大小")

            # ③ 只在首頁：進到選動作畫面後不得出現（視窗已於上方收起）
            page.get_by_role("button").first.click()  # 開練
            page.wait_for_timeout(800)
            check(page.locator(".update-banner").count() == 0,
                  "③ 離開首頁後橫幅消失（訓練中不打斷）")
            ctx.close()

            # ③ 已是最新 → 不顯示
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=99)
            setup_and_home(page)
            check(page.locator(".update-banner").count() == 0, "③ 版本相同時不顯示橫幅")
            check(page.get_by_role("button", name="立即更新").count() == 0,
                  "③ 版本相同時也不會彈視窗")
            ctx.close()

            # ④ 點擊 → 下載（帶 token）並喚起安裝器
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=64)
            setup_and_home(page)
            dismiss_modal(page)
            start_update_from_banner(page)
            page.wait_for_timeout(1200)
            au = page.evaluate("() => window.__au")
            check(len(au["downloads"]) == 1, f"④ 觸發一次下載（{len(au['downloads'])}）")
            dl = au["downloads"][0] if au["downloads"] else {}
            check(dl.get("token") == TOKEN, "④ 下載帶 token（APK 端點需授權）")
            check("/api/app/apk" in (dl.get("url") or ""),
                  f"④ 下載打到 APK 端點：{dl.get('url')!r}")
            check(len(au["installs"]) == 1, "④ 下載完喚起系統安裝器")
            check(au["installs"][0]["path"].endswith(".apk"), "④ 安裝器收到 APK 路徑")
            ctx.close()

            # ⑤ 未授權安裝未知應用程式 → 開設定頁、不下載
            ctx = browser.new_context(viewport=PHONE)
            page = native(ctx.new_page(), base, current=64, can_install=False)
            setup_and_home(page)
            dismiss_modal(page)
            start_update_from_banner(page)
            page.wait_for_timeout(1000)
            au = page.evaluate("() => window.__au")
            check(au["openedSettings"] >= 1, "⑤ 未授權時實際開啟「安裝未知應用程式」設定頁")
            check(len(au["downloads"]) == 0, "⑤ 未授權時不下載（先解決權限再說）")
            err = page.locator(".error-banner")
            check(err.count() == 1 and "設定" in err.inner_text(),
                  f"⑥ 失敗有可辨識訊息：{err.inner_text() if err.count() else '(無)'}")
            ctx.close()

            browser.close()

        # ⑥ 伺服器沒有發佈版本 → 404，前端據此不顯示（不是錯誤）
        import json
        from urllib.error import HTTPError
        from urllib.request import Request as UrlRequest

        for f in release.iterdir():
            f.unlink()
        try:
            urlopen(UrlRequest(f"{base}/api/app/latest",
                               headers={"Authorization": f"Bearer {TOKEN}"}), timeout=5)
            check(False, "⑥ 無發佈版本時應回 404")
        except HTTPError as e:
            body = json.loads(e.read() or b"{}")
            check(e.code == 404 and "error" in body,
                  f"⑥ 無發佈版本時回 404 且帶訊息：{body.get('error')!r}")
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
