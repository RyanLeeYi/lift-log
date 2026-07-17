# Session Handoff
> 最後更新：2026-07-17

## 這個 session 做了
- 動工日全套：PRD（R1–R9）、feature_list F1–F9、L1 harness、GitHub repo（https://github.com/RyanLeeYi/lift-log）
- **F1 資料層＋記錄 API：passing**（29→34 tests、99% 覆蓋率；10 條 review findings 全修：冪等範圍、TOCTOU 復原、LIKE 跳脫、compare_digest、409 語意入 PRD）
- **F2 手機記錄 UI：passing**（seed 35 個雙語動作、靜態 PWA 掛載、深色 LED 計時器設計；fresh-context review 4 findings 全修：搜尋框重繪清空、雙擊重送、回選同動作編號重複、計時器洩漏；另修 LIFTLOG_DB env 別名 bug；acceptance-verifier 獨立 Playwright 重跑全 PASS）
- **真機確認待 Ryan**：手機開一次真實流程（部署後或 Tailscale 連家機）

## 做到一半 / 已知未修
- 無半成品
- F5 acceptance 已補一條 F2 遺留：訓練中重新整理後 setCounts 歸零、set_number 可能重複（sets 表無 (workout_id, exercise_id, set_number) unique）
- F6 前置預警在 PRD 技術約束：原子 log_workout 入口、/mcp auth 不走 router dependency

## 下一步（具體到可直接動手）
- F3 日曆 heatmap：TDD 先寫 `GET /api/stats/calendar?year=&month=` 的噸位計算測試（自體重=最新 body_metrics 體重+負重、無體重紀錄只計負重——注意 body_metrics 表在 F8 才建，F3 先以「無體重紀錄」規則實作、常數噸位公式抽 services）；再做 /calendar 前端月視圖（CSS grid 自繪、5 級深淺、點日看明細）
