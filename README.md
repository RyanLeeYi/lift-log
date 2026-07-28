# lift-log

自家部署的健身紀錄系統：手機單手快記、日曆 heatmap、課表選單、體重體脂記錄，
並以 remote MCP 讓 Claude／ChatGPT／Gemini 直接查詢訓練資料。

- 規格：`docs/prd/mvp-lift-log.md`
- 範圍與進度：`feature_list.json`
- 開發約定：`CLAUDE.md`

> 此 README 目前只記必要的操作與限制，完整版留到 MVP 收官時補。

## 執行

```bash
./init.sh                                                   # 環境恢復
uv run uvicorn app.main:app_factory --factory --reload      # 啟動
uv run pytest && uv run ruff check .                        # 測試與 lint
```

## 兩種前端執行環境

同一份 `app/static/` 同時服務兩邊，差異由 `js/env.js` 偵測 `window.Capacitor` 決定：

| | web（PWA） | Android app（Capacitor 殼） |
|---|---|---|
| 資產來源 | FastAPI 直接供檔 | 打包在 APK 內 |
| API | 同源相對路徑 | 打向公開站（後端 CORS 白名單放行） |
| Service Worker | 註冊，負責殼快取與更新鏈 | **不註冊** |
| 更新方式 | 部署後自動到位（F13/F14/F24） | 重新 build＋重裝 APK |

Android 建置與簽章步驟見 `docs/android-build-setup.md`。

## 已知限制（Android app 版）

- **沒有自動更新**：前端改版後必須 `npx cap sync android` → `gradlew -p android assembleRelease` → 重裝 APK。
  web 版的 sw.js 換版更新鏈對 app 版不成立。後端改版不受影響，不需重出 APK。
- **休息通知在 app 版走本機通知**（F62）：F31 的 Web Push 依賴 Service Worker，而 app 版不註冊 SW，
  因此改由 `@capacitor/local-notifications` 在**手機端**排程——伺服器關掉或沒網路時照樣會響。
  兩個 Android 系統限制：
  - **精確鬧鐘**：Android 12 起需要 `SCHEDULE_EXACT_ALARM`（已宣告）。使用者若在系統設定關閉「精確通知」，
    倒數會被系統延後，且**關閉的當下 app 會被重啟、已排定的通知被清掉**。app 內的開關會顯示「開（可能延遲）」提醒。
  - **Doze 模式**：`allowWhileIdle` 的通知每 9 分鐘只能觸發一次。休息間隔通常 60–180 秒遠短於此，
    但若手機長時間閒置進入深度 Doze，連續兩次提醒之間仍可能被系統壓下。
- **開啟需要網路**：資產雖然打包在本機，但資料一律來自公開站。離線時已記錄的組會進 IndexedDB
  佇列（與 SW 無關，照常運作），恢復連線後自動補傳。
- **sideload 安裝**：不上架 Play Store，靠 `adb install`。簽章金鑰遺失就無法對同一顆 app 發更新。
