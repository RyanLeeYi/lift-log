"""F61 E2E：Capacitor 殼的前端分歧（③⑤⑥）＋ web 版回歸。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f61.py`

驗兩種執行環境：
- **web 版**（沒有 window.Capacitor）：API 走相對路徑、SW 照常註冊、記錄流程可用 —— 即 ⑥ 的回歸
- **app 版模擬**（注入 window.Capacitor.isNativePlatform → true）：API 打公開站、SW **不**註冊

⚠ 模擬的界線：頁面仍由本機伺服器供檔，origin 不是真的 `https://localhost`，所以這裡驗的是
**前端分支邏輯**，不是真機行為。真機安裝後的可用性是 acceptance ④，只能在裝置上驗。
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright
from verify_f67 import e2e_tmp  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TOKEN = "e2e-f61-token"
PUBLIC_HOST = "https://lift-log.my-super-dev-server.work"
PHONE = {"width": 390, "height": 844}

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server(port: int, db: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app_factory", "--factory",
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=REPO,
        env={**dict(__import__("os").environ), "LIFTLOG_TOKEN": TOKEN, "LIFTLOG_DB": str(db)},
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


def round_trip(page) -> int:
    """直接呼叫 api.js 做一次真實往返：這正是 ③／⑥ 的分歧點（base URL 前綴）。
    比點 UI 穩，也保證斷言不是在「沒有任何請求」的空前提下綠掉。"""
    return page.evaluate(
        "async () => {"
        "  const { api } = await import('/js/api.js');"
        "  const r = await api.searchExercises('');"
        "  return Array.isArray(r) ? r.length : -1;"
        "}"
    )


def open_settings(page) -> None:
    """F81：版號搬進設定畫面（首頁右上角齒輪）。"""
    page.locator(".home-settings").click()
    page.wait_for_timeout(700)


def setup_token(page, base: str) -> None:
    """走 setup 畫面存 token（app 版與 web 版共用同一段流程）。"""
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    page.fill("input", TOKEN)
    page.get_by_role("button").first.click()
    page.wait_for_timeout(800)


def verify_version_consistency() -> None:
    """⑤ 版號兩處一致（不釘死數字——踩過三次的坑）。"""
    sw = (REPO / "app/static/sw.js").read_text(encoding="utf-8")
    state = (REPO / "app/static/js/state.js").read_text(encoding="utf-8")
    cache = re.search(r'CACHE_NAME\s*=\s*"liftlog-shell-(v\d+)"', sw)
    app_v = re.search(r'APP_VERSION\s*=\s*"(v\d+)"', state)
    check(bool(cache and app_v) and cache.group(1) == app_v.group(1),
          f"⑤ sw.js CACHE_NAME 與 APP_VERSION 一致（{cache and cache.group(1)}）")
    shell_listed = '"/js/env.js"' in sw
    check(shell_listed, "⑤ 新增的 env.js 已列進 SW SHELL（否則離線首開缺檔）")


def verify_web(page, base: str) -> None:
    api_urls: list[str] = []
    page.on("request", lambda r: api_urls.append(r.url) if "/api/" in r.url else None)
    setup_token(page, base)

    open_settings(page)  # F81：版號搬進設定畫面
    version = page.locator(".version-tag").inner_text()
    state = (REPO / "app/static/js/state.js").read_text(encoding="utf-8")
    expected = re.search(r'APP_VERSION\s*=\s*"(v\d+)"', state).group(1)
    check(version.strip() == expected, f"⑤ web 畫面角落版號＝原始碼版本（{version.strip()}）")

    page.get_by_role("button", name="回首頁").first.click()
    page.wait_for_timeout(700)
    count = round_trip(page)
    check(count > 0, f"⑥ web 版 API 往返成功並取回種子動作（{count} 筆）")
    check(len(api_urls) >= 2, f"⑥ web 版確實發出多個 API 請求（{len(api_urls)} 個，前提非空）")
    check(all(u.startswith(base) for u in api_urls),
          f"⑥ web 版 API 全走同源相對路徑（{len(api_urls)} 個請求）")
    check(not any(u.startswith(PUBLIC_HOST) for u in api_urls),
          "⑥ web 版沒有誤打公開站")

    registered = page.evaluate(
        "async () => (await navigator.serviceWorker.getRegistrations()).length"
    )
    check(registered > 0, f"⑥ web 版 SW 照常註冊（{registered} 個）")


def verify_native_sim(page, base: str) -> None:
    """注入 window.Capacitor 後，API 前綴與 SW 行為都要換一條路。"""
    page.add_init_script(
        "window.Capacitor = { isNativePlatform: () => true, getPlatform: () => 'android' };"
    )

    seen: list[str] = []

    def reroute(route):
        req = route.request
        seen.append(req.url)
        # 把打向公開站的請求轉回本機伺服器，讓流程能繼續（不碰真的正式站）。
        # 不能用 continue_(url=...)——Playwright 不允許改協定（https→http），只能自己抓再 fulfill。
        # 補上 ACAO 是為了讓模擬環境的流程走得下去：真機的 origin 是 https://localhost，
        # 由後端 CAPACITOR_ORIGINS 放行（見 tests/test_cors.py），不靠這裡。
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

    other: list[str] = []
    page.on(
        "request",
        lambda r: other.append(r.url)
        if "/api/" in r.url and not r.url.startswith(PUBLIC_HOST)
        else None,
    )

    setup_token(page, base)

    count = round_trip(page)
    check(count > 0, f"③ app 版經公開站 base URL 往返成功（取回 {count} 筆動作）")
    check(len(seen) >= 2, f"③ app 版 API 打向公開站（攔到 {len(seen)} 個請求，前提非空）")
    # F61 ③ 的凍結條文只要求「app 版指向公開站」，沒有限定 /api/ 前綴；原本寫死 /api/
    # 是這支腳本自己加嚴的。F93 ⑫（後簽核）明訂環境標示的來源是**免 auth 的 /health**
    # ——setup 畫面還沒 token 時就得顯示得出來，它天生不在 /api/ 下。故白名單放行 /health。
    allowed = (f"{PUBLIC_HOST}/api/", f"{PUBLIC_HOST}/health")
    check(all(u.startswith(allowed) for u in seen),
          "③ app 版的公開站請求只落在 /api/ 與免 auth 的 /health")
    check(not other, f"③ app 版沒有殘留的同源 API 請求（殘留 {len(other)} 個）")

    registered = page.evaluate(
        "async () => (await navigator.serviceWorker.getRegistrations()).length"
    )
    check(registered == 0, "③ app 版不註冊 SW（避免供出舊資產／push 卡死）")

    push_supported = page.evaluate(
        "async () => (await import('/js/push.js')).pushSupported()"
    )
    check(push_supported is False,
          "⑨ app 版 pushSupported() 為 false（F31 web push 停用，交給 F62）")


def main() -> int:
    port = free_port()
    db = e2e_tmp() / f"liftlog_f61_e2e_{port}.db"
    proc = start_server(port, db)
    base = f"http://127.0.0.1:{port}"
    try:
        verify_version_consistency()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            web_ctx = browser.new_context(viewport=PHONE)
            verify_web(web_ctx.new_page(), base)
            web_ctx.close()

            native_ctx = browser.new_context(viewport=PHONE)
            verify_native_sim(native_ctx.new_page(), base)
            native_ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for _ in range(20):  # Windows：檔案句柄釋放有延遲，刪不掉就再等
            try:
                db.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.25)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
