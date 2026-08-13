# session handoff

最後更新：2026-08-14。目前 **137/155 passing、18 failing**（F154／F155 為今天新開的兩條）。

## 下一步（最短入口）

1. **F154 跨模型驗收結果**（`/codex-verify` 已可用，這場實測 Codex 恢復正常）。全 pass 才改 passing。
2. F154 落地後：**F145 用嚴格讀法重驗**（Android↔Web 端對端現在跑得動了）、**F146 重驗**
   （它缺的 change log 整合已由 F154 補上）。
3. 然後 F147 → F148 → F149 → F153，再處理 10 條舊債；**F155（既有資料回填）**也在門檻內。

## 2026-08-14 的十題裁決（grill）

| # | 決定 |
|---|---|
| 1 | 做 change-log 整合 |
| 2 | F146 的 Playwright CSRF 拒絕／兩帳號隔離改由 server 端測試負責（acceptance 已重簽） |
| 3 | Google session 與 API token 兩條路都留 |
| 4 | F152／F145 接受同模型驗收降級，之後的 feature 用跨模型 |
| 5 | 三支壞掉的 native e2e 修掉（已修，見下） |
| 6 | **domain 表當 SSOT**，同步層退成版本簿（vault DECISIONS **D17**） |
| 7 | F146 acceptance 新措辭簽核 |
| 8 | 開新 feature F154，不塞進 F146 |
| 9 | domain 表加 `sync_id`／`version`／`deleted_at` |
| 10 | 既有資料先不回填，另開 F155 |

## F154 現況（實作與測試完成，等驗收）

做了什麼、撞到什麼坑，見 `docs/evidence/F154.md`。三個關鍵點：

- **domain 表是事實來源**，`app/services/projection.py` 是兩層之間唯一的橋
- **硬刪全改 tombstone**，讀取濾 `deleted_at`，刪掉再記同一天＝復活那一列
- **自然鍵撞號退成 `natural_key_conflict`**，不自動合併也不覆蓋

驗證：pytest exit 0、ruff clean、Android 38/0、encoding 64/64、新增
`tests/test_sync_domain_bridge.py` 5 條跨路徑測試。

## 三支 native e2e 已修（委派完成）

根因**不是**「native setup 沒有 input」那麼單純：共用的 `FAKE_PLUGIN` 一直缺 `Sync` 外掛，
開機的 `initializeNativeSync()` 因此 throw，畫面卡在「正在準備本機資料」。補上 mock 後
`verify_f81` 不改任何測試邏輯就過。`verify_f61`／`f110` 另各有一個結構差異（見 commit）。

⚠ **要 Ryan 看一眼**：`verify_f61` 原本用真正的 REST round-trip 驗「app 版打公開站」，
但 F131 之後 native 的 domain 資料走 LocalStore、不打網路，現在 `round_trip()` 的 `count>0`
量的是 LocalStore 假資料。`/health` 與 `/api/app/latest` 仍實際打公開站，所以那條斷言還有
真實請求撐著，但**標籤文字與實際量測的東西已經不完全一致**。要不要改寫那條斷言由你決定。

⚠ **我的疏失**：委派 e2e 修復時沒有隔離 worktree，worker 的 test-only 改動被我的 F154
commit 夾帶進去（commit 訊息與內容範圍不完全相符）。下次平行寫入要用 worktree。

## 驗收環境（更新）

- **Codex 已恢復正常**（2026-08-14 實測 probe 成功）。8/13 那次 41 分鐘零產出是暫時性狀況。
  ⚠ **更正 8/13 的判斷**：當時用「process CPU 只有 0.08 秒」推論它沒在跑，**那個判準是錯的**——
  `codex exec` 幾乎全程在等 OpenAI API，模型跑在對面，本機 CPU 本來就趨近 0（8/14 實測正常運作
  中的 exec 同樣是 0.03 秒）。所以那次到底是真卡死還是只是慢，其實沒有證據。
  `--ephemeral` 不寫 rollout log，也沒有進度檔可看——目前**沒有可靠的即時進度訊號**，
  只能用「合理上限＋逾時中止」處理。
- 純後端驗收 prompt 要明講：不要跑 `init.sh`、不要下載瀏覽器、用絕對路徑
  uv 的絕對路徑跑 pytest、單一指令 5 分鐘無輸出就中止。
- **Android JVM 測試的 task 名是 `:app:testDevDebugUnitTest`**（`testDebugUnitTest` 會 ambiguous 失敗）。
- pytest 的結尾 summary 行在本機終端會被吞掉（cp950），**以 exit code 為準**。

## 工作區注意

- E1 尚未全通過，**不得提前發布**正式站或正式 APK metadata；repo assets 與 Drive 測試 APK 為 v151
- F145 動到 `app/static/`，**改 passing 時要出一顆 APK**；F154 是純後端，不必出

## ⚠ 要 Ryan 裁決：F145 的第 9 條

acceptance：「衝突情境以 **Android ↔ Web** 為準，兩端 contract tests 全綠」。

驗收者逐條 9/9 pass，但**它自己講明**第 9 條是用寬鬆讀法（雙端各自的 schema contract test
全綠），因為嚴格讀法（真的用 Web 改一筆、Android 推送撞衝突）**現在做不到**——Web 的 REST
寫入還沒進 sync change log，那條整合排在 F146。

讓驗收者放寬凍結 acceptance 換一個 pass，跟直接改 acceptance 是同一件事，所以**沒有自動改
passing**。兩條路擇一：認寬鬆讀法就改 passing 並重簽 acceptance 措辭；認嚴格讀法就等 F146
完成後補一條端對端情境再驗。細節在 `docs/evidence/F145.md`。

## F146 現況（未完，勿當完成）

**已完成**

- server 早就有 Secure/HttpOnly/SameSite=lax cookie、CSRF 比對、domain API 綁 session user、
  登出撤 session（F142 時期）。CORS 是固定白名單且未開 credentials，CSRF token 不會被跨站讀走。
- 新增：**CSRF token 改由 `hmac(LIFTLOG_TOKEN, session_id)` 推導**。原本是隨機值只存 hash，
  結果網頁一重整就再也拿不回來，所有寫入 403。推導值可重算，重整與新分頁都拿得到同一顆，
  不必改 schema、也不必「每次讀就換一顆」（換一顆會讓其他分頁立刻失效——第一版這樣寫，
  當場打爆既有的 logout 測試）。
- `GET /api/auth/session` 對 web session 回 `csrf_token`；Android session 不回（有測試釘住）。
- 前端 `auth.js`：`restoreWebSession` / `signInWeb` / `signOutWeb` / `getWebCsrfToken`。
  網頁不存 access token，只留 CSRF token。503 不當成「未登入」——那會把離線畫成請重新登入。
- `api.js` `authHeaders()`：有 web session 走 cookie＋`X-CSRF-Token`，沒有才退回舊的 Bearer。
  **兩條路併存是刻意的**——舊的單一 token 是 60+ 支既有 e2e 的入口，砍掉就是大規模回歸。

- 網頁 setup：Google 登入為主要動作，API token 留作備援；設定頁有登出。
- `verify_f146.py`：登入 `client=web`／請求帶 CSRF header 不帶 Authorization／
  localStorage 沒有 token／登出帶 CSRF／服務中斷顯示專用訊息。**全過**。
- 開站離線訊息**不能放 `state.error`**——頂層的 `guard(confirmActiveWorkout)` 會把它清掉。

**還沒做（就是要裁決的那兩件）**

- Playwright 的「CSRF 拒絕」與「兩帳號隔離」：需要真 Google session，瀏覽器裡造不出來
- 決定要不要保留 API token 輸入框當備援（我目前保留，理由同上）

## 驗收環境陷阱（沿用，別再踩）

- **Codex 這場卡死**：`/codex-verify` 跑 41 分鐘零產出、process CPU 只有 0.08 秒，已 `TaskStop`。
  F152／F145 都退回 `acceptance-verifier`（同模型 fresh context，**獨立性降級已記在證據檔**）。
- 純後端驗收 prompt 要明講：不要跑 `init.sh`、不要下載瀏覽器、用絕對路徑
  `"C:\Users\user\.local\bin\uv.exe" run pytest -q`、單一指令 5 分鐘無輸出就中止。
- **Android JVM 測試的 task 名是 `:app:testDevDebugUnitTest`**，`testDebugUnitTest` 會因
  flavor ambiguous 直接失敗；`-p android` 不加 `:app:` 只會跑到 capacitor 子模組（NO-SOURCE）。
- pytest 的結尾 summary 行在本機終端會被吞掉（cp950），**以 exit code 為準**。

## 工作區注意

- E1 尚未全通過，**不得提前發布**正式站或正式 APK metadata；repo assets 與 Drive 測試 APK 為 v151
- 本場只動後端與前端 JS，**尚未出 APK**。F145 動到 `app/static/`，依專案規則
  **F145 改 passing 時要出一顆 APK**（`npx cap sync android` 已跑過）
