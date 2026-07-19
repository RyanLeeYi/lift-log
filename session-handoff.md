# Session Handoff
> 最後更新：2026-07-18（第十一場續：**F14＋F15 皆 → passing 並部署上線**。各自 acceptance-verifier 驗過、mission-control 重啟後正式站 serve 新碼驗過。MVP F1–F9＋F12–F15 全 passing，剩 F10/F11。sw.js 現 **v6**）

## F15 收尾紀錄（已完成）
- **組間休息按鈕兩態切換**（Ryan 真機回饋：倒數沒有停止鈕）。就緒態「✓ 完成這組」記錄該組＋開始倒數＋進休息態；休息態「繼續下一組」停倒數＋LED 回靜態參考秒數＋凍結本次休息秒數＋回就緒態。rest_seconds 定案點＝按「繼續下一組」當下 elapsed（Ryan 選的），寫進下一組、用掉即清；第一組不帶。換動作/收工清掉未用凍結值
- commits：`b581b3a`（實作）+ `11bfbdf`（codex-review P2 修正：凍結值改成「確認保住後才清」，非離線失敗/入列失敗重試不丟）+ `a6070d0`（passing）
- 驗收：acceptance-verifier R1–R7 PASS（自寫 Playwright 擷 POST /sets body、LED 回參考值比對）；R8 換動作分支（驗收者）＋收工分支（補測 `verify_f15_endworkout.py`）雙 PASS；R9 F12 迴歸 out-of-scope（未動 F12 碼）。E2E `verify_f15.py`（scratchpad）。139 tests、ruff clean
- **Ryan 手機更新**：若他先前已手動刷一次拿到 F14（v5，有自動重載 listener），這次 F15（v6）會**自動到位**、不用再手動；若還沒拿到 F14，手動刷一次會直接到 v6，之後每次部署都自動

## 課表編輯（F21、F22 ✅ 完成上線，sw v14）
- **F22 課表加動作視窗：部位篩選**：Ryan 回饋要跟 logger picker 一樣有部位。addModal 加 `.chips` 部位按鈕（groups 取自 tpl.exercises），`tpl.muscleFilter` 篩選、與搜尋並用、開窗重置。codex-review P2 已修（chip 改就地更新不整頁重繪，避免與進行中搜尋 callback 競態——同 F21 選取/搜尋的 in-place 原則）。acceptance-verifier 8/8 pass。E2E `verify_f22.py`

- **F21 課表編輯：動作清單捲動＋加動作懸浮視窗**：Ryan 回饋。編輯課表的 `.tpl-items` 固定約 1 動作高＋捲動（`>1` 時加 scrollable）；「＋加動作」改成 `.modal-overlay` 懸浮視窗（搜尋＋可捲動清單＋確定加入/取消），**單選、按確定加入才進課表**。codex-review 3 P2 已修（modal 選取就地更新不重繪防跳頂、搜尋排除選取即清＋停用確認、tpl-items 保存/還原 scrollTop——因 cap 只 1 動作高，不還原會每次編輯跳頂）＋開窗重置搜尋。acceptance-verifier 10/10 pass。E2E `verify_f21.py`。**新增共用樣式 `.modal-overlay`/`.modal` 可給未來其他 modal 用**

## 開練頁版面（F20 ✅ 完成上線，sw v12）
- **F20 done-list 新→舊排序＋固定高度可捲動**：Ryan 回饋記多組時版面被推走。done-list 改最新在最上（`[...doneSets].reverse()`）；組數 > 2 時加 `.scrollable`（max-height 88px overflow-y auto），下方 steppers/主按鈕位置穩住；編輯某列時解除限高（`!editDraft` 條件）。codex-review P2 已修（finish/endWorkout 清 editDraft）。acceptance-verifier 7/7 pass。E2E `verify_f20.py`。**注意：F16/F19 的舊 logger/calendar E2E 已因 F19 單擊刪除＋F20 反轉順序過時並刪除，現行 logger E2E 是 `verify_f19_logger.py` + `verify_f20.py`**

## 紀錄「編輯＋刪除」✅ 全部完成上線（F16 訓練組、F17 體重、F18 每日狀態、F19 刪除 UX）
- **F18 每日狀態 編輯＋刪除 → passing 並部署（sw v11）**：後端 `DELETE /api/daily-status/{date}` 硬刪/404；日曆狀態列可編輯（精力/睡眠 1–5 量表 + 備註 inline 控制項、POST 覆蓋）＋單擊即刪。codex-review P2 已修（`refreshMonthAndDay` 守衛切月競態 selectDay(null) → 400；此修正惠及 F16/F18/F19 所有日曆變更）。acceptance-verifier 全 pass。E2E scratchpad `verify_f18.py`
- **剩餘 feature：F10 自訂動作、F11 體重補記過去日期**（Ryan 早前真機回饋，與本刪除/編輯串無關）。注意：F11 的 /body 表單目前只記今天；F17 已為過去日期做了編輯清單，F11 是讓表單能「新增」過去日期

- **F17 體重 編輯＋刪除 → passing 並部署（sw v10）**：後端 `DELETE /api/body-metrics/{date}` 硬刪/404（`delete_body_metric` service）；/body 折線圖下體重紀錄清單，每列數字輸入編輯（POST 覆蓋、日期不可改）＋單擊即刪。codex-review P2 已修（編輯草稿存 `body.editDraft` 不丟輸入）。acceptance-verifier R1–R7 pass。E2E scratchpad `verify_f17.py`

- **F19 訓練組刪除 UX 改版 → passing 並部署（sw v9）**：Ryan 回饋兩段式確認多餘＋要多選。改為 logger 與日曆**單擊即刪**（拿掉兩段式）；**多選批次刪除只在日曆**（「選取」→勾選→「刪除選取 (N)」，`cal.selectMode`/`selectedIds`）。刪除 404 當成功（防連點）、批次 finally 重載（部分失敗一致性）。acceptance-verifier 12/12 pass。codex-review 2 P2 已修。**F17/F18 的刪除跟這個範式走（單擊即刪、不做多選、無確認）**，不要再做兩段式確認

- **F16 訓練組 編輯＋刪除 → passing 並部署（sw v8）**：後端 `PATCH /api/sets/{id}`（原位、set_number 不變、404/範圍驗證，`SetUpdate` schema + `update_set` service）；logger done-list 與日曆明細每組可**用 stepper +/- 編輯**（`stepper`/`rpePicker` 已抽到 `dom.js` 共用）＋兩段式刪除；離線 queued 組刪除移出佇列、`flushQueue` 同步後回填 server id 到 doneSets。acceptance-verifier R1–R14 全 pass。codex-review 3 條已修（P1 回填 id、P2 刪除更新 setCounts、R9 改用 steppers）。CLAUDE.md sets 規則已改。E2E：scratchpad `verify_f16_logger/calendar/p1.py`
- **F17 體重 編輯＋刪除**（下一個做）：後端 `DELETE /api/body-metrics/{date}` 硬刪、不存在 404；/body 頁折線圖下新增可編輯/刪除清單；編輯＝POST 覆蓋、日期不可改；兩段式刪除。body_metrics model 在 `app/models.py`、service `app/services/`（body/metrics 相關）、既有測試 `tests/test_body_metrics.py`
- **F18 每日狀態 編輯＋刪除**：後端 `DELETE /api/daily-status/{date}` 硬刪、404；日曆明細 statusRow 可編輯/刪除；編輯＝POST 覆蓋。既有測試 `tests/test_daily_status.py`、`calendar.js` `statusRow()`
- 通用：刪除確認一律兩段式（範式已在 `templates.js` 與本場 F16）；改 static 記得 bump `sw.js` CACHE_NAME（現 **v8**）

## （F16 開工前的原始設計筆記，供 F17/F18 參照）
Ryan 回饋：要能清掉/編輯特定筆紀錄，涵蓋 **訓練組 + 體重 + 每日狀態**，入口在 **logger 當場 + 日曆過去 +（體重）/body 頁**。

**已談定的設計決定（下場照這個寫驗收，不用重談）：**
- **訓練組 sets**：
  - 刪除＝**軟刪（後端已全做好）**：`deleted_at` 欄位、`DELETE /api/sets/{id}`→`svc.soft_delete_set`（`app/services/workouts.py:275`）、所有查詢（exercises/stats/workouts services）已濾 `deleted_at.is_(None)`。缺前端入口。
  - 編輯＝**原位修改，新增 `PATCH /api/sets/{id}`**（改 weight_kg/reps/rpe/rest_seconds），**set_number/位置不變**。**Ryan 拍板放寬 CLAUDE.md「sets 不做 update」原則**（單人 app、audit 需求低）——記得同步更新 CLAUDE.md 那條約束的措辭。
- **體重 body_metrics / 每日狀態 daily_status**（都是 date UNIQUE、一天一筆、POST 本來就覆蓋 upsert）：
  - 刪除＝**硬刪（Ryan 拍板）**：新增 `DELETE /api/body-metrics/{date}`、`DELETE /api/daily-status/{date}`（軟刪會撞 UNIQUE(date) 無法重記同日，故硬刪最乾淨）。
  - 編輯＝**沿用現有 POST upsert**（同日覆蓋，已支援過去日期），前端只要「把某天的值載進表單改一改再存」，後端不用動。
- **確認 UX**：一律沿用課表刪除的**兩段式**（第一下變確認、第二下才真刪；範式在 `app/static/js/templates.js` 的 `confirmDeleteId`），不用瀏覽器彈窗。
- **離線 sets**：done-list 裡尚未同步（queued、無 server id）的組，刪除/編輯＝改 IndexedDB 佇列那筆（`queue.js`），不打 API。

**入口位置：**
- logger「已完成的組」每列：編輯（把值帶回 steppers 改）＋刪除（兩段式）。注意線上組有 server `id`、離線 queued 組只有 client_uuid。
- 日曆某天明細（`calendar.js` `detailRows`/`statusRow`）：把分組文字「深蹲 80×8 80×8」改成**每組一列**可編輯/刪除；狀態列可編輯/刪除；**新增當日體重顯示**可編輯/刪除（目前明細只顯示噸位、沒顯示體重）。
- /body 頁（`body.js`，目前只有折線圖）：體重紀錄列成**可編輯/刪除的清單**。

**拆法（一次一個、TDD）**：F16 訓練組 編輯＋刪除（前端為主＋新 PATCH endpoint）→ F17 體重 編輯＋刪除（後端 DELETE + /body 清單 UI）→ F18 每日狀態 編輯＋刪除（後端 DELETE + 日曆 UI）。
**下場第一步**：把 F16–F18 完整驗收草擬好給 Ryan 簽核 → 凍結進 feature_list → 從 F16 TDD 開工（PATCH /sets 要後端測試；前端兩態切換/刪除用 Playwright E2E）。

## 下場開場動作
- **從 F10 自訂動作開始**（acceptance 已簽核：中文名必填、英文/部位選填、自體重勾選；POST /api/exercises 已存在，主戰場前端 picker/加動作面板）→ 再 F11 體重補記過去日期（API date 欄位已支援，純 UI）。一次一個 feature、TDD、改 static 記得 bump `sw.js` CACHE_NAME（現 v5）
- **提醒 Ryan（F14 部署後一次性動作）**：桌機/手機各**手動刷一次**（手機關掉 app 重開或下拉重整）才會拿到 F14 這版；**從此之後每次部署都自動到位、不用再手動**。這是引入自動更新功能的一次性 bootstrap 成本（舊版 app.js 沒有 listener），非 bug
- **F14 待 Ryan 確認的小事**：實作用一次性 `skippedInitialClaim` 取代 acceptance 原文的「hadController 條件」（可觀察行為相同＋修掉 P2① 首訪者不更新的邊界；驗收者判定符合）。若認可，acceptance 括號可更新措辭——不改也不影響
- **PRD 缺口（驗收者回饋，非阻擋）**：`docs/prd/mvp-lift-log.md` 標頭已補註「F9 起以 feature_list.json 為準」

## F14 收尾紀錄（已完成）
- **程式碼完成＋自我驗證充分**（commits 8820688 原始 + **8426a15** review 修正）：
  - sw.js install：`fetch(url?v=CACHE_NAME, {cache:"reload"})` + `cache.put(url)`（版本戳杜絕新 SW 裝舊資產混版）、CACHE_NAME **v5**、activate 清舊快取 + claim（與 8820688 一致）
  - app.js：controllerchange 自動 reload。**Codex P2① 修正**：原本 `hadController` 永久 false 會讓「首訪者頁面開著、之後部署」永遠不更新；改為一次性 `skippedInitialClaim`——只跳過首裝的**初次**接管，之後任何一次接管（部署新版）都 reload 一次（`refreshing` 旗標防循環）
  - 138 tests 全過、ruff 乾淨
- **驗證證據**（下場給驗收者/寫進 feature_list evidence）：
  - `/codex-review`（審 8820688）回 3 條：**P2① 已修**（見上）；**P1 已知一次性 bootstrap 限制**（見下，接受並揭露）；**P2② 已知**（記錄中途被 reload 丟失正填的那組輸入＋計時；訓練情境已持久化課表/動作，只丟正在填的一組，接受）
  - Playwright E2E 兩情境皆 PASS（scratchpad `verify_f14.py`＝暖升級 acceptance 情境；`verify_f14_p21.py`＝P2① 首訪者不導航自動更新）。E2E 教訓：(a) marker 要埋 `<head>`，埋 body 內會被 app.js render 洗掉；(b) 導航進行中 evaluate/content 會噴 "context destroyed"，要 try/except 重試；(c) http.server 用 `allow_reuse_address` 避免前輪殘留 socket 撞 port；跑前 `taskkill //F //IM headless_shell.exe` 清孤兒
- **⚠ 偏離凍結 acceptance 需 Ryan 確認**：acceptance 原文寫「首次安裝不 reload——以啟動時已有 controller 為條件」。實作改用一次性 skippedInitialClaim（可觀察行為相同＝首裝不 reload，且修掉 P2① 邊界）。若 Ryan 認可，把 acceptance 該括號更新為「首裝的初次接管不 reload、之後接管都 reload」
- **⚠ P1 一次性 bootstrap 限制（已揭露，非缺陷）**：F14 是第一個有自動重載的版本。Ryan 手機現在跑 F14 之前的 app.js（沒有這個 listener），**F14 部署當次它不會自動到位、仍需手動刷一次**才拿到 F14；從 F14 之後的每次部署才會自動更新。SW 端 `client.navigate()` 試過想根治 bootstrap，但對舊 SW 載入的既有 client 不觸發（實測 0 次自動導航），且偏離 acceptance，已放棄
- **未做（依序，下場額度重置後）**：1) acceptance-verifier agent 逐條驗收（uv 專案不走 codex-verify，見 memory）；2) F14 → passing（evidence 引本場 E2E＋codex-review）；3) mission-control 重啟 lift-log 部署；4) 告知 Ryan：這次部署後手機**要手動刷一次**（bootstrap），之後才自動；桌機同理一次
- **F13 已收**（4/4 PASS，commit 4d81661）：sw.js no-cache 生效，公開 URL REVALIDATED
- **用量**：本場切 Opus 4.8 續作（Fable 週限額兩帳號都 ~91%）。收工原因：現用帳號 ian4567x 的 **5h 窗到 93%**（Opus 真正燒的窗，破 90%），15:00 重置。下場開工前 `cswap list` 看額度

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
