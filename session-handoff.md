# session handoff

最後更新：2026-08-17。**145/158 passing、13 failing**。`.harness/current_feature` = F158。

## 接手第一件事

**先確認有沒有第二個 session 在動這個 repo。** 本輪出現過兩次症狀：派出去的 worker 拿到落後 3 個 commit 的基準點；驗收者中途看到 `feature_list.json` 憑空被改。後來確認是另一個流程committed 了 `f5c6274`、`6a81710`（`touches` 欄位補齊，內容無害）。兩邊並行會互相踩，動工前先看 `git log --oneline -5` 對得上不。

**F149 的阻塞已解除**（OAuth client ID 已設、遷移已跑、legacy token 已撤），但 F149 本身仍是 `failing`，剩餘項見下。

## 本輪完成

### F149 的阻塞鏈全部打通

1. **Google OAuth client ID 已設**（`.env` / `.env.dev`，`LIFTLOG_GOOGLE_CLIENT_ID`）。
   關鍵發現：**不必重出 APK**——Android 與 Web 都經 `/api/auth/config` 跟 server 拿 client id
   （`app/static/js/auth.js`），所以換這個值只要重啟服務。原計畫裡「重出 APK」那步是多餘的。
2. **真實資料遷移已執行**。Ryan 確認資料正確。
   - 結果：8 workouts／150 sets／40 exercises／3 templates／8 body_metrics／1 app_setting
   - 對帳：legacy 179 sets = 150 遷入 + 2 重複跳過 + 27 墓碑不遷
   - 回滾快照：`prod-data/users/backfill_backups/20260817T025419Z/68ea7b49-….snapshot.db`
   - 回滾指令：`uv run python scripts/migrate_legacy.py --rollback <snapshot> --email ian4567x@gmail.com`
3. **`LIFTLOG_TOKEN` 已撤**（`.env` 留註解版，拿掉 `#` 重啟即還原）。
   實測正式站：舊 token 401、空 bearer 401、Google 設定仍正常。

### 遷移腳本的真 bug（commit `d352647`）

`_migrate_sets` 只用 `client_uuid` 比對既有列，但 DB 的真正約束是
**partial unique index(workout, exercise, set_number) WHERE deleted_at IS NULL**。
同一天的兩場訓練會被自然鍵併成一場，兩場各自的「第 1 組」就在這裡撞，
遷移在 flush 時炸 IntegrityError 而不是產出可讀的衝突報表。已加複合鍵 fallback。
另依 Ryan 決定不搬軟刪列，用獨立的 `skipped_deleted` 計數（「因重複跳過」與「因是墓碑不搬」
是兩件事，混在一個數字裡就查不出來）。

### F156 refresh token 併發輪替（commit `cf1c451`，驗收 6/6，**已上線**）

Ryan 回報「手機 app 過一陣子會自己登出」的根因。refresh token 單次使用輪替 + 重播即判盜用
吊銷整個 family，但 Android 有**兩個互不知情的刷新者**共用同一顆 SecureStore token
（`NativeAuthSession.java` 背景同步、`auth.js::restoreNativeSession` webview），開 app 時同時
呈遞，慢的那個被當成盜用。加 60 秒重播寬限期；`used_at` 只寫第一次所以窗口不可被重播展延；
`revoked` 不因寬限復活。詳見 `docs/evidence/F156.md`。

### F157 web session 滑動到期（commit `3baf4ea`，驗收 6/6，**已上線**）

**驗收擋了兩輪，兩次都是真問題，值得記住：**

1. 第一輪：DB 的 `access_expires_at` 有滑動，但 cookie 的 Max-Age 只在登入當下設一次。
   瀏覽器到期就丟掉 cookie、之後不再送出——**滑動在真實瀏覽器裡從未生效，而測試是綠的**
   （只斷言 DB 欄位）。「DB 記錄了」不等於「客戶端知道了」。
2. 第二輪：修對層次但補錯粒度——cookie 續發**逐個呼叫點補**，補兩個漏第三個
   （`api/account.py::_current`）。驗收者：「往後只要再新增一個直接呼叫 `resolve_session`
   的路由，就會複製同一個洞。」

最終收斂成單一路徑：`app/api/deps.py::resolve_request_session()` 是唯一 session 解析入口，
只在 `request.state` 登記；`app/main.py::slide_web_session_cookie` middleware 統一寫進回應。
放 middleware 還順帶涵蓋錯誤回應——CSRF 403 / rate limit 429 拒絕的是「這一次請求」不是
「這個 session」，不該讓登入狀態開始倒數；401 走不到登記那段，所以不會續發。
詳見 `docs/evidence/F157.md`。

### F158 第一段：MCP token 到期與唯讀欄位（commit `ba4d565`）

`McpToken` 加 `expires_at`（預設 90 天，不再永久）與 `read_only`。到期與已撤銷走同一條 401，
分不出是哪一種。舊庫用 `ALTER TABLE` 補欄位（`create_all` 只建缺席的表，少了這段升級後
一查就 OperationalError）；預設值等於 F158 之前的行為，既有 token 不受影響。

**`read_only` 只存進去、還沒生效**——擋寫入工具是第二段。

## 尚未完成

### F158 剩兩段（`.harness/current_feature` 指這條）

- **第二段（授權邊界，建議留主 session 自己做）**：`read_only` 的 token 只能跑查詢類 MCP
  tools，寫入類一律拒絕並回可讀錯誤。動 `app/mcp.py`——`DomainTokenVerifier.verify_token`
  現在只回 user，要把 read_only 一起帶出來（`AccessToken` 的 scopes 是現成的位置）。
- **第三段（可委派）**：設定頁的 MCP token 管理 UI（列出／發新的／撤銷；明文只顯示一次）。
  API 早就齊了（`app/api/mcp_tokens.py`），純粹缺畫面。**動 `app/static/` 就要出 APK**。

### F149 剩餘

1. release-signed APK 全流程冒煙：真登入、完整離線訓練、衝突處理、換裝置、MCP、匯出、刪帳
2. Web/APK/MCP/schema 版本一致
3. 派獨立 review 與 `acceptance-verifier` 逐條驗收，才可改 passing

## 記帳（不阻塞，但別忘）

- app 內建自我更新（F67）按「立即更新」後沒有動作，server log 也沒有下載請求。
  **這是一條沒查完的線索**，可能只是「安裝未知應用」權限沒開
- `scripts/backfill_sync.py` 的快照目錄用秒級時間戳，同一秒重跑會撞 VACUUM INTO 目的檔已存在
- `docs/evidence/F146.md` 末段第 2 項仍未處理
- `G:\我的雲端硬碟\lift-log-apk` 未掛載，v154 尚未複製到 Google Drive
- **不要整份 `Read` `feature_list.json`**（334KB）。理由與挑欄位指令見 `CLAUDE.md` 工作規則 #1
- 正式站目前跑 `e8ff575`（F157）。前端版號仍是 v154——F156/F157 都只動後端，不需要新 APK
