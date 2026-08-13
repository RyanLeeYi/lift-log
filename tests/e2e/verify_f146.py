"""F146 browser verification: web Google session, CSRF on writes, logout, outage state.

伺服器端的 cookie 旗標、CSRF 比對與跨帳號隔離由 pytest（`tests/test_auth.py`、
`tests/test_user_isolation.py`）釘住；這支只驗**瀏覽器這一側的契約**——
網頁到底有沒有改用 cookie session、寫入有沒有帶 CSRF header、access token 有沒有
外洩到 localStorage、登出與服務中斷的畫面是否誠實。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

# 中文與 ⚠ 這類字在 Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1（F138）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
TOKEN = "f146-token"
CSRF = "csrf-from-server"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(port: int) -> subprocess.Popen:
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f146_{port}.db"
    if tmpdb.exists():
        tmpdb.unlink()
    env = dict(os.environ, LIFTLOG_TOKEN=TOKEN, LIFTLOG_DB=str(tmpdb))
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app_factory", "--factory",
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=str(REPO), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return proc
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("伺服器沒有在 30 秒內起來")


def main() -> int:
    port = free_port()
    server = start_server(port)
    base = f"http://127.0.0.1:{port}"
    login_body: dict[str, object] = {}
    seen: dict[str, dict[str, str]] = {}
    session_status = {"code": 200}
    signed_in = {"value": False}  # 還沒登入前 session 必須 401，否則畫面直接進首頁

    def api_stub(route: Route) -> None:
        """只攔認證與 domain 讀取——重點是記下請求長什麼樣，不是回什麼資料。"""
        request = route.request
        url = request.url
        path = url.split("?", 1)[0].removeprefix(base)
        seen[path] = {key.lower(): value for key, value in request.headers.items()}

        if path == "/api/auth/config":
            body = {"google_client_id": "test-client"}
        elif path == "/api/auth/google":
            login_body.update(json.loads(request.post_data or "{}"))
            signed_in["value"] = True
            route.fulfill(
                status=200,
                content_type="application/json",
                headers={"set-cookie": "liftlog_session=web-cookie; Path=/api; HttpOnly"},
                body=json.dumps({"csrf_token": CSRF, "user": {"id": "u1"},
                                 "device": {"id": login_body.get("device_id"), "name": "Web"}}),
            )
            return
        elif path == "/api/auth/session":
            if not signed_in["value"]:
                route.fulfill(status=401, content_type="application/json",
                              body='{"error":"unauthorized"}')
                return
            if session_status["code"] != 200:
                route.fulfill(status=session_status["code"], content_type="application/json",
                              body='{"error":"unavailable"}')
                return
            body = {"csrf_token": CSRF, "user": {"id": "u1"},
                    "device": {"id": "web-device", "name": "Web"}}
        elif path == "/api/auth/logout":
            signed_in["value"] = False
            route.fulfill(status=204, body="")
            return
        elif path == "/api/schedule/today":
            body = {"template": None, "week": {"done": 0, "target": 4}, "last_workout": None}
        elif path == "/api/exercises":
            body = []
        else:
            body = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.route(f"{base}/api/**", api_stub)

            # ① 未登入：Google 登入是主要動作，API token 仍留著當備援入口
            page.goto(base, wait_until="networkidle")
            button = page.get_by_test_id("web-google-signin")
            button.wait_for()
            assert page.locator("input[type=password]").count() == 1, "API token 備援入口不見了"

            # ② 登入：走 client=web，且不把任何 token 寫進 localStorage
            page.evaluate(
                """() => {
                  window.google = { accounts: { id: {
                    initialize: (options) => { window.__cb = options.callback;
                                               window.__nonce = options.nonce; },
                    prompt: () => window.__cb({ credential: 'google-id-token' }),
                  } } };
                }"""
            )
            button.click()
            page.locator(".home-head").wait_for(timeout=15_000)
            assert login_body["client"] == "web", login_body
            assert login_body["id_token"] == "google-id-token"
            assert len(str(login_body["nonce"])) >= 16
            assert page.evaluate("localStorage.getItem('liftlog.token')") is None
            assert "access_token" not in login_body

            # ③ 登入後的請求：帶 CSRF header，不帶 Authorization
            domain = seen.get("/api/schedule/today") or seen["/api/exercises"]
            assert domain.get("x-csrf-token") == CSRF, domain
            assert "authorization" not in domain, domain

            # ④ 登出：帶 CSRF，回到登入畫面
            page.get_by_role("button", name="設定").click()
            page.get_by_test_id("web-signout").click()
            page.get_by_test_id("web-google-signin").wait_for(timeout=15_000)
            assert seen["/api/auth/logout"].get("x-csrf-token") == CSRF

            # ⑤ 服務不可用：講明是服務端的問題，不冒充成空資料
            signed_in["value"] = True
            session_status["code"] = 503
            page.goto(base, wait_until="networkidle")
            page.get_by_test_id("web-google-signin").wait_for()
            banner = page.locator(".error-banner")
            banner.wait_for(timeout=5_000)
            text = banner.inner_text()
            assert "無法連上登入服務" in text, text
            assert "資料沒有遺失" in text, text  # 不把服務中斷講成「請重新登入」

            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)

    print("PASS  F146 web cookie session, CSRF header, logout, outage state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
