"""F165 E2E：內建對話畫面（acceptance ①-⑥）。

跑法：`uv run python tests/e2e/verify_f165.py`

只攔 `/api/chat/`——LLM 這一段在測試環境沒有 key 也不該打外網，所以由腳本假扮 F164 的回應
（acceptance ⑦ 明文要求）。其餘 `/api/**` 一律打**真的**本機伺服器：確認寫入時腳本用同一顆
legacy token 走真的 `POST /api/workouts/batch` 建立那筆訓練，所以 ③「重新進日曆看得到那筆」
驗的是真的資料庫，不是假回應。

⚠ 界線：這支不驗 server 端的兩段式語意（第一次不寫、第二次才寫、key 不落地）——
那是 F164 的 pytest（`tests/test_chat.py`）釘的，這裡驗的是瀏覽器這一側的畫面契約。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_f67 import (  # noqa: E402
    PHONE,
    TOKEN,
    e2e_tmp,
    open_settings,
    safe_port,
    setup_and_home,
    start_server,
    wait_home,
)

# 中文與符號在 Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1（F138）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TODAY = date.today().isoformat()

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def open_chat(page) -> None:
    page.locator(".bottom-nav").get_by_role("button", name="對話").click()
    page.wait_for_selector(".screen.chat-screen", timeout=10_000)


def say(page, text: str) -> None:
    page.get_by_test_id("chat-input").fill(text)
    page.get_by_test_id("chat-send").click()
    page.wait_for_timeout(600)


def main() -> int:
    port = safe_port()
    db = e2e_tmp() / f"liftlog_f165_{port}.db"
    release = e2e_tmp() / f"liftlog_f165_release_{port}"
    release.mkdir(exist_ok=True)
    server = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"

    write_args = {
        "sets": [
            {"exercise": "深蹲", "weight_kg": 60, "reps": 5},
            {"exercise": "深蹲", "weight_kg": 60, "reps": 5},
            {"exercise": "深蹲", "weight_kg": 60, "reps": 5},
        ],
        "date": TODAY,
        "create_missing": True,
    }
    # 腳本要模擬的下一個 /api/chat 回應（狀態碼, body）；每次請求消掉一個。
    scripted: list[tuple[int, dict]] = []
    chat_calls: list[dict] = []

    def chat_stub(route: Route) -> None:
        request = route.request
        body = json.loads(request.post_data or "{}")
        headers = {k.lower(): v for k, v in request.headers.items()}
        chat_calls.append({"body": body, "headers": headers})
        status_code, payload = scripted.pop(0)
        if payload.get("__really_write__"):
            # ③：確認這一段真的落庫——用同一顆 legacy token 打真的批次寫入 API
            resp = page.context.request.post(
                f"{base}/api/workouts/batch",
                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
                data=json.dumps(body["pending_write"]["arguments"]),
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "已寫入。", "result": resp.json()}),
            )
            return
        route.fulfill(
            status=status_code, content_type="application/json", body=json.dumps(payload)
        )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport=PHONE, timezone_id="Asia/Taipei")
            page = context.new_page()
            page.route(f"{base}/api/chat/", chat_stub)

            page.goto(base, wait_until="networkidle")
            setup_and_home(page)
            wait_home(page)

            # ① 進得去的對話畫面：底部導覽 → 輸入一句話 → 顯示助手回覆
            open_chat(page)
            check(page.locator(".screen.chat-screen").count() == 1, "① 底部導覽進得去對話畫面")
            scripted.append((200, {"reply": "你上週練了 3 次。"}))
            say(page, "我上週練幾次")
            log_text = page.get_by_test_id("chat-log").inner_text()
            check("我上週練幾次" in log_text and "你上週練了 3 次。" in log_text,
                  "① 一句話問答顯示使用者訊息與助手回覆")

            # ② 寫入類指令先顯示 dry-run 摘要卡；按取消不送第二次請求
            scripted.append((200, {
                "reply": "幫你記這三組。",
                "pending_write": {"tool": "log_workout", "arguments": write_args},
                "dry_run": {
                    "will_create_count": 3, "will_skip_count": 1, "will_conflict_count": 0,
                    "preview": [
                        {"index": i, "exercise": "深蹲", "weight_kg": 60, "reps": 5,
                         "duration_seconds": None, "disposition": "create"}
                        for i in range(6)  # 給 6 筆，畫面只該顯示前 5 筆
                    ],
                },
            }))
            say(page, "深蹲 60 公斤 5 下三組")
            card = page.get_by_test_id("chat-dryrun")
            check(card.count() == 1, "② 寫入類指令先顯示 dry-run 摘要卡")
            card_text = card.inner_text()
            check("將新增 3" in card_text and "將略過 1" in card_text and "將衝突 0" in card_text,
                  "② 摘要卡列出將新增／將略過／將衝突筆數")
            check(page.locator(".chat-preview-row").count() == 5, "② 預覽最多 5 筆")
            check(card.get_by_role("button", name="確認寫入").count() == 1
                  and card.get_by_role("button", name="取消").count() == 1,
                  "② 摘要卡有確認寫入與取消")

            calls_before_cancel = len(chat_calls)
            page.get_by_test_id("chat-cancel").click()
            page.wait_for_timeout(400)
            check(len(chat_calls) == calls_before_cancel, "② 按取消不送第二次請求")
            check(page.get_by_test_id("chat-dryrun").count() == 0, "② 按取消後摘要卡收起")
            listed = page.context.request.get(
                f"{base}/api/workouts?start_date={TODAY}&end_date={TODAY}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            check(listed.json() == [], "② 按取消後資料庫零變更")

            # ③ 確認後顯示寫入結果摘要，且真的寫進去了
            scripted.append((200, {
                "reply": "幫你記這三組。",
                "pending_write": {"tool": "log_workout", "arguments": write_args},
                "dry_run": {"will_create_count": 3, "will_skip_count": 0,
                            "will_conflict_count": 0, "preview": []},
            }))
            say(page, "深蹲 60 公斤 5 下三組")
            scripted.append((200, {"__really_write__": True}))
            page.get_by_test_id("chat-confirm").click()
            page.wait_for_timeout(900)
            summary = page.get_by_test_id("chat-log").inner_text()
            check("3 組" in summary, "③ 結果摘要顯示組數")
            check("900" in summary, "③ 結果摘要顯示噸位 kg（3×60×5）")
            # 並列不相加：噸位與秒數各自標單位，畫面上不得出現把兩者加起來的數字
            check("噸位 900 kg" in summary and "900 秒" not in summary,
                  "③ 噸位與秒數並列不相加")
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(600)
            page.locator(".bottom-nav").get_by_role("button", name="日曆").click()
            page.wait_for_selector(".screen.calendar", timeout=10_000)
            page.wait_for_timeout(600)
            written = page.context.request.get(
                f"{base}/api/workouts?start_date={TODAY}&end_date={TODAY}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            ).json()
            check(len(written) == 1, "③ 確認後那筆真的寫進資料庫（日曆頁的資料來源）")
            today_cell = page.locator(f".cal-day[aria-label='{TODAY}']")
            cell_class = today_cell.first.get_attribute("class") if today_cell.count() else ""
            check("lv0" not in cell_class and "lv" in cell_class,
                  "③ 日曆頁今天那格因為這筆而上色")

            # ④ 設定頁可填入與清除自己的 key，且標示「使用自己的 key」
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(500)
            open_settings(page)
            check(page.get_by_test_id("llm-key-input").count() == 1, "④ 設定頁有 API key 欄位")
            page.get_by_test_id("llm-key-input").fill("sk-ant-e2e-key")
            page.get_by_test_id("llm-key-save").click()
            page.wait_for_timeout(300)
            check("使用自己的 key" in page.get_by_test_id("llm-key-state").inner_text(),
                  "④ 已填時標示「使用自己的 key」")
            stored = page.evaluate("() => localStorage.getItem('liftlog.llm_key')")
            check(stored == "sk-ant-e2e-key", "④ key 存 localStorage")
            # ④ 夾帶給 server 的是 header，不是同步資料
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(500)
            open_chat(page)
            scripted.append((200, {"reply": "好。"}))
            say(page, "哈囉")
            sent = chat_calls[-1]
            check(sent["headers"].get("x-llm-api-key") == "sk-ant-e2e-key",
                  "④ 自填 key 以 header 夾帶給 server")
            check("sk-ant-e2e-key" not in json.dumps(sent["body"]),
                  "④ key 不進請求 body（不隨資料上傳）")
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(400)
            open_settings(page)
            page.get_by_test_id("llm-key-clear").click()
            page.wait_for_timeout(300)
            check(page.evaluate("() => localStorage.getItem('liftlog.llm_key')") is None,
                  "④ 清除後 localStorage 不留 key")

            # ⑤ llm_key_missing：畫面指出去哪裡設定，不是空白或無限轉圈
            page.get_by_role("button", name="回首頁").first.click()
            page.wait_for_timeout(500)
            open_chat(page)
            scripted.append((400, {"error": "llm_key_missing"}))
            say(page, "我上週練幾次")
            missing = page.get_by_test_id("chat-error")
            check(missing.count() == 1, "⑤ 缺 key 時顯示錯誤訊息")
            missing_text = missing.inner_text()
            check("設定" in missing_text and "key" in missing_text.lower(),
                  "⑤ 訊息指出去設定頁填 key")
            check(page.locator(".chat-busy").count() == 0, "⑤ 不是無限轉圈")

            # ⑥ 上游錯誤：可讀訊息，不顯示原始碼或 key
            for code, expect in (
                ("llm_unauthorized", "無效"),
                ("llm_rate_limited", "額度"),
                ("llm_timeout", "逾時"),
            ):
                scripted.append((502, {"error": code}))
                say(page, "我上週練幾次")
                text = page.get_by_test_id("chat-error").inner_text()
                check(expect in text and code not in text,
                      f"⑥ {code} 顯示可讀訊息且不露原始錯誤碼")
            check("sk-ant" not in page.content(), "⑥ 畫面任何地方都不出現 key")

            browser.close()
    finally:
        server.kill()

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    for label in failed:
        print(f"  FAIL {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
