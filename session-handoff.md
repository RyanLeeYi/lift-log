# session handoff

最後更新：2026-08-13（第二場：D15 方向定案 + E1 重簽）。目前 **133/153 passing，20 failing**。
下一條為 **F138**，尚未開始；`.harness/current_feature` 應在開始 F138 時才切換。

## ⚠ 2026-08-13 方向定案（D15；本場未寫任何程式碼，只有決策與規格）

**目標＝作品集優先，公開 repo 但不經營。** 完整決策在 vault
`projects/2026-07-健身紀錄系統/DECISIONS.md` 的 **D15**。
**D14 已被 D15 更正，不要照 D14 行動**——它的兩個前提查證後不成立。

定位句：**「唯一不用把資料交給任何雲，就能讓 AI 讀寫的健身紀錄器」**。
差異在 *self-host + **可寫入** MCP 的組合*，不是「有 MCP」：

- 健身 MCP 已有 `chrisdoc/hevy-mcp`、AthleteData、Shape、Arvo，**全部依附別人的雲**
- 開源那派沒人做 MCP：wger 有 REST API 但無 MCP；`LiamMorrow/LiftLog` 純本機無 server，掛不了
- **撞名已查證**：`LiamMorrow/LiftLog`（AGPL、455★）定位重疊八成。**決定不換名**——作品集靠貼連結
- 護城河是**時間差不是技術**（wger 隨時可補 MCP）
- **RAG 明確不用**：結構化資料走 SQL 聚合＋tool calling；自由描述量級太小，FTS5 即可

### 本場已完成（feature_list.json 已改，不要重做）

1. **E1 envelope 重簽**（`signed_off: 2026-08-13`）：outcome 改作品集導向；constraints 加
   「所有 agent 寫入路徑共用同一組 tools 與護欄，不得開第二條」與「不商用不投廣告」；
   non_goals 加 RAG／經營社群／live demo 站與 APK 公開分發
2. **F145 縮範圍重簽**：衝突情境以 Android ↔ Web 為準；雙 Android takeover 與 recovery 降 backlog
3. **F149 新範圍重簽**：加 `docker compose up` 乾淨機器實測、MIT LICENSE、雙語 README；
   移除 20 帳號 quota 與備份／restore drill（降 `docs/operations.md`）
4. **新開 F150–F153**（批次寫入／冪等鍵／dry-run／app 內建對話）
5. **evidence 歸檔**：133 條 passing 的 evidence 移到 `.harness/evidence/F<id>.md`，
   `feature_list.json` 只留 `archived -> ` 指標，525KB → 333KB

### 發布門檻 20 條，執行順序（不要自行改順序）

1. **F138** — cp950 UnicodeEncodeError。先修，否則污染後面每一條的驗收證據
2. **F150 → F151 → F152** — 護欄，F153 讀寫對等的共用前置
3. **F145 → F146 → F147 → F148 → F149**
4. **F153** — app 內建對話
5. 其餘 10 條舊債：F86–F89、F95、F104、F105、F124、F128、F136

⚠ **沒有煞車**：Ryan 明確選擇不設時間上限、不設範圍凍結。唯一的收斂機制是這 20 條清單本身——
**不得再往門檻加條目**，新想到的一律標 failing 但排在 20 條之後。

### 交付物

GitHub repo（MIT、英文 `README.md` ＋ `README.zh-TW.md`）＋ **90 秒影片**：
手機記一場 → Claude 查詢 → Claude 口述寫入 → 切內建對話做同一件事 → 結尾架構圖標
「同一組 MCP tools」。不做 live demo 站、不做 APK 公開分發。

## F144 收官

- Android domain mutation 與 outbox 維持同 transaction；sync client 先 push 後 pull，支援 mutation response-loss 重送、transactional cursor apply、5 秒起跳的 exponential backoff＋jitter（上限 15 分鐘）。
- 啟動、前景、網路恢復、JobScheduler 背景與設定頁「立即同步」都接到同一 native runner；UI 顯示已同步／待同步／離線／錯誤。
- 新裝置 `bootstrapComplete=false` 時先停在 bootstrap gate，完整 pull transaction commit 後才開主要 UI，不顯示半份資料。
- v2→v3 migration 會 backfill 全部既有 domain rows；date/key natural-key pull 可安全 reconcile；空 outbox 的 pull-only failure 以 `sync_state` 保存 retry 次數與時間。
- Claude cross-model review 的唯一 HIGH（一般 RuntimeException 未保存 error/backoff）已修；targeted re-review **0 findings／integrity valid**。

## 這場完成

- F143 的 generic sync store 已完成 mutation receipt、version/tombstone、per-user `server_seq`、cursor pull 與 sequence regression 防護；共用 JSON fixtures 同時驗 server schema 與 Android JVM contract。
- Codex review 修正 concurrent mutation lost update，以及 chunked request、`Content-Length` 與 CORS 邊界；每 user SQLite 寫入採 `BEGIN IMMEDIATE` single-writer，control DB 保存 `server_seq` high-water。
- generic store 尚未接入既有 REST／MCP domain tables，這是明確 defer：REST 由 F146、MCP 由 F147 接入；sequence reset／backup restore operations 留給 F149。

## F144 驗證證據

- Claude canonical acceptance verifier：frozen acceptance **8/8 pass**、integrity **true**，允許改 passing。
- `./init.sh` 通過；backend **338 passed**；ruff clean。
- Android JVM/Robolectric **27 tests** 全綠；JS native-sync **2/2**；Playwright F144 bootstrap gate＋manual sync UI pass。
- v151 release APK 已建置並放 `G:\我的雲端硬碟\lift-log-apk\lift-log-v151-F144.apk`（SHA-256 `E32874BC0EF8AE9E4AB2660542CC5B89E6241812F2B23D2FF3ECAD0EF6F35C6C`）；E1 尚未全通過，不發布正式站或正式 APK metadata。

## 下一個 session 最短入口

1. 讀本檔、F145 frozen acceptance 與 PRD；確認 `git status`。
2. 開始實作時才把 `.harness/current_feature` 切為 F145；先以兩裝置 contract／instrumentation tests 固定 conflict inbox、takeover 與 recovery workout 行為。
3. 不要提前把 generic sync store 接入既有 REST／MCP domain tables；F146／F147／F149 的 deferred boundary不變。

## 工作區注意

- `CLAUDE.md` 是使用者既有未提交變更；絕對不要 stage、restore 或覆寫。
- F144 已通過驗收但 **E1 不得提前發布**：正式 Web／正式 APK metadata 均未發布；repo assets 與 Drive 測試 APK為 **v151**，完整 E1 release DoD 仍留到 F149。
