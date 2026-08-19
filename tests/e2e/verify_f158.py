"""F158（第三段）browser verification: 設定頁的 MCP token 管理 UI（acceptance 1-3）。

伺服器端的到期／唯讀語意、legacy 拒絕（acceptance 4/6/7）由 pytest
（`tests/test_mcp.py`、`tests/test_mcp_tokens_api.py`）釘住；這支只驗**瀏覽器這一側的契約**——
列表有沒有畫出該有的欄位、建立視窗有沒有把選好的到期／權限送出去、明文是不是只出現一次、
複製鈕真的把明文寫進剪貼簿、撤銷有沒有立刻反映在畫面上。

`/api/mcp-tokens/*` 用腳本自己的記憶體假資料回應（同 `verify_f148.py`／`verify_f146.py`
對 `/api/account/*`、`/api/auth/*` 的作法）——Google 登入本身無法在無網路的測試環境真的
驗 id_token，所以這批腳本一律整條 `/api/**` 攔截，只驗「前端有沒有打對請求、畫對畫面」。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_f67 import PHONE, e2e_tmp, open_settings, start_server  # noqa: E402

# 中文與符號在 Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1（F138）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSRF = "csrf-from-server"
BASE_TIME = datetime(2026, 8, 19, 3, 0, 0)  # 刻意不帶時區——同服務端 control.db 的 naive UTC 慣例

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def undersized(page) -> list[str]:
    out = []
    for i in range(page.locator("button").count()):
        b = page.locator("button").nth(i)
        if not b.is_visible():
            continue
        box = b.bounding_box()
        if box and (box["height"] < 44 or box["width"] < 44):
            label = (b.inner_text() or b.get_attribute("aria-label") or "?").strip()[:16]
            out.append(f"{label}({int(box['width'])}x{int(box['height'])})")
    return out


class McpTokenStub:
    """假的 MCP token 控制庫——只在這支腳本的行程裡存在，驗的是前端契約不是伺服器邏輯。"""

    def __init__(self) -> None:
        self.tokens: list[dict] = []
        self._next_id = 1

    def create(self, payload: dict) -> dict:
        token_id = f"tok-{self._next_id}"
        self._next_id += 1
        expires_in_days = payload.get("expires_in_days", 90)
        expires_at = None
        if expires_in_days is not None:
            expires_at = (BASE_TIME + timedelta(days=expires_in_days)).isoformat()
        row = {
            "id": token_id,
            "name": payload["name"],
            "created_at": BASE_TIME.isoformat(),
            "last_used_at": None,
            "revoked_at": None,
            "expires_at": expires_at,
            "read_only": bool(payload.get("read_only", False)),
        }
        self.tokens.append(row)
        plaintext = f"secret-{token_id}-plaintext"
        return {**row, "token": plaintext}

    def revoke(self, token_id: str) -> None:
        for row in self.tokens:
            if row["id"] == token_id:
                row["revoked_at"] = (BASE_TIME + timedelta(hours=1)).isoformat()


def main() -> int:
    port = free_port()
    db = e2e_tmp() / f"liftlog_f158_{port}.db"
    release = e2e_tmp() / f"liftlog_f158_release_{port}"
    release.mkdir(exist_ok=True)
    server = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    signed_in = {"value": False}
    calls: dict[str, list[dict]] = {}
    mcp = McpTokenStub()

    def record(path: str, request) -> dict:
        entry = {
            "method": request.method,
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": json.loads(request.post_data or "{}") if request.post_data else {},
        }
        calls.setdefault(path, []).append(entry)
        return entry

    def api_stub(route: Route) -> None:
        request = route.request
        path = request.url.split("?", 1)[0].removeprefix(base)
        entry = record(path, request)

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
        elif path == "/api/settings/weekly_target_days":
            body = {"key": "weekly_target_days", "value": "4"}
        elif path == "/api/schedule/today":
            body = {"template": None, "week": {"done": 0, "target": 4}, "last_workout": None}
        elif path == "/api/exercises":
            body = []
        elif path == "/api/mcp-tokens/" and request.method == "POST":
            route.fulfill(status=201, content_type="application/json",
                           body=json.dumps(mcp.create(entry["body"])))
            return
        elif path == "/api/mcp-tokens/" and request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(mcp.tokens))
            return
        elif path.startswith("/api/mcp-tokens/") and request.method == "DELETE":
            mcp.revoke(path.rsplit("/", 1)[-1])
            route.fulfill(status=204)
            return
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

    def local_time(page, iso: str) -> str:
        """跟前端同一條算式（append Z 再 toLocaleString）算出期望字串——
        既不綁死某個時區／ICU 版本的輸出格式，又能真的抓到「忘了補 Z」這種時區錯位。"""
        return page.evaluate(
            "(iso) => new Date(iso + 'Z').toLocaleString('zh-TW', "
            "{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})",
            iso,
        )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=PHONE, timezone_id="Asia/Taipei", accept_downloads=True,
            )
            context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
            page = context.new_page()
            page.route(f"{base}/api/**", api_stub)

            # ① 登入，進設定頁
            page.goto(base, wait_until="networkidle")
            install_gsi(page)
            page.get_by_test_id("web-google-signin").click()
            page.locator(".home-head").wait_for(timeout=15_000)
            open_settings(page)

            check(page.locator(".mcp-token-card").count() == 1, "① 設定頁有 MCP token 管理區塊")
            check("尚未建立任何 token" in page.locator(".mcp-token-card").inner_text(),
                  "① 沒有 token 時顯示空狀態")

            # ② 新增：預設有限期（90 天）、預設可寫，且未填名稱前不能送出
            page.get_by_test_id("mcp-token-add").click()
            page.get_by_test_id("mcp-token-name-input").wait_for()
            confirm_btn = page.get_by_test_id("mcp-token-create-confirm")
            check(confirm_btn.is_disabled(), "② 名稱空白時建立鈕停用")
            expiry_90 = page.get_by_test_id("mcp-token-expiry-90")
            default_expiry = expiry_90.get_attribute("class") or ""
            check("on" in default_expiry, f"② 到期預設選 90 天（{default_expiry!r}）")
            scope_write = page.get_by_test_id("mcp-token-scope-write")
            default_scope = scope_write.get_attribute("class") or ""
            check("on" in default_scope, f"② 權限預設可寫（{default_scope!r}）")

            # 選「永久」要看得到風險提示，選回有限期後提示消失
            page.get_by_test_id("mcp-token-expiry-permanent").click()
            check("外洩風險" in page.locator(".modal.confirm-modal").inner_text(),
                  "② 選永久時明講風險")
            page.get_by_test_id("mcp-token-expiry-180").click()
            check("外洩風險" not in page.locator(".modal.confirm-modal").inner_text(),
                  "② 選回有限期後風險提示收起")

            page.get_by_test_id("mcp-token-name-input").fill("Claude Desktop")
            page.get_by_test_id("mcp-token-scope-readonly").click()
            check(not confirm_btn.is_disabled(), "② 填了名稱後建立鈕可按")

            confirm_btn.click()
            page.wait_for_timeout(400)
            create_call = calls.get("/api/mcp-tokens/", [])
            posts = [c for c in create_call if c["method"] == "POST"]
            check(len(posts) == 1, f"② 送出一次建立請求（{len(posts)}）")
            body = posts[0]["body"] if posts else {}
            check(body.get("name") == "Claude Desktop"
                  and body.get("expires_in_days") == 180
                  and body.get("read_only") is True,
                  f"② 建立請求帶對名稱／到期／唯讀（{body}）")

            # 明文只出現這一次
            plaintext_field = page.get_by_test_id("mcp-token-plaintext")
            plaintext_field.wait_for()
            plaintext_value = plaintext_field.input_value()
            check(plaintext_value.startswith("secret-"),
                  f"② 明文顯示在畫面上（{plaintext_value!r}）")
            check("唯一" in page.locator(".modal.confirm-modal").inner_text()
                  and "看不到" in page.locator(".modal.confirm-modal").inner_text(),
                  "② 明講關掉就看不到了")

            page.get_by_test_id("mcp-token-copy").click()
            page.wait_for_timeout(200)
            clipboard = page.evaluate("() => navigator.clipboard.readText()")
            check(clipboard == plaintext_value, f"② 複製鈕真的把明文寫進剪貼簿（{clipboard!r}）")

            page.get_by_test_id("mcp-token-done").click()
            page.wait_for_timeout(300)
            check(page.get_by_test_id("mcp-token-plaintext").count() == 0,
                  "② 關閉視窗後明文從畫面上消失")

            # ① 列表反映剛建立的 token
            row = page.get_by_test_id("mcp-token-row").first
            row.wait_for()
            row_text = row.inner_text()
            check("Claude Desktop" in row_text, f"① 列表顯示名稱（{row_text!r}）")
            check("唯讀" in row_text, "① 列表顯示唯讀旗標")
            check("尚未使用" in row_text, "① 列表顯示尚未使用過")
            expected_created = local_time(page, BASE_TIME.isoformat())
            check(expected_created in row_text, f"① 建立時間以本地時間呈現（{expected_created!r}）")
            expected_expiry = local_time(page, (BASE_TIME + timedelta(days=180)).isoformat())
            check(expected_expiry in row_text, f"① 到期時間以本地時間呈現（{expected_expiry!r}）")

            # ③ 撤銷：即時反映在列表，且送出真的撤銷請求
            page.get_by_test_id("mcp-token-revoke").click()
            confirm_modal = page.locator(".modal.confirm-modal")
            confirm_modal.wait_for()
            check("Claude Desktop" in confirm_modal.inner_text(), "③ 撤銷確認視窗點名該 token")
            page.get_by_test_id("mcp-token-revoke-confirm").click()
            page.wait_for_timeout(400)

            deletes = [c for c in calls.get("/api/mcp-tokens/tok-1", []) if c["method"] == "DELETE"]
            check(len(deletes) == 1, f"③ 送出一次撤銷請求（{len(deletes)}）")
            row_text_after = page.get_by_test_id("mcp-token-row").first.inner_text()
            check("已撤銷" in row_text_after, f"③ 列表即時顯示已撤銷（{row_text_after!r}）")
            check(page.get_by_test_id("mcp-token-revoke").count() == 0,
                  "③ 撤銷後不再顯示撤銷鈕（不能再操作已死的 token）")

            check(not undersized(page), f"觸控目標 ≥44px（不足：{undersized(page)}）")
            no_hscroll = "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
            check(page.evaluate(no_hscroll), "設定頁無水平捲動（390 寬）")

            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
        for _ in range(20):
            try:
                db.unlink(missing_ok=True)
                break
            except PermissionError:
                import time

                time.sleep(0.25)
        for f in release.iterdir():
            f.unlink()
        release.rmdir()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
