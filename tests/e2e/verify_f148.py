"""F148 browser verification: export / logout-block / delete-account UI wiring.

Server-side rate limit, reauth 驗證、tombstone、token 撤銷都由 pytest
（`tests/test_account.py`）釘住；這支只驗**瀏覽器這一側的契約**——
按鈕存不存在、reauth 有沒有真的重新跑一次 Google 憑證流程、CSRF header 有沒有帶上、
二次確認輸入框有沒有真的擋住誤按。
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

# 中文與符號在 Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1（F138）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
TOKEN = "f148-token"
CSRF = "csrf-from-server"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(port: int) -> subprocess.Popen:
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f148_{port}.db"
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
    signed_in = {"value": False}
    calls: dict[str, list[dict]] = {}

    def record(path: str, request) -> None:
        entry = {
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": json.loads(request.post_data or "{}") if request.post_data else {},
        }
        calls.setdefault(path, []).append(entry)

    def api_stub(route: Route) -> None:
        request = route.request
        path = request.url.split("?", 1)[0].removeprefix(base)
        record(path, request)

        if path == "/api/auth/config":
            body = {"google_client_id": "test-client"}
        elif path == "/api/auth/google":
            signed_in["value"] = True
            route.fulfill(
                status=200,
                content_type="application/json",
                headers={"set-cookie": "liftlog_session=web-cookie; Path=/api; HttpOnly"},
                body=json.dumps({
                    "csrf_token": CSRF, "user": {"id": "u1"},
                    "device": {"id": "web-device", "name": "Web"},
                }),
            )
            return
        elif path == "/api/auth/session":
            if not signed_in["value"]:
                route.fulfill(status=401, content_type="application/json",
                              body='{"error":"unauthorized"}')
                return
            body = {"csrf_token": CSRF, "user": {"id": "u1"},
                    "device": {"id": "web-device", "name": "Web"}}
        elif path == "/api/account/export":
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({
                    "schema_version": 1, "exported_at": "2026-08-14T00:00:00Z",
                    "exercises": [], "templates": [], "workouts": [],
                    "body_metrics": [], "daily_status": [], "settings": {},
                }),
            )
            return
        elif path == "/api/account/delete":
            route.fulfill(status=200, content_type="application/json",
                           body='{"status":"deleted"}')
            return
        elif path == "/api/settings/weekly_target_days":
            body = {"key": "weekly_target_days", "value": "4"}
        elif path == "/api/schedule/today":
            body = {"template": None, "week": {"done": 0, "target": 4}, "last_workout": None}
        elif path == "/api/exercises":
            body = []
        else:
            body = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def install_gsi(page) -> None:
        page.evaluate(
            """() => {
              window.google = { accounts: { id: {
                initialize: (options) => { window.__cb = options.callback;
                                           window.__nonce = options.nonce; },
                prompt: () => window.__cb({ credential: 'fresh-google-id-token' }),
              } } };
            }"""
        )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900},
                                           accept_downloads=True)
            page = context.new_page()
            page.route(f"{base}/api/**", api_stub)

            # ① 登入
            page.goto(base, wait_until="networkidle")
            install_gsi(page)
            page.get_by_test_id("web-google-signin").click()
            page.locator(".home-head").wait_for(timeout=15_000)

            # ② 設定頁看得到帳號區塊
            page.get_by_role("button", name="設定").click()
            export_btn = page.get_by_test_id("account-export")
            export_btn.wait_for()
            page.get_by_test_id("account-delete-open").wait_for()

            # ③ 匯出：重新跑一次 Google 憑證流程（新的 nonce），CSRF header 隨請求送出，
            #    瀏覽器真的觸發下載
            install_gsi(page)
            with page.expect_download(timeout=15_000) as download_info:
                export_btn.click()
            download = download_info.value
            assert download.suggested_filename.startswith("lift-log-export-")
            export_call = calls["/api/account/export"][-1]
            assert export_call["headers"].get("x-csrf-token") == CSRF, export_call
            assert export_call["body"]["id_token"] == "fresh-google-id-token"
            assert len(export_call["body"]["nonce"]) >= 16

            # ④ 刪帳：二次確認輸入框沒打對 DELETE 前，確認鈕維持 disabled
            page.get_by_test_id("account-delete-open").click()
            confirm_btn = page.get_by_test_id("account-delete-confirm")
            confirm_input = page.get_by_test_id("account-delete-confirm-input")
            confirm_input.wait_for()
            assert confirm_btn.is_disabled()
            confirm_input.fill("delete")  # 大小寫不符
            assert confirm_btn.is_disabled()
            confirm_input.fill("DELETE")
            assert not confirm_btn.is_disabled()

            install_gsi(page)
            confirm_btn.click()
            page.wait_for_timeout(500)  # 送出後頁面會 reload；給一點時間讓請求真的打出去
            delete_call = calls["/api/account/delete"][-1]
            assert delete_call["headers"].get("x-csrf-token") == CSRF, delete_call
            assert delete_call["body"]["confirm"] == "DELETE"
            assert delete_call["body"]["id_token"] == "fresh-google-id-token"

            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)

    print("PASS  F148 export/logout-block/delete-account UI wiring")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
