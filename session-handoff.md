# Session Handoff
> 最後更新：2026-07-17

## 這個 session 做了
- 動工日全套：PRD（R1–R9）、feature_list F1–F9、L1 harness、GitHub repo（https://github.com/RyanLeeYi/lift-log）
- **F1 資料層＋記錄 API：passing**（冪等三態、TOCTOU 復原、compare_digest、10 findings 全修）
- **F2 手機記錄 UI：passing**（seed 35 動作、LED 計時器、上次帶入；5 bugs 修：搜尋框重繪、雙擊、編號接續、計時器洩漏、LIFTLOG_DB env）
- **F3 日曆 heatmap：passing**（41 tests；/api/stats/calendar 噸位統計、月視圖 5 級琥珀深淺、點日明細、換月；4 findings 修：guard 繞過、動作庫快取、零噸位顯示、月份重置）
- **真機確認待 Ryan**：手機開一次真實記錄流程

## 做到一半 / 已知未修
- 無半成品
- F5 acceptance 含 F2 遺留（重新整理後 setCounts 歸零可能撞編號）
- F6 前置預警在 PRD 技術約束（原子 log_workout、/mcp auth）
- F8 接點已備好：services/stats.py 的 set_tonnage(bodyweight_kg) 參數、calendar_tonnage 呼叫端傳最新體重即可

## 下一步（具體到可直接動手）
- F4 課表選單：TDD 先寫 templates CRUD API 測試（建課表含動作順序與預設組數、開練帶課表、刪課表不影響歷史 workout——workouts.template_id 已存在）；再做課表管理頁＋開練時選課表帶出動作清單
