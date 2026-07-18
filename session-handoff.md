# Session Handoff
> 最後更新：2026-07-18（第十場再終：F13 passing、**F14 實作 GREEN 未驗證**（commit 8820688），撞第二個帳號的 Fable 週限額收工）

## F14 現況（下場從這裡接）
- **已完成（commit 8820688）**：feature_list 入列（acceptance Ryan 簽核）；RED→GREEN：sw.js install 改 `fetch(url?v=CACHE_NAME, {cache:"reload"})` + `cache.put(url)`（杜絕新 SW 裝舊資產的混版）、CACHE_NAME bump **v5**；app.js controllerchange 自動 reload（hadController 條件防首裝重載、旗標防循環）；兩條源碼模式測試。138 tests 全過、ruff 乾淨
- **未做（依序）**：1) Playwright E2E 驗自動更新流（做法：copy app/static 到暫存目錄用 `python -m http.server` 隨機 port 服務→開頁等 SW ready→改暫存副本的 CACHE_NAME＋index.html 可辨識內容→page.reload() 一次→**不再手動操作**，等頁面自動變新內容；殺 server 記得樹殺）；2) `/codex-review`（只審 8820688）；3) acceptance-verifier（uv 專案不走 codex-verify，見 memory）；4) F14 → passing；5) mission-control 重啟 lift-log 部署；6) Ryan 桌機/手機開一次 app 確認自動到位
- **F13 已收**（4/4 PASS，commit 4d81661）：sw.js no-cache 生效，公開 URL REVALIDATED。CF 快取是 per-colo——桌機同機房已新，手機 4G 機房的舊 sw.js 條目等 TTL 或 purge
- 背景：Ryan 桌機 Ctrl+Shift+R 已見新版（F12 倒數確認 serve 正常）；手機待 F14 部署後自然解決
- **用量**：兩個帳號的 Fable 週限額同日雙雙觸頂（usage-guard per-model 窗口攔的）——下場開工前先 `cswap list` 看額度

## 第十場最終快照
- **F12 完成上線**：規格（a50e019）→ 後端（0c01278）→ 前端（62bb947）→ codex-review 4 P2 全修（bed347d）→ acceptance-verifier 8/8 PASS → passing。mission-control 已重啟 lift-log，**正式 DB 遷移自動完成**（templates API 已帶 rest_hint_seconds），本機 sw.js v4
- **注意：Cloudflare 邊緣快取 sw.js 4 小時**（cf-cache-status HIT）——公開 URL 的新版最多延遲 ~4h 到手機；急件去 CF dashboard purge。通案已入列 **F13（sw.js no-cache 標頭）**
- **Codex 驗收限制（記憶已存）**：workspace-write sandbox 跑不了 uv（寫不了 cache、讀不了 managed Python）——uv 專案驗收直接派 acceptance-verifier fallback，別燒 Codex 額度
- **測試孤兒教訓**：`uv run uvicorn` 的 Popen 用 `terminate()` 只殺 uv 層，孤兒 uvicorn 佔 port 頂替下一輪（症狀：fresh DB 卻回 template name already exists）。一律 `taskkill /F /T /PID` 整樹殺＋隨機 port
- **F13 也完成了（同場加映）**：sw_no_edge_cache middleware（commit 0c2eb11）→ 驗收 4/4 PASS → passing。公開 URL 實測 CF 對 no-cache 的行為是「存但每次回源驗證」（REVALIDATED），部署即時生效；zone 會改寫瀏覽器側標頭為 max-age=14400 但不影響 SW 更新（瀏覽器對 SW 主腳本預設繞過 HTTP cache）。改版前的舊 /sw.js 快取條目一次性 HIT 至 TTL 過期或 Ryan purge
- **下場開場動作**：照順序做 **F10 自訂動作**（acceptance 已簽核；POST /api/exercises 已存在，主戰場前端 picker/加動作面板）→ F11 體重補記（body-metrics date 欄位已支援）。改 static 資產記得 bump sw.js CACHE_NAME（現為 v4）
- Ryan 手機實測 F12 倒數（等 CF 快取過期或 purge 後）：課表設參考秒數→倒數→超時變紅震動→點 chip 臨時調
- vault DEVLOG 本場已記（MVP 收官＋F12 全流程）

## 第十場（2026-07-18）
- 開場撞 Session 98% 用量門檻一次（帳號輪替後續作；usage-guard 已另案改版成以 cswap per-account 判定，見 `~/.claude/scripts/usage-guard.sh`）
- **F7 → passing**：Ryan 於 Cloudflare dashboard 加 public hostname `lift-log.my-super-dev-server.work` → 公開 HTTPS `/health` 200、首頁 200；Ryan 手機 4G 真機記錄（當日 workout 1–3 含實值 sets）；mission-control 收編（第八場實測＋services.toml＋存活旁證）。acceptance-verifier 逐條 3/3 PASS
- **MVP 全 passing**。收官事項（vault PLAN.md checklist）：連續自用 2 週對成功指標、README（先讀 vault `identity/voice-and-tone.md` 若存在）、after-action → 尚未動
- **Ryan 真機試用回饋 → 新 feature 入列（failing，acceptance 已含 Ryan 的設計選擇）**：F10 自訂動作（完整欄位、多數選填）、F11 體重補記過去日期（API 已支援 date，純 UI）、F12 組間休息目標倒數提醒（實際量測邏輯不變）。回饋 #2（課表編輯 ↑↓ 箭頭）確認是正常功能（調動作順序）非 bug，未入列；回饋 #5（收工按鈕語意）已口頭說明（收工只清 client 狀態，資料每組即時寫入），未入列
- **下場開場動作**：從 F10 開始（一次一個 feature、TDD）；F10/F11 的 API 面已存在（POST /api/exercises、body-metrics date 欄位），主戰場在前端 `app/static/js/`——記得改 static 資產要 bump `sw.js` CACHE_NAME

## 第九場（2026-07-18）

## 第九場（2026-07-18）
- 開場確認：repo 乾淨、8137 `/health` ok、F1–F6/F8/F9 passing 不變
- Ryan 決定：Cloudflare hostname **他自己去 dashboard 加**（建議值不變：`lift-log.my-super-dev-server.work` → `http://localhost:8137`）
- **下場開場動作**：先問 Ryan hostname 加了沒 → 加了就驗證公開 HTTPS（`curl https://<hostname>/health`）＋請 Ryan 手機 4G 記錄一組 → 兩者都過才把 F7 改 passing（附證據）。F7 過後進 MVP 收官（見 vault PLAN.md checklist）

## 進度總覽
F1–F6、F8、F9 全部 passing（各自附 acceptance-verifier 證據於 feature_list.json）。**F7 failing**，本機部分已完成，剩餘兩步只有 Ryan 能做：

1. **Cloudflare dashboard 加 public hostname**：Zero Trust → Tunnels →（現有 token 型 tunnel，ingress 只能 dashboard 管）→ 建議 hostname `lift-log.my-super-dev-server.work` → service `http://localhost:8137`（照 reels 的慣例；名稱最終由 Ryan 定）
2. **手機 4G 實測**：關 WiFi 開站台記錄一組（F7 acceptance）；順便真機確認 F2–F5（記錄＋課表＋飛航離線，歷次驗收都留了這條）

## 這個 session 做了
- **F6 收尾→passing**：acceptance-verifier live MCP 實呼叫 8/8 PASS
- **F7 本機部分**：`/health`（TDD，無 auth、實探 DB）；services.toml 收編 lift-log（port 8137、autostart）；mission-control 啟停監控實測。**注意孤兒教訓**：中台被 `taskkill /F` 硬殺會讓受管服務全變孤兒佔 port（詳見 mission-control session-handoff 2026-07-18 條目）
- **F8→passing**：GET/POST /api/body-metrics（同日覆蓋 201/200、IntegrityError 競賽復原）、/body SVG 折線頁（body.js，無圖表庫）、heatmap 自體重噸位接 latest_weight；Codex review 3 P2 全修（舊體脂預填、序列先篩後切、防雙擊）；驗收 5/5
- **F9→passing**：DailyStatus model/service（鏡射 body_metrics 含競賽復原）、GET/POST /api/daily-status、MCP log/get_daily_status、日曆明細顯示狀態（休息日也顯示）、interview prompt 改為覆述確認（含當日狀態）後才寫入；Codex review 2 P2 全修（prompt 確認缺口、cache bump v3）；驗收 6/6
- **正式環境**：mission-control 重啟 lift-log，8137 已跑最新 code（shell v3）

## 流程慣例（下場照做）
- feature 完成 → `codex exec review`（codex-review skill）→ verify findings → 修 → acceptance-verifier → 才改 passing
- **改任何 static 資產（js/css/html）→ sw.js CACHE_NAME 要遞增**（sw.js 內有註解釘住）
- Windows curl 發中文 JSON 會編碼壞掉——測試用 `uv run python` + httpx

## 做到一半 / 已知未修
- 無做到一半的程式碼；全部改動已 commit + push
- F7 之外的收官事項（MVP 全 passing 後）：連續自用 2 週對成功指標、README、after-action——見 vault PLAN.md 收官 checklist

## 驗證指令
- `uv run pytest`（121 passed，覆蓋率 98%）；`uv run ruff check .`
- 正式服務由 mission-control 管（`list_services` 應見 lift-log running）；`curl http://127.0.0.1:8137/health` → `{"status":"ok"}`
- MCP 快驗：`claude mcp list` 應顯示 lift-log ✔ Connected（需先 `claude mcp add`，上上場註冊在 local scope）
