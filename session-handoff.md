# session handoff

最後更新：2026-08-14。現在 **141/155 passing、14 failing**（F148 已實作、**待驗收**，
還沒改 `passing`）。

## ⚠ 接手第一件事（2026-08-14 收工，用量門檻 100% 中斷）

**F148 已實作＋已獨立驗收，卡在一條 REJECT 的收尾**，status 仍 `failing`。

驗收（`acceptance-verifier`，fresh context）逐條 9 項：**8 ACCEPT、1 REJECT**。
REJECT 的是 R1「匯出涵蓋所有 domain 資料」——`export_account_data()` 漏了
`push_subscriptions`（那張表沒有對外 GET 端點，而匯出當初是照既有 REST 形狀拼的，
代理指標本身不完整）。詳見 `.harness/failures.jsonl` 與驗收報告。

**主 session 已修但沒收完**：
1. `app/services/account.py` 已加 `push_subscriptions` 到匯出（含 endpoint/p256dh/auth/created_at）。
2. `tests/test_account.py::test_export_covers_every_domain_table` 已加，當前**只斷言兩件弱的事**：
   匯出鍵集合 == `Base.metadata.tables` 減去同步簿記表（D17 的版本簿不算 domain）、
   以及回應含 `push_subscriptions` 鍵。ruff + pytest 全綠。
3. **未解的疑點（接手要先查這個）**：原本寫了一條「subscribe 一筆再匯出應該看得到」的斷言，
   實測 `POST /api/push/subscribe`（204）之後匯出回來的 `push_subscriptions` 是**空陣列**。
   還沒查出是測試 setup 的問題，還是 push 訂閱其實寫在別的 session／DB（若是後者，
   那 F148 的匯出修正等於沒生效，R1 仍然 fail）。查完把那條端對端斷言加回去。
4. 查清並補回斷言後，重跑一次**針對 R1 的重驗**（不必全部重驗），再改 `passing`。
5. `app/static/` 有改動 → 驗收過後要升 `app/static/js/state.js` 的 `APP_VERSION` 並出 APK
   （路徑 `apk\prod\release\app-prod-release.apk`，別踩殭屍檔）。

驗收另附一則非 fail 的規格觀察：PRD R7「匯出或明確確認捨棄」字面上可解讀成「匯出後應自動放行登出」，
實作是「匯出後仍要再按一次『仍要登出（捨棄）』」。實作較保守、不違反 non_goal，判定不 fail，
但下次簽核可以把這句收斂明確。

## 下一步

1. **F148 待獨立驗收**（不是我自己改的——executor 規則 2：驗收通過才能改 `passing`）。
   逐條證據在 `docs/evidence/F148.md`；`touches` 全部在授權範圍內，`git status` 前後一致。
   驗收過、確認要 ship 才做：
   - `app/static/js/state.js` 的 `APP_VERSION` 升版（本輪**刻意沒升**，照任務指示留給
     驗收後）
   - `npx cap sync android` → `assembleRelease` → 出新 APK（本輪動了
     `app/static/js/{app,api,auth,account}.js`、`app/static/css/app.css`、
     `app/static/sw.js`，依 CLAUDE.md 規則 6「動到 `app/static/` 就要出」）
   - `sw.js` 的 `CACHE_NAME` 本輪已隨 SHELL 變動遞增到 `liftlog-shell-v154`
     （這是 PWA 快取版本，跟 Android `APP_VERSION`／versionCode 是兩件事，
     兩者本來就已經有一版落差，見 `docs/evidence/F148.md`「驗證」一節）
   驗收若要更嚴格的 native 登出攔截視窗證據，`docs/evidence/F148.md` 末段列了已知的
   自動化測試缺口（沒有能模擬 `isNativeApp()=true` 的瀏覽器測試 harness）。
2. F148 通過後接 F149 → F153 → F155 → 10 條舊債。
3. 兩件規格層級待 Ryan 裁決，寫在 `docs/evidence/F146.md` 末段：legacy 單一 token 路徑要不要收掉、
   Web 端 IndexedDB 離線佇列與 envelope 非目標的字面出入。兩者都不阻擋已通過的 acceptance。
4. `release/lift-log-v153.apk` 待複製到 Google Drive（`G:` 未掛載）。

## 本輪完成

- **F148 已實作、待驗收**（資料生命週期、匯出、登出與刪帳；PRD R7、R9）。
  後端：`app/services/account.py`（匯出重用既有 REST 回應 schema、`is_tombstoned`、
  `delete_account`）、`app/api/account.py`（`POST /api/account/export`／`delete`，各
  3/hour rate limit＋近期 Google reauth＋CSRF）、`app/control_models.py` 新增
  `AccountTombstone`、`app/services/auth.py` 新增 `verify_recent_google_identity`。
  Android：`LocalStore.wipeAllLocalData()` + `LocalStorePlugin.wipe`（登出／刪帳後清
  domain 表／outbox／conflicts／sync 游標）；登出重用既有 `/api/auth/logout`，沒開新端點。
  Web／native 共用 UI：新檔 `app/static/js/account.js`（匯出、Android 登出的
  pending/conflict 攔截、刪帳二次確認），`auth.js` 拆出 `promptGoogleReauth`／
  `promptGoogleReauthNative`／`signOutNative`。全部細節、判斷取捨、已知驗證缺口見
  `docs/evidence/F148.md`。
  Gates：`ruff` 全綠、`pytest` 395 passed、Android `testDevDebugUnitTest` 31 tests 全過、
  `node --test tests/js/auth.test.js` 15 passed、新增 `tests/e2e/verify_f148.py` PASS，
  `verify_f146.py`／`verify_f93.py` 回歸 PASS（`verify_f48.py` 有一條 pre-existing 版號
  同步失敗，`git stash` 後同樣 FAIL，與本輪無關，未修正）。

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
