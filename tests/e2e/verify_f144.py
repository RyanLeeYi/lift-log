"""F144 native bootstrap gate and sync status UI browser verification."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_capacitor import build_fake_capacitor  # noqa: E402
from playwright.sync_api import Page, sync_playwright  # noqa: E402

APP_URL = "http://127.0.0.1:8765/"


def install_native_mocks(page: Page, *, bootstrap_complete: bool) -> None:
    initial_status = json.dumps(
        {
            "state": "synced" if bootstrap_complete else "offline",
            "pending": 0,
            "failed": 0,
            "cursor": 0,
            "lastSyncedAt": 1000 if bootstrap_complete else None,
            "bootstrapComplete": bootstrap_complete,
        }
    )
    bootstrap_js = json.dumps(bootstrap_complete)
    retry_state = json.dumps("pending" if bootstrap_complete else "offline")
    retry_pending = 2 if bootstrap_complete else 0
    preamble = """
globalThis.fetch = async () => ({
  ok: false,
  status: 503,
  json: async () => ({ error: "offline" }),
});
globalThis.__syncCalls = 0;
const emptySnapshot = {
  exercises: [], templates: [], workouts: [], sets: [],
  body_metrics: [], daily_status: [],
  settings: [{ key: "weekly_target_days", value: "4" }],
};
"""
    auth_session = """
      loadSession: async () => ({
        accessToken: "test-access",
        refreshToken: "test-refresh",
        accessExpiresAt: Date.now() + 900000,
        deviceId: "11111111-1111-4111-8111-111111111111",
      }),
    """
    local_store = """
      initialize: async () => ({ schemaVersion: 3, seededExercises: 0 }),
      snapshot: async () => emptySnapshot,
      status: async () => ({ pendingMutations: 0 }),
    """
    sync = f"""
      initialize: async () => ({initial_status}),
      status: async () => ({{
        state: "pending", pending: 2, failed: 0, cursor: 3,
        lastSyncedAt: 1000, bootstrapComplete: true,
      }}),
      syncNow: async () => {{
        globalThis.__syncCalls += 1;
        if ({bootstrap_js} && globalThis.__syncCalls >= 2) {{
          return {{
            state: "synced", pending: 0, failed: 0, cursor: 5,
            lastSyncedAt: Date.now(), bootstrapComplete: true,
          }};
        }}
        return {{
          state: {retry_state},
          pending: {retry_pending}, failed: 0, cursor: 0,
          bootstrapComplete: {bootstrap_js},
        }};
      }},
    """
    page.add_init_script(
        script=build_fake_capacitor(
            preamble=preamble,
            auth_session=auth_session,
            local_store=local_store,
            sync=sync,
        )
    )


def verify_bootstrap_gate(page: Page) -> None:
    install_native_mocks(page, bootstrap_complete=False)
    page.goto(APP_URL)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="正在準備本機資料").wait_for()
    page.get_by_role("button", name="重試同步").wait_for()
    assert page.get_by_text("首次登入要先完整下載雲端資料").is_visible()
    assert page.get_by_role("button", name="開始訓練").count() == 0


def verify_status_and_manual_sync(page: Page) -> None:
    install_native_mocks(page, bootstrap_complete=True)
    page.goto(APP_URL)
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="設定").wait_for()
    page.get_by_role("button", name="設定").click()
    page.get_by_role("heading", name="設定").wait_for()
    page.get_by_text("資料同步", exact=True).wait_for()
    page.get_by_text("2 筆待同步", exact=True).wait_for()
    page.get_by_role("button", name="立即同步").click()
    page.get_by_text("上次同步", exact=False).wait_for()
    assert page.evaluate("globalThis.__syncCalls") >= 2


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        bootstrap_page = None
        healthy_page = None
        try:
            bootstrap_page = browser.new_page()
            verify_bootstrap_gate(bootstrap_page)
            healthy_page = browser.new_page()
            verify_status_and_manual_sync(healthy_page)
        except Exception:
            screenshot = Path(tempfile.gettempdir()) / "lift-log-f144-failure.png"
            try:
                (healthy_page or bootstrap_page).screenshot(path=str(screenshot), full_page=True)
                print(f"failure screenshot: {screenshot}")
            except Exception:
                pass
            raise
        finally:
            browser.close()
    print("F144 browser verification passed: bootstrap gate + manual sync status UI")


if __name__ == "__main__":
    main()
