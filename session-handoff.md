# session handoff

最後更新：2026-08-20。**151/159 passing、8 failing**（F89、F95、F104、F124、F128、F149、F153、**F159 新**）。
`.harness/current_feature` = F105（已 passing 並歸檔）。

## 接手第一件事

1. **不要部署，也不要出 APK**。正式站現在跑 `800c0e2`（v155），F105 的程式碼在 main 但**刻意還沒上線**。
   理由見下面 F159：正式站一旦存在任何一筆時間型組，既有 Android 裝置的同步 pull cursor 會永久卡死。
   **F159 完成才解除這個封鎖。**
2. `git log --oneline -3` 對 origin/main（本輪已 push），確認沒有第二個 session 在動 repo。
3. F159 的 acceptance **尚未簽核**——動工前要 Ryan 逐條確認（`delegation-warmup` hook ③ 也會擋沒簽核的派工）。

## 本輪完成（2026-08-19 → 08-20）

### 部署與維運

- 正式站從 `e8ff575` 推到 `800c0e2`（v155，含 F158／F136／F86–F88），先前落後 6 個 feature。
- **mission-control supervisor 修復**：進程活著但 18600 的 listener 死了，排程工作顯示 Running、
  `LastTaskResult 0x800710E0`（任務已在執行）永遠不會重跑，所以它不會自癒。
  砍掉整棵進程樹重啟排程工作解決。**這是 mission-control 的洞**（它的 health 只看子服務、不看自己），
  值得在那個 repo 開一條。

### F105 時間型動作 — passing

一條 feature 切五塊：後端契約（主 session）＋四個平行 worktree worker＋主 session 補縫。
證據 `docs/evidence/F105.md`，整條原文在 `docs/archive/features.jsonl`。

| commit | 內容 |
|---|---|
| `d07b3e1` | 後端契約：`exercises.mode`、`sets.duration_seconds`、`sets.reps` 去 NOT NULL |
| `c499678` | 四個 worker 合併＋整合縫隙 |
| `4b1741e` | **獨立驗收擋下的 P0 修正**（sync push 整批報廢） |
| `e563228` | 證據 |

**最值得記的三件事**

1. **SQLite 沒有 ALTER COLUMN**，`reps` 要變 nullable 只能整表重建。重建的自我檢查一開始寫成
   `PRAGMA foreign_key_check`，結果誤判——F151 之前的舊表**沒有 FK 子句**，重建後才有，
   於是既有孤兒列在重建後「首次」被報出來、看起來像是這次弄壞的。改成比對複製保真度指紋
   （筆數＋相異鍵數＋各欄位加總）才對。同理 `created_at` 刻意不加 NOT NULL：**重建不該比它取代的那張表更嚴格**。
2. **獨立驗收擋下一條我自己的 P0，而且是四個 worker 都不可能發現的那種**：
   `assert_set_matches_mode` 拋的 `UnprocessableError` 不是 `ValueError` 家族，
   `sync.py::_process()` 沒攔到 → 整個 sync push request 變 422 → commit 跑不到 →
   同批裡完全合法的 mutation 一起被 rollback。**根因是 `sync.py` 不在 F105 的 `touches` 清單**，
   所以四張派工單都沒涵蓋它。派工前的 ownership map 只照 `touches` 填，`touches` 漏了就整條路徑沒人看。
3. **平行派工的邊界是我切錯的，不是 worker 的錯**。三個 worker 各自在邊界停下回報：
   W4 說「自訂動作的 mode 選擇器在 `custom-exercise.js`，不在我的 may-write」、
   W4 說「首頁摘要需要 `schedule.py` 補欄位」、W2 說「日曆補記與課表批次還沒分流」。
   三條都對，三條都是我派工單漏的。**worker 停在邊界回報比自己動手好**，這次的機制是有效的。

### 平行派工實測（供 harness 決策）

四個 worker 零合併衝突（may-write 互斥、各自 worktree）。耗時 12–34 分鐘不等。
主 session 在等待期間只做「不碰它們檔案」的事。W2 宣稱 `verify_f92.py` 的 6 條失敗是既存問題，
但它的驗法（stash 掉自己的檔案）證不到——**主 session 用 `800c0e2` 開臨時 worktree 實測才確認**。
教訓：worker 說「這不是我造成的」時，要用它動不到的那個變因去驗，不是用它的檔案去驗。

## F159（新開，未簽核）— Android 原生本地儲存支援時間型動作

`LocalStore.java::applyRemoteUpsert()` 的 `case "set"` 用 `payload.getInt("reps")` 讀一個
現在可能為 null 的欄位（同一段的 rpe／rest_seconds 用的是 null-safe 的 `putJsonNullableInteger`）。

放大原因是 `applyPullPage()` 「change apply 與 cursor commit 共用同一個 transaction，
任一 change 壞掉整批回滾」（該檔既有註解與既有測試 `pullPageAndCursorCommitTogether` 都證實）。
所以後果不是「時間型的組存不進去」，而是**該裝置的 pull cursor 永久卡在那一頁之前**，
連同頁之後所有正常的次數型資料一起擋住，不會自我恢復。

Ryan 2026-08-20 裁決此項為 F105 的 out-of-scope，另立 F159。完整 acceptance 在 `feature_list.json`。

## 尚未完成

### F149 剩餘

1. release-signed APK 全流程冒煙：真登入、完整離線訓練、衝突處理、換裝置、MCP、匯出、刪帳
2. Web/APK/MCP/schema 版本一致
3. 派獨立 review 與 `acceptance-verifier` 逐條驗收，才可改 passing

⚠ F149 的 APK 冒煙要等 F159——現在出的 APK 碰到時間型資料會卡同步。

## 記帳（不阻塞，但別忘）

- **`verify_f92.py` 有 6 條失敗，與 F105 無關**（已用 `800c0e2` 實測確認既存）。
  失敗集中在「按開始訓練後伺服器場數」「一組都沒記就結束該被刪」「有記組不得被刪」，
  看起來是 F91／F92 的結束訓練流程有東西壞了，沒人在追。值得開一條。
- `verify_f144.py` 需要手動起固定 port 8765 的伺服器才能跑，驗收時被跳過。
- app 內建自我更新（F67）按「立即更新」後沒有動作，server log 也沒有下載請求。
  **這是一條沒查完的線索**，可能只是「安裝未知應用」權限沒開
- `scripts/backfill_sync.py` 的快照目錄用秒級時間戳，同一秒重跑會撞 VACUUM INTO 目的檔已存在
- `docs/evidence/F146.md` 末段第 2 項仍未處理
- **不要整份 `Read` `feature_list.json`**。理由與挑欄位指令見 `CLAUDE.md` 工作規則 #1
- 正式站目前跑 `800c0e2`（v155）。APK 也是 v155
