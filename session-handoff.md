# Session Handoff
> 最後更新：2026-07-17

## 這個 session 做了
- 動工日全套：PRD（docs/prd/mvp-lift-log.md，R1–R9）、feature_list F1–F9、L1 harness
- **F1 資料層＋記錄 API：passing**（TDD；29 tests、覆蓋率 99%、ruff 乾淨；acceptance-verifier 逐條 PASS 並以真實 server curl 覆核）
- code review（8 finder + 3 verifier agents）10 findings 全修：冪等重放範圍修正（跨 workout／已刪除 → 409）、IntegrityError TOCTOU 復原、LIKE wildcard 跳脫、token 改 secrets.compare_digest、last-sets 404、409/404/400 語意寫入 PRD 邊界情況
- 驗收者發現 uvicorn 入口壞掉 → 已修（`app.main:app_factory --factory`，CLAUDE.md 同步）

## 做到一半 / 已知未修
- 無半成品。兩條 F6 前置預警已記在 PRD 技術約束（services 需原子 log_workout 入口；/mcp auth 走不到 router dependency）
- GitHub remote 已建：https://github.com/RyanLeeYi/lift-log（private，main 已推）

## 下一步（具體到可直接動手）
- F2 手機記錄 UI：先建 `app/static/`（index.html + JS modules），FastAPI 掛靜態檔；驗收＝手機瀏覽器完成「開練→選動作→kg×reps→送出」、上次重量帶入（GET /api/exercises/{id}/last-sets 已就緒）、組間計時器（rest_seconds 隨下一組送出）
- F2 開工前先種 seed 資料：約 30 個雙語動作的預載腳本（PRD 介面契約有寫，F1 未含）
