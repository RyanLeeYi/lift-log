# session handoff

最後更新：2026-08-20（第二輪）。**151/160 passing、9 failing**（F89、F95、F104、F124、F128、F149、F153、F159、**F160 新**）。
`.harness/current_feature` = F159。

## 接手第一件事

1. **F159 只差一件事：實機冒煙。** 程式碼全部完成並驗證，正式站與 APK 都已是 v156。
   卡在手機 app 停在 Google 登入頁——那一步只有 Ryan 本人能做（agent 不得代輸憑證）。
   Ryan 登入後，冒煙流程見下面「F159 剩下的一半」。**沒做完之前不得改 passing。**
2. `git log --oneline -3` 對 origin/main（本輪已 push 到 `4474496`），確認沒有第二個 session 在動 repo。
3. **F160 是草案、未簽核**，動工前要 Ryan 逐條看（`delegation-warmup` hook ③ 也會擋沒簽核的派工）。

## 本輪完成（2026-08-20 第二輪）

### F159 — 程式碼完成，等實機冒煙

Ryan 簽核凍結 acceptance 後派兩個平行 `executor`（各自 worktree，檔案零重疊），
主 session 整合＋覆核。證據 `docs/evidence/F159.md`。

| commit | 內容 |
|---|---|
| `51faf4c` / `dc3e7b5` | worker 實作：pull 路徑 null-safe、`exercises.mode`、`sets` 整表重建（v3→v4） |
| `23e110c` | **P2 修正**：原生浮動視窗的快記貫通 mode |
| `fc9e00c` | 3 條 P3 護欄：DB 層互斥 CHECK、指紋涵蓋率、冪等依據 |
| `4ee3d5c` | bump v156 |
| `4474496` | 證據補寫 ＋ 開 F160 |

**最值得記的三件事**

1. **`/code-review` 抓到 `acceptance-verifier` 抓不到的 P2**，而且波及範圍比第一眼大得多。
   時間型動作的 `state.reps` 裝的是秒數（`app.js:2520` 才在 API 邊界轉成 `duration_seconds`），
   但浮動視窗的快記把它原樣寫進 `reps` 欄 → server 回 422。
   **關鍵在後果**：`SyncClient.java:96` 把 422 交給 `LocalStore.markPushPermanentFailure(body, …)`，
   而它（`LocalStore.java:875-891`）是 for 迴圈把 body 裡**每一筆** mutation 標成永久失敗，
   batch 上限 500。一筆壞資料會靜默帶走同批最多 499 筆無關紀錄。
   **兩種檢查看的是不同的東西**：驗收看「acceptance 逐條有沒有做到」（①–⑦ 全 PASS 是對的），
   review 看「這段程式碼會不會壞」。strict 檔位兩個都跑不是重複。
2. **worker 踩到的 SQLite 語法規則**：`CREATE TABLE` 的表級約束必須排在所有欄位定義之後，
   插在欄位中間會 `near "rpe": syntax error`（29/36 測試直接紅）。
3. **重建保真度指紋原本只涵蓋 14 欄中的 4 欄**，把 `deleted_at` 與 `created_at` 對調會完全通過——
   而那正是它宣稱要擋的故障。已擴到 13 個聚合值。
   **限制要知道**：純聚合統計量對「值分佈對稱的兩欄互換」天生看不出來，這是手法的極限。

### 部署與維運

- **正式站 `800c0e2`（v155）→ `6451b35`（v156）**，F105 時間型動作正式上線。
- **`scripts/deploy.ps1` 的 health 門檻 30s → 180s**，並印出實際啟動耗時。
  本輪第一次部署被誤判回退（log 明明有 `Uvicorn running on 0.0.0.0:8137`），
  正式站因此有約 4 分鐘不可用。
  ⚠ **但重跑時只花 24 秒，比舊門檻還短**——所以根因是「卡在邊界」而不是「穩定超時」。
  下次要不要再調，看腳本現在會印的那個數字，不要憑感覺。
- APK v156 已裝上實機（`versionCode=156`、`SITE=prod` 都用 `unzip` 核對過，
  避開 `apk\release\app-release.apk` 那顆殭屍檔）。

### 平行派工實測（供 harness 決策）

兩個 worker、檔案零重疊、零合併衝突。耗時 7.6 / 12.3 分鐘。
**主 session 覆核 worker 的非顯而易見主張仍然抓到東西**：A 把 `addSet` 寫成 if/else 兩支、
10 個參數重複兩遍，收成單次呼叫（用 `Integer` 先裝箱避開三元的 unboxing 陷阱）。

上一輪的教訓仍然成立：worker 說「這不是我造成的」時，要用它動不到的那個變因去驗。

## F159 剩下的一半

acceptance ⑦ 的實機冒煙，狀態 `unverified (人工)`。Ryan 在手機上登入後：

1. 網頁（或手機 app）建一個**時間型動作**，記一組
2. 手機同步 → 看得到那筆，且**既有次數型資料照常同步**
3. 浮動休息視窗對時間型動作顯示「N 秒」、步進 ±5，按「完成這組」後那筆能成功 push（不是 422）

補充：`app/services/sync.py::pull` **沒有 device 過濾**，回的是 cursor 之後的所有變更，
包含裝置自己 push 上去的。所以在手機上建時間型資料，也會再 pull 回來走一次
`applyRemoteUpsert`——原本會拋 `JSONException` 卡死 cursor 的正是那條路徑。
換句話說「手機建」也驗得到根因，不是非得從網頁建不可。

⚠ 正式站現在**已經**支援時間型動作。任何還在跑 v155 以下 APK 的裝置，
一旦 pull 到時間型資料就會卡死 cursor。目前只有 Ryan 這一支，且已升到 v156。

## 尚未完成

### F160（新開，未簽核）— 單筆 mutation 被拒不得連坐整批

由 F159 的 review 發現、主 session 開檔驗證。連坐機制**是既有設計，不是 F159 引入的**；
F159 只是讓它第一次有具體觸發路徑。動工前要先確認 server 的 422 回應
**帶不帶得出出錯的 mutation_id**——帶不出來的話這條的範圍要跟著改，
不得用「猜第一筆」或「全部保留」草草了事（後者會變成無限重試同一筆毒藥）。

### F149 剩餘

1. release-signed APK 全流程冒煙：真登入、完整離線訓練、衝突處理、換裝置、MCP、匯出、刪帳
2. Web/APK/MCP/schema 版本一致
3. 派獨立 review 與 `acceptance-verifier` 逐條驗收，才可改 passing

F159 解除封鎖後這條就能繼續（APK 已是 v156）。

### 通知家族合併（Ryan 2026-08-20 決定）

F89 / F104 / F128 三條合併成一條——它們的 `touches` 是同一批原生檔
（`RestOverlay.java`／`RestTimerService.java`／`RestTimerPlugin.java`），分開做等於同一段程式碼改三次。
**還沒動筆**，因為本輪 P2 正在改那三個檔，寫規格會對著即將過期的程式碼寫。現在可以動了。

合併後有一個問題需要 Ryan 拍板：**F128 ⑥ 的樂觀倒數代價**選 (a) 接受、還是
(b) 多做一條「這組沒記到」的回報路徑。F128 目前仍是未簽核草案。

## 記帳（不阻塞，但別忘）

- **`verify_f92.py` 的 6 條失敗已修**（本輪第一段）。根因是 F154 把 `delete_workout`
  改成軟刪，但 `list_workouts` 沒跟著過濾。修在 `app/services/workouts.py`（`6347a31`），
  附紅→綠回歸測試。verify_f92 9/15 → 15/15。
- `verify_f144.py` 需要手動起固定 port 8765 的伺服器才能跑，驗收時被跳過。
- app 內建自我更新（F67）按「立即更新」後沒有動作，server log 也沒有下載請求。
  **這是一條沒查完的線索**，可能只是「安裝未知應用」權限沒開
- `scripts/backfill_sync.py` 的快照目錄用秒級時間戳，同一秒重跑會撞 VACUUM INTO 目的檔已存在
- `docs/evidence/F146.md` 末段第 2 項仍未處理
- **不要整份 `Read` `feature_list.json`**。理由與挑欄位指令見 `CLAUDE.md` 工作規則 #1
- **正式站與 APK 都是 v156。** F159 改 passing 後照 `CLAUDE.md` 規則 6 把 APK 丟
  `G:\我的雲端硬碟\lift-log-apk\lift-log-v156-F159.apk`（本輪還沒丟，因為 F159 未 passing）
