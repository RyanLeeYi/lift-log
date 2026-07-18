# lift-log 健身紀錄系統

自家部署的健身紀錄 web：手機單手快記、日曆 heatmap、課表選單、體重體脂 SSOT，並以 remote MCP 讓 Claude／ChatGPT／Gemini 查詢訓練資料。規格見 `docs/prd/mvp-lift-log.md`，範圍與進度以 `feature_list.json` 為準。

## 啟動與驗證

- 環境恢復：`./init.sh`
- 啟動：`uv run uvicorn app.main:app_factory --factory --reload`；測試：`uv run pytest`；lint：`uv run ruff check .`
- 你宣告任何功能完成前，必須先跑過測試與 lint 並貼出輸出

## 專案結構與邊界

- `app/models.py` SQLAlchemy 模型；`app/api/` REST routers；`app/mcp.py` MCP tools；`app/static/` 前端 PWA（原生 JS，無打包器）
- API 層不得直接寫 SQL——一律經 `app/services/`；MCP tools 重用 services，不重複查詢邏輯
- 前端不引入框架與圖表庫；heatmap 用 CSS grid 自繪

## 工作規則

1. 一次只做一個 feature（看 `feature_list.json`，挑第一個 failing）
2. feature 狀態只能 failing → passing，且必須附驗證證據（測試輸出/截圖）
3. 不做 feature_list 之外的事；發現該做的新事項 → 先加進 list 標 failing，不直接做
4. session 結束前更新 `session-handoff.md`（L2 起）
5. 收官（session 結束）時檢查 `git status` + 未推 commit：程式碼有改動就 commit 並 push（remote：https://github.com/RyanLeeYi/lift-log）

## 專案特有約束

- 單人系統：全站單一 Bearer token（`.env` 的 `LIFTLOG_TOKEN`），缺少即拒絕啟動
- `sets` 刪除用軟刪（`deleted_at`，查詢一律濾掉）；編輯用 `PATCH /api/sets/{id}` 原位修改量測欄位（weight/reps/rpe/rest_seconds），set_number/exercise/client_uuid 不動（F16 起放寬原本的 append-only「不做 update」）
- 動作名稱雙語（name_zh/name_en），查詢與 MCP 參數兩者皆匹配
