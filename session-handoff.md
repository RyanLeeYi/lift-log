# session handoff

最後更新：2026-08-10。active feature：**F140**；E1（F139–F149）已簽核。F140 **passing**，目前 **129/149 passing**；暫停於 F140 收官，F141 尚未啟動。

## 這場完成

- F139 LocalStore foundation 已獨立驗收通過並提交；F140 已把 Android 核心 domain 讀寫切至同一顆 `liftlog-local.db`。
- WebView 與 native overlay 共用 LocalStore；Android 舊 IndexedDB／localStorage／SharedPreferences domain queue 已移出正式寫入路徑。Web 維持 REST online-only，尚未啟用雲端同步。
- dev assets／APK 為 **v149**；tokenless 與 airplane-mode emulator cold start 都直接進 home，無 setup。
- F140 fresh-context Codex review 的 tombstone、template snapshot、tokenless gate、pending 單位、顯式 set number 與 overlay UI evidence findings 均已修正；第二輪六項驗收全 pass。

## 已有證據

- `uv run pytest` → **286 passed**；`uv run ruff check .` → **All checks passed**。
- Android `testDevDebugUnitTest` → **BUILD SUCCESSFUL**（8/8；`LocalStoreTest` 7 tests）。
- `emulator-5554` F140 instrumentation → **OK (2 tests)**；第二支實際以 WebView Capacitor LocalStore plugin seed/readback，並在 overlay window 點擊「停止」與「完成這組」。
- E2E 全綠：F67 20/20、F80 19/19、F81 50/50、F83 35/35、F85 94/94、F87 38/38、F90 30/30、F91 20/20、F92 15/15、F103 16/16、F104 7/7。
- packaged dev APK 直接驗證 v149 assets SHA match；fresh-context `codex exec` gpt-5.6-sol 第二輪六項逐條 PASS。

## 下一個 session 最短入口

1. 讀本檔、F141 frozen acceptance 與 PRD；確認 `git status`。
2. **動工時才**把 `.harness/current_feature` 從 F140 設為 F141；本次不要提前切換。
3. F141 涉及 auth/session/security，先依 frozen acceptance 確認範圍與測試門檻，再開始實作。

## 工作區注意

- `CLAUDE.md` 是使用者既有未提交變更；絕對不要 stage、restore 或覆寫。
- F140 已通過驗收但**未部署**：正式 Web／正式 APK 均未發布；只有 dev APK 與 emulator 驗證。
