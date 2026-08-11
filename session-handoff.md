# session handoff

最後更新：2026-08-11。active feature：**F142**；E1（F139–F149）已簽核。F142 **passing**，目前 **131/149 passing**；本輪停在 F142 收官，下一步是 F143。

## 這場完成

- 所有既有 REST domain router 已改由已驗證 Android access token 或 Web cookie 解析 user，再開啟 `users/<internal UUID>.db`；client 傳入 user/path 不參與 routing，legacy token 只保留到 F149 cutover。
- 每 user data DB 啟用 foreign keys、WAL、5 秒 busy timeout 與 schema version；啟動與再次登入會冪等 migration／seed，寫入達 100 MiB 回 stable 507，domain rate limit 為 120/min/user+device。
- suspended／closed user 不能存取；單一 DB 遺失或 migration 失敗只讓該帳號 503，不拖垮其他帳號，DB 復原後 Android refresh 或重新登入可解除。
- push subscription 與 in-process rest timer 也按 user scope 隔離；MCP 仍維持 legacy path，依 frozen 順序由 F147 user-scope。

## 已有證據

- `./init.sh` → **init OK**；`uv run pytest` → **317 passed**；`tests/test_user_isolation.py` → **8 passed**；F141 `tests/test_auth.py` regression → **22 passed**。
- `uv run ruff check .` → **All checks passed**；F142 純後端且未動 `app/static/`，本 slice 不重跑 Playwright／APK。
- Claude cross-model review 的兩項 HIGH（單一壞 DB 全站停機、refresh 復原 stale state）均修正；最終 targeted review → **0 findings／integrity valid**。
- canonical acceptance verifier → **5/5 pass／integrity true**，report：`C:\Users\user\AppData\Local\Temp\claude-verify-F142-20260811-101932\report.md`。

## 下一個 session 最短入口

1. 讀本檔、F143 frozen acceptance 與 PRD；確認 `git status`。
2. **動工時才**把 `.harness/current_feature` 從 F142 設為 F143。
3. F143 是 sync server 協定：mutation receipt、version/tombstone/change sequence、push/pull pagination 與穩定錯誤契約；沿用 F142 request-scoped `DbSession`，不得新增第二條寫入路徑。

## 工作區注意

- `CLAUDE.md` 是使用者既有未提交變更；絕對不要 stage、restore 或覆寫。
- F142 已通過驗收但**未部署**：正式 Web／正式 APK 均未發布，assets／APK 仍為 **v150**；完整 E1 release DoD 仍留到 F149。
