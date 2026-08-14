# session handoff

最後更新：2026-08-14。現在 **141/155 passing、14 failing**。

## 下一步

1. **F148**（資料生命週期、匯出、登出與刪帳）。接著 F149 → F153 → F155 → 10 條舊債。
2. 兩件規格層級待 Ryan 裁決，寫在 `docs/evidence/F146.md` 末段：legacy 單一 token 路徑要不要收掉、
   Web 端 IndexedDB 離線佇列與 envelope 非目標的字面出入。兩者都不阻擋已通過的 acceptance。
3. `release/lift-log-v153.apk` 待複製到 Google Drive（`G:` 未掛載）。
4. F147 只動了 `app/mcp.py`／`app/api/`／`app/services/`／`app/control_models.py`，**未動
   `app/static/`**——不必為這條出新 APK。

## 本輪完成

- **F147 passing**：user-scoped MCP token（PRD R6、R9）。`app/control_models.McpToken`
  （uuid PK、hash-only）、`app/services/mcp_tokens.py`（create/list/revoke/resolve）、
  `app/api/mcp_tokens.py`（`/api/mcp-tokens/`，legacy scope 401）、`app/mcp.py` 的
  `DomainTokenVerifier` 同時接受 legacy token 與 user MCP token，八個 tool 共用
  `domain_session()` helper 依 `get_access_token().client_id` route 到該 user 的
  data DB（用完 `engine.dispose()`）。domain 寫入全部沿用既有
  `app/services/*`（已呼叫 `projection.record_write`），沒有新增第二條寫入路徑。
  `tests/test_mcp.py` 新增 7 條（建立/列出/撤銷＋DB 只存 hash、legacy 401、錯 token
  401、撤銷後立即 401、跨 user IDOR 讀寫隔離、撤銷別人 token 404、MCP 寫入進
  Android `/api/sync/pull` 的 change log）。詳見 `docs/evidence/F147.md`。
- **踩到的坑**：fastmcp 的 in-memory `Client(mcp_server)` transport **完全不走 `auth=`
  驗證層**（探針腳本證實 `get_access_token()` 恆回 `None`），所以既有 in-process 測試
  必須保持在 `control_session_factory is None` 時完全跳過 `get_access_token()` 呼叫；
  要驗證「user token 真的 route 到自己的 DB」得走真的 `/mcp/` HTTP 層——用
  `httpx.ASGITransport` + fastmcp `StreamableHttpTransport(httpx_client_factory=...)`
  + `app.router.lifespan_context(app)`（手動觸發 `mcp_app.lifespan`，否則
  `StreamableHTTPSessionManager` 的 task group 沒初始化會直接 500）做到全程 in-process、
  不開真連線埠的端對端測試。

- **F146 passing**（前一輪）：F154 補上 R5 change log 整合後重驗，全 gates 綠（ruff、pytest 373、
  `verify_f146` Playwright、JS auth 10/10、f48/f93/f101/f102 回歸）。獨立驗收 fresh context
  逐條 11 項全 pass ACCEPT，並自行查證無第三條繞過 change log 的寫入路徑、web 不碰 Android
  local store；驗收前後 `git status` 一致。
- prod **v153 / F146** APK 已出並驗過內含版號，放在 `release/lift-log-v153.apk`。
- **CLAUDE.md 第 6 條的 APK 路徑已修**：正確路徑是 `apk\prod\release\app-prod-release.apk`。
  舊路徑 `apk\release\app-release.apk` 是加 flavor 前的殭屍檔（2026-07-30 的 v95），
  不會被新 build 覆蓋，照舊路徑複製會出一顆「build 成功但內容是舊版」的 APK（本輪實際踩到）。

## 環境與邊界

- `acceptance-verifier` 走本機 agent（fresh context，同模型，**不是**跨模型獨立）；
  Codex 整條路徑已於 2026-08-14 移除，舊的 `gpt-5.6-sol` 說法作廢。
- Android JVM task：`:app:testDevDebugUnitTest`；本機 SDK：`C:\Users\user\AppData\Local\Android\Sdk`。
- 純後端驗收用 `C:\Users\user\.local\bin\uv.exe`；pytest summary 若被 cp950 吞掉，以 exit code 為準。
- E1 未全通過：不得部署正式站或正式 APK metadata。
- **F147 已由 `acceptance-verifier` 逐條驗收 6/6 ACCEPT**（2026-08-14，fresh context，
  另寫獨立驗證腳本查 control DB 與走完整多使用者 app，不只信既有測試斷言）；
  逐條證據補在 `docs/evidence/F147.md` 末段。
- 流程提醒：executor 這輪**自己就把 status 改成 passing**，驗收是事後補的。
  repo 規則 2 的順序是「驗收通過才改 passing」，下次派工單要把這句寫進限制。
