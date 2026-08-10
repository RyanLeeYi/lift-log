# session handoff

最後更新：2026-08-10。active feature：**F141**；E1（F139–F149）已簽核。F141 **passing**，目前 **130/149 passing**；F141 已收官，下一步是 F142。

## 這場完成

- Server 已加入 Google ID token 驗證、control DB 的 user/device/session、15 分鐘 Android access token、idle 30 天／absolute 90 天 rotating refresh token 與 family replay revoke；建立失敗會回滾 user data DB。
- Android 使用 Credential Manager 顯式 Google 登入，session 以 EncryptedSharedPreferences／Keystore 保存；Web session 限 Secure HttpOnly SameSite cookie＋CSRF，Web token 不可改走 Bearer 繞過 CSRF。
- 全域 APK update endpoint 同時接受既有 legacy token 與有效 Android access token，避免 F67 在 F149 切換前退化；user-scoped domain API 留給 F142／F146。
- assets／APK 為 **v150**；F141 cross-model review 最終 0 findings，canonical acceptance verifier 10/10 pass。

## 已有證據

- `uv run pytest` → **308 passed**；`tests/test_auth.py` → **22 passed**；`uv run ruff check .` → **All checks passed**。
- `npm run test:auth` → **5 passed**；Playwright F141 → **PASS**；F81 regression → **50/50 passed**。
- Android `testProdDebugUnitTest`、`compileProdDebugAndroidTestJavaWithJavac`、`assembleProdDebug` → **BUILD SUCCESSFUL**；instrumentation 已編譯，因本輪無裝置未執行 runtime。
- Claude cross-model review → **0 findings／integrity valid**；canonical acceptance verifier → **10/10 pass／integrity true**。

## 下一個 session 最短入口

1. 讀本檔、F142 frozen acceptance 與 PRD；確認 `git status`。
2. **動工時才**把 `.harness/current_feature` 從 F141 設為 F142。
3. F142 涉及 per-user DB routing／ownership isolation，先列出所有 domain DB 入口與負向跨帳號測試，再開始實作。

## 工作區注意

- `CLAUDE.md` 是使用者既有未提交變更；絕對不要 stage、restore 或覆寫。
- F141 已通過驗收但**未部署**：正式 Web／正式 APK 均未發布；F141 Android instrumentation runtime 因本輪無裝置未執行，完整 E1 release DoD 仍留到 F149。
