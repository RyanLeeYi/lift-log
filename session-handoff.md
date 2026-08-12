# session handoff

最後更新：2026-08-12。F144 **passing**；E1（F139–F149）已簽核，目前 **133/149 passing**。下一條為 **F145**，尚未開始；`.harness/current_feature` 應在開始 F145 時才切換。

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
