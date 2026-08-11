# session handoff

最後更新：2026-08-11。active feature：**F143**；E1（F139–F149）已簽核。F143 **passing**，目前 **132/149 passing**；本輪停在 F143 收官，下一步是 F144。

## 這場完成

- F143 的 generic sync store 已完成 mutation receipt、version/tombstone、per-user `server_seq`、cursor pull 與 sequence regression 防護；共用 JSON fixtures 同時驗 server schema 與 Android JVM contract。
- Codex review 修正 concurrent mutation lost update，以及 chunked request、`Content-Length` 與 CORS 邊界；每 user SQLite 寫入採 `BEGIN IMMEDIATE` single-writer，control DB 保存 `server_seq` high-water。
- generic store 尚未接入既有 REST／MCP domain tables，這是明確 defer：REST 由 F146、MCP 由 F147 接入；sequence reset／backup restore operations 留給 F149。

## 已有證據

- Codex fresh-context 主驗收：除 Android sandbox 標為 UNVERIFIED 外，其餘 frozen acceptance 全 PASS、integrity **VALID**；backend **338 passed**、ruff clean，unknown cursor 的 temp DB black-box 通過。
- targeted Codex fresh-context 以本機 Android SDK 補驗：Android/server 直接讀取同一實體 JSON fixtures，Gradle **BUILD SUCCESSFUL**、JUnit **2/2**、integrity **VALID**。

## 下一個 session 最短入口

1. 讀本檔、F144 frozen acceptance 與 PRD；確認 `git status`。
2. **動工時才**把 `.harness/current_feature` 從 F143 設為 F144。
3. F144 是 Android sync client：先 push 再 pull、cursor transactional apply、retry／背景／手動同步與 UI；不要提前把 generic sync store 接入既有 REST／MCP domain tables。

## 工作區注意

- `CLAUDE.md` 是使用者既有未提交變更；絕對不要 stage、restore 或覆寫。
- F143 已通過驗收但 **E1 不得提前發布**：正式 Web／正式 APK 均未發布，assets／APK 仍為 **v150**；完整 E1 release DoD 仍留到 F149。
