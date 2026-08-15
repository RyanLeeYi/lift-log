# lift-log 健身紀錄系統

自家部署的健身紀錄 web：手機單手快記、日曆 heatmap、課表選單、體重體脂 SSOT，並以 remote MCP 讓 Claude／ChatGPT／Gemini 查詢訓練資料。規格見 `docs/prd/mvp-lift-log.md`，範圍與進度以 `feature_list.json` 為準。

## 啟動與驗證

- 環境恢復：`./init.sh`
- 啟動：`uv run uvicorn app.main:app_factory --factory --reload`；測試：`uv run pytest`；lint：`uv run ruff check .`
- 你宣告任何功能完成前，必須先跑過測試與 lint 並貼出輸出
- **E2E（前端 PWA）**：Playwright 已是 dev 依賴，一律用 `uv run python <script>` 跑。**不要用 `uv run --with playwright`**——那是 ephemeral 疊裝，冷環境/驗收 agent 每次重建很慢；瀏覽器由 init.sh 的 `uv run playwright install chromium` 裝好。
- **純前端 feature 的驗收**：後端未動時，完成定義的 pytest 可只跑相關子集（例 `uv run pytest tests/test_exercises.py`），保留 ruff + UI E2E 全驗即可，不必每次重跑全套（提速；理由見全域記憶 verification-speed-policy）。

## 專案結構與邊界

- `app/models.py` SQLAlchemy 模型；`app/api/` REST routers；`app/mcp.py` MCP tools；`app/static/` 前端 PWA（原生 JS，無打包器）
- API 層不得直接寫 SQL——一律經 `app/services/`；MCP tools 重用 services，不重複查詢邏輯
- 前端不引入框架與圖表庫；heatmap 用 CSS grid 自繪

## 工作規則

1. 一次只推進一個 envelope（沒有 envelope 就是一條 feature，看 `feature_list.json` 挑第一個 failing）。
   同 envelope 內的 slice 可同批實作，序列或平行皆可；平行需 `touches` 無交集且各自 worktree。
   **驗收一律逐條、依 `prerequisites` 順序、各自 evidence**——上游改動會讓已通過的下游驗收失效
   - ⚠ **不要整份 `Read` `feature_list.json`**（334KB，多數是 142 條 passing 的 acceptance 原文，
     整讀約 8 萬 token 且每輪重送）。要哪幾條就挑哪幾條：
     `uv run python -c "import json;fs=json.load(open('feature_list.json',encoding='utf-8'))['features'];print([f['id'] for f in fs if f['status']=='failing'])"`
     ——長證據早已搬進 `docs/evidence/F<id>.md`，`evidence` 欄位只剩 pointer
2. feature 狀態只能 failing → passing，且必須附驗證證據（測試輸出/截圖）
3. 不做 feature_list 之外的事；發現該做的新事項 → 先加進 list 標 failing，不直接做
4. session 結束前更新 `session-handoff.md`（L2 起）
5. 收官（session 結束）時檢查 `git status` + 未推 commit：程式碼有改動就 commit 並 push（remote：https://github.com/RyanLeeYi/lift-log）
6. **feature 改 passing 後出一顆 APK 丟 Google Drive**（Ryan 用來隨時裝新版）：

   ```powershell
   # 先把 app/static/js/state.js 的 APP_VERSION 升版（它是 versionCode 的唯一來源，見 F67）
   npx cap sync android                                   # 漏掉這步 APK 內還是舊畫面
   .\android\gradlew.bat -p android assembleRelease
   Copy-Item android\app\build\outputs\apk\prod\release\app-prod-release.apk `
     "G:\我的雲端硬碟\lift-log-apk\lift-log-<版號>-<feature id>.apk"
   ```

   - ⚠ **路徑是 `apk\prod\release\app-prod-release.apk`**。`apk\release\app-release.apk` 是
     加 product flavor 之前留下的**殭屍檔**（2026-07-30 的 v95），還在磁碟上、不會被新 build 覆蓋，
     照舊路徑複製會出一顆看起來成功的舊版 APK。複製後用
     `unzip -p <apk> assets/public/js/state.js | grep APP_VERSION` 確認版號再交付

   - 目的地是 **`G:\我的雲端硬碟`**（真正的 Google Drive）。**不要**用 `OneDrive\Desktop\GoogleDrive`
     ——那個資料夾在 OneDrive 裡面，只是名字叫 GoogleDrive，丟進去不會上 Google Drive
   - 檔名帶版號與 feature id（例 `lift-log-v62-F61.apk`），舊檔保留當回退用
   - **只動後端的 feature 不必出 APK**（app 版資產打包在 APK 內、API 打公開站，後端改版直接生效）；
     動到 `app/static/` 就要出

## Vault 連動

專案的 PLAN / DEVLOG / DECISIONS 在
`C:\Users\user\OneDrive\Desktop\Obsidian\projects\2026-07-健身紀錄系統\`。

- **開場先讀那裡的 `PLAN.md`**：為什麼做、作品集定位、成功指標都在 vault，這個 repo 只有「怎麼做」
- **收工時回寫兩處**：`DEVLOG.md` 記一筆（卡點、解法、有數字記數字）；難回頭的技術選擇寫 `DECISIONS.md`
- repo 的 `session-handoff.md` 是給下一個 agent 看的；vault 的 `DEVLOG.md` 是給 Ryan 累積成就故事用的。兩者都要寫，不能互相取代
- 寫入 vault 的規則以 vault 根目錄 `AGENTS.md` 為準（增刪檔案要在同一輪 response 內更新 `INDEX.md`）

## 專案特有約束

- 單人系統：全站單一 Bearer token（`.env` 的 `LIFTLOG_TOKEN`），缺少即拒絕啟動
- `sets` 刪除用軟刪（`deleted_at`，查詢一律濾掉）；編輯用 `PATCH /api/sets/{id}` 原位修改量測欄位（weight/reps/rpe/rest_seconds），set_number/exercise/client_uuid 不動（F16 起放寬原本的 append-only「不做 update」）
- 動作名稱雙語（name_zh/name_en），查詢與 MCP 參數兩者皆匹配
