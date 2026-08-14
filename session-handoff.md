# session handoff

最後更新：2026-08-14。現在 **140/155 passing、15 failing**。

## 下一步

1. **F147**（既有 MCP 整合到 user-scoped）。接著 F148 → F149 → F153 → F155 → 10 條舊債。
2. 兩件規格層級待 Ryan 裁決，寫在 `docs/evidence/F146.md` 末段：legacy 單一 token 路徑要不要收掉、
   Web 端 IndexedDB 離線佇列與 envelope 非目標的字面出入。兩者都不阻擋已通過的 acceptance。
3. `release/lift-log-v153.apk` 待複製到 Google Drive（`G:` 未掛載）。

## 本輪完成

- **F146 passing**：F154 補上 R5 change log 整合後重驗，全 gates 綠（ruff、pytest 373、
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
