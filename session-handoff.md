# Session Handoff
> 最後更新：2026-07-17（第四場：F5 收官）

## 這個 session 做了
- **F5 PWA 離線佇列：passing**（evidence 見 feature_list.json）
  - 新增 `app/static/sw.js`（app shell SWR 快取＋waitUntil、install 逐檔容錯、/api 不快取）、`app/static/js/queue.js`（IndexedDB 佇列：0/5xx 保留重試、401 上拋、永久 4xx 標 failed 手動捨棄）
  - app.js：logSet 離線入列、⏳/⚠ 標示由 `state.queueStatus` 即時推導（不存旗標）、online 事件與開站自動 flush、背景重繪不清輸入焦點、離線選動作帶入本次待同步組數
  - state.js：setCounts 隨 sessionStorage 續接（F2 遺留正式修復，重整後 set_number 不撞號）
  - 測試 +2：/sw.js 供應、SHELL 清單漂移防護（新增 js/css 檔忘了進 SHELL 會紅）
  - code review（8 finder + 2 verifier）10 findings 全處置；REFUTED：saveActiveWorkout 每組全量序列化（<1KB 人速操作，可忽略）；確認為正確行為：收工後佇列仍補傳（server 是 SSOT，該組確實練了）
  - acceptance-verifier 獨立以 Playwright setOffline 重現全部情境：8/8 PASS
- 60 tests、覆蓋率 99%（後端未動）、ruff 乾淨、console 0 errors

## 做到一半 / 已知未修
- 無半成品
- 有意識接受：捨棄 failed 組後 setCounts 不回滾（set_number 留空號，append-only 無唯一約束，無害）；離線重整後 done-list 的逐列歷史不重建（佇列 badge 仍在，資料安全）；SW 需 HTTPS（部署走 F7 Cloudflare Tunnel 沒問題，純 http LAN IP 直連不會有離線快取——已知窄缺口）
- F6 前置預警（PRD 技術約束）：(1) services 需新增單一交易的 log_workout 入口，勿以迴圈拼裝 log_set；(2) /mcp 掛載走不到 APIRouter 的 require_token，需用 fastmcp auth 接同一 token 來源，實連必驗 401
- F8 接點：services/stats.py set_tonnage(bodyweight_kg)
- F2–F5 真機最終確認留待 Ryan（手機實開：記錄＋課表＋飛航模式離線記錄）

## 下一步（具體到可直接動手）
- **F6 MCP＋AI connector**：fastmcp 掛 /mcp（Streamable HTTP）。TDD 起手：先寫 services.log_workout 單一交易入口的測試（整包寫入、未知動作整包拒絕回建議、create_missing=true 才建檔——PRD R7b）；再掛查詢 tools（query_workouts/get_progress/list_templates/get_body_metrics）與記錄 tools（log_workout/log_body_metrics）、prompt 模板 log-workout-interview；/mcp 帶錯 token 必須 401（fastmcp auth）。最後至少一家 connector（Claude）實連成功截圖。注意 get_body_metrics/log_body_metrics 依賴 F8 的 body_metrics 表——可先建模型與 service（F8 只剩 UI 與 heatmap 接線），或 F6 先做 workout 相關 tools、body metrics tools 留到 F8 後補
