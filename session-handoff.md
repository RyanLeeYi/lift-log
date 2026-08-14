# session handoff

最後更新：2026-08-14（額度 93% 收工）。目前 **137/155 passing、18 failing**。

## 下一步（最短入口）

1. **F154 第四輪重驗**（前三輪各抓到一個 fail，都已修）。這一輪要驗的是第三處修正
   （`delete_template` 逐筆 record_write，commit `f4fba95`），以及**還有沒有第四處同款漏洞**。
   派 `acceptance-verifier`，要它同時掃 `session.add(` 與 `session.execute(update(` / `.execute(delete(`
   兩種寫法——前三次證明只掃 ORM add 會漏。
2. 全 pass 才把 F154 改 passing（`docs/evidence/F154.md` 已寫好三次 fail 的來龍去脈）。
3. 然後：F145 用嚴格讀法重驗、F146 重驗（缺的 change log 整合已由 F154 補上）、
   F147 → F148 → F149 → F153 → F155 → 10 條舊債。

## F154 的三次 fail（同一個失敗模式，三個位置）

**domain 寫入沒進 change log**，而既有測試全綠——因為沒人交叉看那條路徑。這正是 F154 要
消滅的東西，卻在實作 F154 時連犯三次：

| # | 位置 | 影響 | commit |
|---|---|---|---|
| 1 | `app/seed.py` | 新帳號的 35 筆種子動作手機永遠 pull 不到 | `0fcac6d` |
| 2 | `_log_workout`（`/api/workouts/batch`、**MCP `log_workout` 唯一入口**） | 透過 AI 對話記的組完全同步不到手機 | `84f09b2` |
| 3 | `delete_template()` 的 bulk `UPDATE workouts SET template_id=NULL` | 被解除關聯的 workout 版本停滯、payload 停在舊狀態 | `f4fba95` |

**#2 的根因是我寫的反模式**：先 `session.flush()` 再用 `session.new` 反查剛寫的列——flush
已經把它們移出集合。**不要用 session 集合狀態反查寫了什麼，要明確收集。**

**#3 的方法論教訓**：`grep session.add(` 抓不到 `session.execute(update(...))` 這種 raw SQL 寫入。
兩種都要掃。

三條回歸測試都已補進 `tests/test_sync_domain_bridge.py`（共 8 條），且驗收者獨立確認過
第二條在修正前的舊碼上真的會紅。

## 2026-08-14 的十題裁決（grill）

1 做 change-log 整合／2 F146 Playwright 範圍改由 server 端測試負責（acceptance 已重簽）／
3 Google session 與 API token 兩條路都留／4 之後的 feature 用跨模型（**現已不適用**，見下）／
5 三支 native e2e 修掉（已修）／6 **domain 表當 SSOT**（vault D17）／7 acceptance 新措辭簽核／
8 開新 feature F154／9 domain 表加三欄位／10 既有資料先不回填（F155）。

## 驗收環境（重要更新）

- **Codex 整條路徑已於 2026-08-14 從全域 rules 移除**。驗收一律走 `acceptance-verifier`
  （同模型 fresh context，**不得寫成跨模型獨立驗收**）。不要再提議裝回 Codex。
- 移除前查到的真因供參考：`codex exec` 的指令執行全走 code-mode host，而那個 host
  `exited during handshake`；關掉它只會變成 `code-mode host is disabled`。
- **判斷背景程序是否卡死不能看 CPU 時間**——網路密集的 client 本來就趨近 0。
- **Android JVM 測試 task 名是 `:app:testDevDebugUnitTest`**（`testDebugUnitTest` 會 ambiguous 失敗）。
- pytest 結尾 summary 在本機終端會被吞掉（cp950），**以 exit code 為準**。

## 委派注意（這場踩到）

平行委派時**沒有隔離 worktree**，worker 的 test-only 改動被主 session 的 commit 夾帶進去，
commit 訊息與內容範圍不符。下次平行寫入一律用 worktree。

## 待 Ryan 決定（不急）

`verify_f61` 原本用真正的 REST round-trip 驗「app 版打公開站」，但 F131 之後 native 的 domain
資料走 LocalStore、不打網路，現在那條 `count>0` 量的是 LocalStore 假資料。`/health` 與
`/api/app/latest` 仍實際打公開站，斷言還有真實請求撐著，但標籤文字與實際量測的東西不完全一致。

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
