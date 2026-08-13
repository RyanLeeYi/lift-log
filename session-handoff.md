# session handoff

最後更新：2026-08-13（第五場，夜間自主執行）。目前 **137/153 passing、16 failing**。

## 下一步（最短入口）

**兩條都卡在同一種東西上：凍結 acceptance 寫的驗證方式做不出來，需要 Ryan 裁決。**

1. **F145 第 9 條讀法**（寬鬆＝雙端 schema contract test，嚴格＝真的 Android↔Web 端對端）。
2. **F146 的 Playwright「CSRF 拒絕」與「兩帳號隔離」**：要嘛開一個測試用 Google verifier
   注入點（＝在認證路徑上開後門），要嘛改 acceptance 讓 server 端測試負責。細節在
   `docs/evidence/F146.md` 最後一節。
3. 裁決前可以先做的：**native 模擬路徑的 e2e 是壞的**（`verify_f61`／`f81`／`f110` 都卡在
   `wait_for_selector("input")`），且**在這場之前就壞了**（已用 worktree 比對 `62705ae` 確認）。
   值得單獨開一條修。
4. 之後依序 F147 → F148 → F149 → F153，再處理 10 條舊債。

## 這場做了什麼

| commit | 內容 |
|---|---|
| `7633003` | F152 改 passing（dry-run 摘要，驗收 6/6） |
| `e464544` | F145 實作：衝突收件匣 ＋ 保留本機／採用雲端 |
| `4edd796` `62705ae` | F145 證據歸檔（狀態仍 failing，理由見下） |
| `906e367` | F146：web CSRF token 改由 session id 推導 |
| `014b48d` | F146：網頁 cookie session client（`auth.js` ＋ `api.js`） |
| `1365787` | F146：網頁 Google 登入畫面、登出、服務中斷提示、`verify_f146.py` |
| `8d2dcaa` | F146：既有 e2e helper 改成指名點「連線」（setup 第一顆按鈕換成 Google 登入了） |
| `20df34a` | F146 證據歸檔（狀態仍 failing） |

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
