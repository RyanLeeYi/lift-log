# Session Handoff
> 最後更新：2026-07-17（第二場，用量門檻收工）

## 這個 session 做了
- **F4 課表選單：實作完成，驗收流程未跑完**（詳見下方「做到一半」）
  - 後端 TDD：17 個新測試先寫先紅（templates CRUD、順序/預設組數、400/401/404、刪課表不影響歷史 workout、更新失敗不留半套）→ 全套 58 tests 過、覆蓋率 99%、ruff 乾淨
  - 新增：`app/models.py` Template/TemplateExercise、`app/services/templates.py`、`app/api/templates.py`、schemas TemplateCreate/Out（含 is_bodyweight 供 logger 預設）
  - 前端：`js/templates.js`（課表管理＋編輯器：加動作/↑↓排序/組數步進/兩段確認刪除）、`js/dom.js`（抽共用 el()，app.js/calendar.js 已改用）、app.js 加 templateSelect 畫面與 picker 今日菜單區（進度 n/m 組、臨時加動作區照舊）、state.js template 快照隨 sessionStorage 續接
  - Playwright 390×844 全流程實測 PASS：建課表（深蹲5組+硬舉3組）→ 開練選課表帶出菜單 → 記一組後菜單 1/5 → 臨時加臥推（課表定義未被污染）→ 重新整理課表續接 → 刪課表 → 日曆明細歷史完好（噸位 320 kg）；console 0 errors
  - 證據截圖：`docs/evidence-f4-templates.png`、`docs/evidence-f4-menu.png`

## 做到一半 / 已知未修
- **F4 驗收流程沒跑完就觸發用量門檻**：/code-review（medium）與 acceptance-verifier 都還沒跑 → `feature_list.json` F4 維持 failing（規則：verifier 過了才能改 passing）
- 已知非 F4 問題：重新整理後 setCounts 歸零（菜單進度顯示歸零、可能撞編號）——F5 acceptance 已涵蓋，勿在 F4 修
- F2/F3 真機確認仍待 Ryan

## 下一步（具體到可直接動手）
1. 跑 `/code-review medium`（範圍：本次 commit diff），CRITICAL/HIGH 必修
2. 跑 acceptance-verifier agent 對照 F4 acceptance 逐條驗收（伺服器啟動：`$env:LIFTLOG_TOKEN='verify-token'; $env:LIFTLOG_DB='<scratch>.db'; uv run uvicorn app.main:app_factory --factory --port 8137`）
3. 兩者都過 → `feature_list.json` F4 改 passing 附 evidence（58 tests/99% 覆蓋率/ruff 乾淨/Playwright 全流程/兩張截圖）
4. 然後進 F5 PWA 離線佇列（含 F2 遺留的 setCounts 續接恢復）
