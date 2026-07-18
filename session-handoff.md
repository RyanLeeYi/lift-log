# Session Handoff
> 最後更新：2026-07-18（第十場續：**F7 passing → MVP F1–F9 全數收齊**；Ryan 真機回饋轉 F10–F12 入列 failing）

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
