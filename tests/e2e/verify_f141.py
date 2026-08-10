"""F141 browser verification: Android auth gate, nonce binding and secure bridge handoff."""

from __future__ import annotations

import json
import sys

from playwright.sync_api import Route, sync_playwright


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:28741"
    stored: dict[str, object] = {
        "deviceId": "11111111-1111-4111-8111-111111111111",
        "deviceName": "Test Pixel",
    }
    login_body: dict[str, object] = {}
    credential_nonce = ""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.expose_function("authLoad", lambda: stored.copy())

        def save_session(value: dict[str, object]) -> None:
            stored.update(value)

        context.expose_function("authSave", save_session)
        page = context.new_page()
        page.add_init_script(
            """
            window.Capacitor = {
              isNativePlatform: () => true,
              getPlatform: () => 'android',
              Plugins: {
                AuthSession: {
                  loadSession: async () => window.authLoad(),
                  saveSession: async (value) => window.authSave(value),
                  clearSession: async () => {},
                  googleSignIn: async ({ nonce }) => {
                    window.__credentialNonce = nonce;
                    return { idToken: 'google-id-token',
                      deviceId: '11111111-1111-4111-8111-111111111111',
                      deviceName: 'Test Pixel' };
                  },
                },
                LocalStore: {
                  initialize: async () => ({ schemaVersion: 2, pendingMutations: 0 }),
                  snapshot: async () => ({ exercises: [], templates: [], workouts: [], sets: [],
                    body_metrics: [], daily_status: [], settings: [] }),
                  status: async () => ({ schemaVersion: 2, pendingMutations: 0 }),
                },
                AppUpdate: {
                  currentVersion: async () => ({ versionCode: 150 }),
                },
              },
            };
            """
        )

        def route_api(route: Route) -> None:
            nonlocal credential_nonce
            url = route.request.url
            if url.endswith("/api/auth/config"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(
                    {"google_client_id": "test-client"}
                ))
                return
            if url.endswith("/api/auth/google"):
                login_body.update(json.loads(route.request.post_data or "{}"))
                credential_nonce = page.evaluate("window.__credentialNonce")
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "access_token": "issued-access",
                    "refresh_token": "issued-refresh",
                    "expires_in": 900,
                    "user": {"id": "user"},
                    "device": {"id": login_body.get("device_id"), "name": "Test Pixel"},
                }))
                return
            if url.endswith("/api/app/latest"):
                route.fulfill(
                    status=404,
                    content_type="application/json",
                    body='{"error":"not found"}',
                )
                return
            if url.endswith("/health"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"status":"ok","env":"prod"}',
                )
                return
            route.fulfill(status=404, content_type="application/json", body='{"error":"not found"}')

        page.route("https://lift-log.my-super-dev-server.work/**", route_api)
        page.goto(base, wait_until="networkidle")
        button = page.get_by_role("button", name="使用 Google 登入")
        button.wait_for()
        assert page.locator("input[type=password]").count() == 0

        with page.expect_request("**/api/app/latest") as update_request:
            button.click()
        page.locator(".home-head").wait_for(timeout=10_000)

        assert login_body["nonce"] == credential_nonce
        assert login_body["id_token"] == "google-id-token"
        assert login_body["client"] == "android"
        assert stored["refreshToken"] == "issued-refresh"
        assert update_request.value.headers["authorization"] == "Bearer issued-access"
        assert page.evaluate("localStorage.getItem('liftlog.token')") is None
        browser.close()

    print("PASS  F141 native Google gate, nonce binding, secure session handoff")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
