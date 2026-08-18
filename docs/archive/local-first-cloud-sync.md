---
updated: 2026-08-09
feature: "E1 / F139–F149"
signed_off: 2026-08-09
---

# Local-first 多帳號雲端同步 — PRD

## 背景與目標

lift-log 現況是刻意的單人系統：Android App 與 Web 的完整資料都寫入家機 FastAPI 的單一 SQLite，App 只以 IndexedDB、localStorage 與原生 SharedPreferences 保存待補送資料。全站共用一顆 Bearer token，資料表沒有使用者概念，APK 也固定指向 Ryan 的正式站，因此不能安全分享。

本功能要把 lift-log 改為可讓任何 Google 帳號註冊的正式多使用者產品。Android App 採 Local-first：所有日常紀錄先以本地 transaction 成功為完成，不依賴網路；雲端負責多裝置同步、備份、Web 與每位使用者自己的 MCP。後端仍由家機＋Cloudflare Tunnel 提供，雲端資料可被後端解讀，不採端對端加密。

這是一個完整發布 envelope。雖然實作會拆成多個可驗證 slice，但任何 slice 單獨完成都不算可對外發布；只有本 PRD 全部需求通過才可發布正式版。

## 非目標（本次不做）

- 不做 iOS App。
- 不做 Web 離線完整使用；Web 必須連線，登入後直接使用雲端資料。
- 不做端對端加密；否則雲端 MCP 無法直接查詢資料。
- 不做社群、公開排行榜、共同課表、教練查看、即時多人協作或 AI 教練建議。
- 不做付費、訂閱或商店內購。
- 不搬到 VPS、managed database 或第三方 SaaS backend；後端維持家機＋Cloudflare Tunnel。
- 不允許匿名帳號或自行設定密碼；身分只採 Google Sign-In。
- 不允許同一場進行中 workout 被兩台裝置同時寫入；以裝置擁有權與明確接管處理。
- 不把既有資料表全面改成共用多租戶表；雲端採 control DB＋每使用者獨立 data DB。

## 需求與驗收標準

### 一般使用者

#### R1：作為新使用者，我想用 Google 帳號登入，以便立即建立自己的隔離資料空間

- Given 使用者持有有效且 audience、issuer、expiry、nonce 都符合設定，且 `email_verified=true` 的 Google ID token。
- When Android 或 Web 第一次送出登入請求。
- Then 後端以 Google `sub` 建立一個內部 UUID user、獨立 data DB 與第一台 device，回傳短效 access token 與可輪替 refresh token；不得以 email 作為主鍵或資料庫檔名。
- Given 同一 Google `sub` 再次登入。
- When 登入請求成功。
- Then 必須回到同一 user，不得建立第二份帳號或資料庫。
- Given token 無效、過期、audience 不符、nonce 不符或簽章驗證失敗。
- When 送出登入請求。
- Then 回 401，且不得建立 user、device、session 或 data DB。
- Any Google account 可註冊；不需要邀請名單。
- Android access token 有效 15 分鐘；rotating refresh token 閒置 30 天或簽發後 90 天失效，以先到者為準。

#### R2：作為 Android 使用者，我想在完全離線時使用全部核心紀錄功能，以便家機或網路中斷也不影響訓練

- Given 使用者至少成功登入過一次，且本機帳號尚未登出或刪除。
- When 家機關機、Tunnel 不通、token 已過期但無法 refresh，或手機進入飛航模式。
- Then Android 仍可建立／結束 workout、記錄／編輯／軟刪 set、管理課表、體重體脂、每日狀態、排程與設定，並可查看 heatmap、歷史、PR 與既有資料。
- Then 每次寫入必須在同一個本地 SQLite transaction 中同時更新 domain row 與 sync outbox；只有 transaction commit 成功才向使用者顯示已記錄。
- Then UI 顯示「離線」與待同步筆數，不得把未同步資料顯示成已同步，也不得因 API 失敗回滾已完成的本地紀錄。
- Given App 被系統回收、裝置重開或離線數週。
- When App 再次打開。
- Then 本地資料、待同步 mutation、衝突與進行中 workout 均仍存在。

#### R3：作為使用者，我想讓不同裝置取得相同資料，以便換機或在多台裝置查看紀錄

- Given 一台裝置有尚未同步的 mutation。
- When App 啟動／回前景、網路恢復、使用者按「立即同步」，或 OS 允許背景工作。
- Then client 先 push、後 pull；每批最多 500 mutations 或 1 MiB，超出時分頁處理。
- Then server 以 `mutation_id` 冪等：相同 mutation 重送只回傳第一次結果，不重複建立資料或增加版本。
- Then 每筆接受的 mutation 以單調遞增 server sequence 寫入 change log；client 以 cursor 分頁拉取，重複 pull 不得重複套用。
- Then local row 只有在 server 明確接受後才清除 dirty/outbox 狀態。
- Given sync 在任一批次中斷。
- When 下次重試。
- Then 從最後已確認的 mutation 與 cursor 繼續，不重送已確認資料、不漏資料。
- 線上且 server 健康時，本地 mutation 應在 5 秒內開始同步；暫時失敗採指數退避加 jitter，最大間隔 15 分鐘，另提供手動同步。
- Given 新裝置第一次登入且雲端已有資料。
- When local DB 尚未建立。
- Then client 以 cursor 0 分頁拉取完整 snapshot/change stream，全部 transaction commit 後才開放主要 UI；中途失敗保留可重試的 bootstrap 狀態，不顯示半份資料。

#### R4：作為多裝置使用者，我想安全處理同一筆資料的並行修改，以便任何一方的修改都不會靜默消失

- 所有可同步 entity 都有 immutable `sync_id` UUID、integer `version`、`updated_at` 與 nullable tombstone。
- 新增不同 `sync_id` 的 workout／set／metric／status／template 自動合併，不互相覆蓋。
- 編輯或刪除既有 entity 必須帶 `base_version`。若等於 server version，server 接受並將 version 加一；不相等則回 conflict，附 server 版本與 client mutation。
- Conflict 不得自動 last-write-wins。App 將它保存在本地 conflict inbox，顯示雙方欄位，由使用者選擇「保留本機」或「採用雲端」；解決動作本身是新的 versioned mutation。
- 刪除以 tombstone 同步；舊裝置拉到 tombstone 後刪除／隱藏本地 row，不得重新上傳使資料復活。
- 同一場進行中 workout 有 `owner_device_id` 與 lease generation。只有 owner 可新增或修改該 workout 的 set；其他裝置只讀並顯示「由另一台裝置進行中」。
- 接管必須在線完成並增加 generation。舊 owner 離線期間產生、之後因 generation 過期被拒絕的 set 必須留在 conflict inbox，可移到新的 recovery workout，不得丟棄。

#### R5：作為 Web 使用者，我想登入後使用同一份雲端資料，以便在電腦查看與管理紀錄

- Web 使用同一個 Google Sign-In 與 user data DB。
- Web 保留現有核心功能與畫面，但所有 API 都由 server session 解析 user，不接受 client 傳入任意 user ID。
- Web 不提供離線寫入保證；server 不可用時顯示明確離線／服務不可用狀態，不得顯示空資料冒充真實結果。
- Web 建立的 mutation 與 MCP 建立的 mutation 都必須進同一 change log，Android 下次 sync 能取得。
- Web 使用 Secure、HttpOnly、SameSite cookie；所有狀態變更請求需要 CSRF 防護。

#### R6：作為 AI connector 使用者，我想建立自己的 MCP token，以便 AI 只能存取我的資料

- 每位 user 可建立、列出描述、停用多顆 MCP token；token 只在建立當下顯示完整值，server 只保存 hash。
- MCP 驗證 token 後只能開啟該 user 的 data DB；不得接受 tool 參數指定其他 user 或 DB。
- MCP／REST／Web 的 domain write 都重用既有 service 邏輯並寫入同一 change log，不得存在繞過同步版本的第二條 server 寫入路徑。
- 停用 token 後，新請求立即回 401；既有 user access／refresh session 不受影響。

#### R7：作為使用者，我想匯出與刪除自己的資料，以便不被服務綁定

- 已登入使用者可匯出完整、版本化 JSON，內容涵蓋所有 domain 資料與必要關聯，但不含 access token、refresh token、MCP token hash、Google token 或 server 內部路徑。
- 匯出需重新驗證近期 Google 身分，且每帳號每小時最多 3 次。
- 刪除帳號需近期重新驗證與二次確認；成功後立即撤銷全部 session、device 與 MCP token，刪除 active user DB，Android 清除本地 DB、outbox、conflict 與憑證。
- Server 備份中的殘留最長 30 天後消失；已刪帳號不得從一般啟動或自動 restore 流程恢復。
- 登出會撤銷當前 device refresh token並清除本地資料。若仍有 pending mutation 或 unresolved conflict，預設阻擋登出，直到同步／解決、匯出或使用者明確確認捨棄。

#### R8：作為既有 Ryan 帳號，我想把目前正式資料無損搬入新架構，以便升級後歷史與功能完全保留

- 遷移前需產生可驗證備份並記錄 row counts。
- Ryan 第一次以指定 Google `sub` 登入後，管理命令將現有正式 DB 綁定為該 user 的 data DB，替需要同步的既有 entity 補 `sync_id`、version 與 change-log baseline。
- 遷移不得要求在文件、log 或指令歷史中保存 Ryan 的 email、Google token 或實際 `sub`；識別值只從環境變數或互動式安全輸入取得。
- 遷移後逐表 row count、關聯、軟刪資料、PR／heatmap／課表／體重與 MCP 查詢必須與遷移前一致。
- 舊單一 Bearer token 在新正式版切換後作廢，不得繼續授權 API 或 MCP。

### 管理者／營運者

#### R9：作為家機營運者，我想讓公開註冊不拖垮服務或洩漏資料，以便可安全提供給他人

- Cloudflare Tunnel 是唯一公開入口；資料服務只監聽 loopback／受控內網，不直接暴露資料庫埠。
- Control DB 只保存 user、device、session、hashed MCP token、quota 與狀態；每位 user 的 domain 資料位於隨機 UUID 命名的獨立 SQLite，不使用 email／Google sub 作檔名。
- Data DB 啟用 foreign keys、WAL 與 busy timeout；server session 只能由已驗證 user context 解析到一個 canonical path，任何 request 欄位都不能指定路徑。
- 公開 auth endpoint 每 IP 每分鐘最多 10 次；sync／domain endpoint 每 user＋device 每分鐘最多 120 次；export 每 user 每小時最多 3 次；account delete 每 user 每小時最多 3 次。超限回 429＋`Retry-After`，不丟棄 client outbox。
- 每帳號 active data DB 上限 100 MiB、每天最多接受 20,000 筆 mutations；超限回 stable error code 並保留本地資料，管理者可停用濫用帳號。Tombstone、receipt 與 change-log 維護不得讓 active DB 永久只增不減；壓縮／保留規則需有測試。
- Log、metrics 與錯誤不得包含 token、Google ID token、email、訓練 payload、體重、MCP 參數或 user DB 絕對路徑。
- 每日建立 control DB 與 active user DB 的加密備份，保存 7 份每日＋4 份每週版本，目的地不能與 active DB 在同一顆實體磁碟；每次正式發布前完成一次隔離 restore drill。
- 家機離線時，既有 Android client 照常使用；Web、登入、新裝置 bootstrap、sync 與 MCP 顯示服務不可用。恢復後不得需要手動修資料才能續傳。

## 介面契約

### 整體資料流

```text
Android UI / Native Overlay
        │
        ▼
LocalStore bridge ──transaction──> local SQLite
        │                              ├─ domain tables
        │                              ├─ sync_outbox
        │                              ├─ sync_state
        │                              └─ sync_conflicts
        ▼
Sync client ──Google session──> FastAPI /sync
                                   ├─ control.db
                                   └─ users/<internal-user-uuid>.db
                                        ├─ domain tables
                                        ├─ mutation_receipts
                                        └─ sync_changes

Web ───────────────> FastAPI domain API ─┘
MCP token ─────────> user-scoped MCP ────┘
```

### Auth API

```text
POST /api/auth/google       { id_token, nonce, device_id, device_name, client: "android | web" }
                            -> Android: { access_token, expires_in, refresh_token, user, device }
                            -> Web: Set-Cookie session + { user, device }
POST /api/auth/refresh      { refresh_token, device_id }
                            -> rotated token pair
POST /api/auth/logout       current device session -> 204
```

Refresh token 每次使用即輪替；重用已輪替 token 視為 session compromise，撤銷該 token family。

### Sync API

```text
POST /api/sync/push
{
  "device_id": "uuid",
  "mutations": [
    {
      "mutation_id": "uuid",
      "entity_type": "set",
      "entity_id": "uuid",
      "operation": "upsert | delete | takeover",
      "base_version": 0,
      "lease_generation": 1,
      "payload": {}
    }
  ]
}
-> {
  "accepted": [{ "mutation_id": "uuid", "version": 1, "server_seq": 42 }],
  "conflicts": [{ "mutation_id": "uuid", "reason": "version_mismatch", "server": {} }]
}

GET /api/sync/pull?cursor=41&limit=1000
-> { "changes": [...], "next_cursor": 99, "has_more": false }
```

### Domain entity 共用同步欄位

```json
{
  "sync_id": "uuid",
  "version": 3,
  "updated_at": "server-assigned ISO-8601 UTC",
  "deleted_at": null
}
```

Device clock 只供顯示與原始事件時間參考，不用來判定哪次編輯勝出。

## 介面示意

```text
設定
┌──────────────────────────────────┐
│ Google 帳號  Ryan                │
│ 同步狀態     已同步 · 12 秒前     │
│ 裝置         Galaxy Note 10+（本機）│
│              Pixel 9（可查看）    │
│ [立即同步] [管理裝置]             │
│                                  │
│ MCP 存取     2 顆有效 token       │
│ [建立 token] [管理 token]         │
│                                  │
│ [匯出資料]   [登出]               │
│ [刪除帳號與所有資料]              │
└──────────────────────────────────┘

衝突收件匣（只有有衝突時顯示）
┌──────────────────────────────────┐
│ 槓鈴深蹲 · 2026/08/09 · 第 3 組   │
│ 本機：100 kg × 5                  │
│ 雲端：100 kg × 4                  │
│ [保留本機] [採用雲端]             │
└──────────────────────────────────┘
```

## 具體範例（輸入 → 輸出）

### 範例 1：離線新增一組後重送

1. Android transaction 寫入 set `S1` 與 mutation `M1`；畫面立即顯示該組與「待同步 1」。
2. 第一次 push 的 HTTP response 遺失，但 server 已接受 `M1`。
3. App 重送同一 `M1`；server 從 mutation receipt 回傳相同 `version=1/server_seq=42`，不新增第二組。
4. App 清除 `M1` outbox，顯示「已同步」。

### 範例 2：兩台裝置編輯同一筆體重

1. A、B 都持有 body metric `version=3`。
2. A 送 80.0 kg、base_version=3，server 接受為 version=4。
3. B 送 79.8 kg、base_version=3，server 回 `version_mismatch` 與 server 的 80.0 kg。
4. B 顯示兩個值；使用者選 79.8 kg 後，以 base_version=4 送新的 mutation，server 接受為 version=5。

### 範例 3：舊 owner 在接管後才恢復上線

1. Device A 擁有 workout W、generation=1，離線記錄兩組。
2. Device B 在線明確接管，server 將 generation 改為 2。
3. A 恢復上線，兩組因 stale generation 進 conflict inbox，資料仍在本機。
4. 使用者選「移到新訓練」，App 建立 recovery workout 並以新的 mutation 同步兩組。

## 邊界情況與錯誤行為

- Google login 成功但建立 user DB 失敗：整體交易失敗回 503，不留下半個 user/session；重試可安全重做。
- Google JWKS／驗證服務暫時不可用：仍可使用尚未過期的安全快取 key；無可驗證 key 時新登入回 503，不得略過簽章。既有本機使用與已核發 session 不受影響。
- Refresh token 被竊用或重放：撤銷 token family，該 device 需重新 Google Sign-In；其他 device session 不自動撤銷。
- App local DB migration 失敗：禁止開啟寫入 UI，保留原 DB 與錯誤前備份，提供匯出診斷；不得重建空 DB 冒充成功。
- Pull 收到未知 entity type 或不支援 schema version：停止套用該批並保留 cursor，提示需要更新 App。
- 單筆 mutation 驗證失敗：只拒絕該筆並回 stable error code；同批其他互不相依 mutation可繼續，依賴該筆的 mutation 保留待處理。
- Server 磁碟滿、DB locked、備份失敗：回 503／告警，不回 200；client 保留 outbox。
- 使用者在多裝置刪除同一筆：第一次產生 tombstone，後續相同 delete 冪等成功。
- 使用者先刪除、另一裝置再編輯舊版本：回 conflict/tombstoned，不得復活。
- Google 帳號被停用或管理者停權：既有 App 保留本地只讀匯出能力，但 server 拒絕登入、sync、Web 與 MCP；不得刪除本地資料。
- Home server 從備份還原到較舊 cursor：啟動檢查若偵測 sequence regression 必須停止 sync endpoint，等待營運者處置，不讓 client 誤認回滾為新狀態。

## 技術約束（本專案特有）

- Android UI 維持 Capacitor＋原生 JS/CSS，不改寫成 Compose，不加入前端 framework。
- Android 本地資料使用單一原生 SQLite；由薄 Capacitor LocalStore bridge 給 WebView 使用，原生浮動視窗與 WebView 必須寫同一個 store，不得再新增第四份 queue。
- 優先使用 Android `SQLiteOpenHelper` 與既有 Java；只有加密或 migration 能力有可驗證缺口時才評估額外 database dependency。
- Android manifest／backup rules 必須排除 local data DB、outbox、conflict 與 auth secrets 的 Auto Backup；換機資料只從已驗證雲端 bootstrap，避免舊 DB 在不同帳號或 schema 下被系統還原。
- 雲端保留 FastAPI、SQLAlchemy 與 SQLite。採一顆 control DB＋每 user 一顆 data DB，domain services 不接受 user ID/path 參數，由已驗證 request context 提供 session。
- 所有 server domain mutation 只能經 `app/services/`；REST、Web、MCP、sync 共用 service 與 change-log hook。
- Control DB 與 data DB migration 必須有 schema version、可重跑、失敗中止與備份還原路徑。
- Client 與 server 以共用 JSON fixture 驗證同步契約；不得靠兩份各自手寫但沒有 contract test 的規格。
- Access token 短效；Android refresh token 存 Android Keystore-backed encrypted preferences，Web session 存 Secure HttpOnly cookie；任何 token 不寫 log 或 data DB。
- Any-Google-account 公開註冊必須搭配 rate limit、quota、停權與備份，不得只完成登入畫面就上線。

## 分階段任務清單

> 以下是實作依賴切分，不是產品發布階段；全部完成才可發布。

- [ ] F139：Android LocalStore 基礎——本地 schema、migration、domain tables、sync metadata、outbox、conflict 與既有 seed。
- [ ] F140：Android 完整本地讀寫——把核心紀錄、課表、體重、狀態、統計與 native overlay 接到同一 local store，離線全功能。
- [ ] F141：Google Sign-In 與 session——control DB、user/device、token rotation、Android/Web session 與公開註冊防濫用。
- [ ] F142：雲端每使用者 data DB 隔離——安全 session routing、DB lifecycle、quota、既有 domain API 多帳號化。
- [ ] F143：同步 server 協定——mutation receipt、version、tombstone、change sequence、push/pull 分頁與錯誤契約。
- [ ] F144：Android sync client——transactional outbox、push/pull、cursor、retry、背景／手動觸發與同步狀態 UI。
- [ ] F145：多裝置與衝突——workout owner/takeover、version conflict inbox、解決操作與 recovery workout。
- [ ] F146：Web 多帳號化——Google session、CSRF、user-scoped domain API 與服務不可用狀態。
- [ ] F147：User-scoped MCP——個人 token lifecycle、hash storage、user DB routing 與所有寫入進 change log。
- [ ] F148：資料生命週期——完整 JSON export、登出安全、帳號刪除、device/session/token 撤銷與 backup retention。
- [ ] F149：遷移、營運與正式發布——Ryan 正式資料 migration、加密備份/restore drill、rate-limit/load/isolation/security 測試、Android/Web/MCP 全路徑驗收與正式版發布。

## 完成定義（必過的指令）

- `uv run pytest` 全過，涵蓋 auth、per-user isolation、sync idempotency、version conflicts、tombstones、MCP scope、export/delete 與既有 domain 回歸。
- `uv run ruff check .` 無錯誤。
- Android JVM unit tests 與 instrumentation tests 全過，涵蓋 local migration、transaction rollback、process death、離線數週、outbox retry、兩裝置 conflict/takeover。
- Playwright 驗 Web Google session stub、跨帳號隔離、CSRF、服務離線、MCP mutation 後 Android pull。
- Contract tests 以同一組 JSON fixtures 驗 Android client 與 FastAPI server。
- 隔離環境完成舊正式 DB migration 前後 row count／domain result 對照。
- 以至少 20 個帳號、每帳號 2 台裝置的測資驗 sync 分頁、rate limit 與資料隔離；任何 cross-user read/write 都是 release blocker。
- 完成一次 active DB → encrypted backup → 空環境 restore → client catch-up 演練。
- 建置 release-signed APK，實機完成：全新 Google 登入、離線完整訓練、另一裝置接管與衝突、換機還原、MCP 查寫、匯出、刪除帳號。
- 現有 passing feature 的受影響驗收依 prerequisites 重跑；正式 Web、APK、MCP 與 schema 版本一致後才可發布。

## 開放問題

- 無。產品邊界已由 Ryan 於 2026-08-09 拍板：任何 Google 帳號皆可註冊；同筆衝突人工解決、同一進行中 workout 單裝置 owner＋接管；Android local-first、Web online-only；家機＋Tunnel；server 可讀資料供 MCP；刪帳前可匯出、刪除後雲端與裝置清除。
