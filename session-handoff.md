# session handoff

最後更新：2026-08-13（第四場）。目前 **136/153 passing，17 failing**。
**F151 已 passing**（commit `bd75c8b`）；**F152 實作完成但仍 failing，只差一條重驗**。

## 下一步（最短入口）

1. **F152 收尾**：acceptance 的 N 值已補簽核為 5（見下），實作本來就是 5，**不用改 code**。
   只要重跑一次跨模型驗收確認第 2 條（preview 筆數）由 `untestable` 轉 `pass`，就能改 passing。
2. **跑驗收時不要跑 `init.sh`**——見下方「驗收環境陷阱」。
3. 之後依序 F145 → F146 → F147 → F148 → F149 → F153，再處理 10 條舊債。

## F151 收工（2026-08-13 passing，commit `bd75c8b`）

`sets` 新增 nullable `idem_key` = `sha256(date|exercise_id|set_number)` 配 partial unique index
（`idem_key IS NOT NULL AND deleted_at IS NULL`）。整批命中時**連 `Workout` 列都不新建**；
部分命中時新組併入既有鍵所屬的 workout（不另開孤兒 workout）。`LogWorkoutSummary` 加
`created_count`／`skipped_count`。既有列不回填，`idem_key` 維持 NULL。
`DOMAIN_SCHEMA_VERSION` 2 → 3。

Codex 跨模型驗收 **6/6 pass**、驗收前後 `git status` 逐字相同。證據 `docs/evidence/F151.md`。

⚠ **已知規格上限**：鍵是 date-scoped，**同一天真的分兩次練同一動作，第二次的第 1 組會被誤判為
重送**。凍結 acceptance 明定用 `date+exercise+set_index`，兩個模型獨立驗收都提出同一點。
決定不改鍵，靠 F152 的 dry-run 當煞車。

## F152 現況（實作完成，**尚未 passing**）

`POST /api/workouts/batch` 加 `dry_run: true` → 回 **200**（不是 201）與
`will_create_count`／`will_skip_count`／`will_conflict_count`＋前 5 筆 `preview`。

- F151 的判斷邏輯抽成 `_plan_batch`，dry-run 與實際寫入**共用同一份**，沒有第二套規則
- `session.rollback()` 放 `try/finally`，`create_missing` 拋例外時也不留 Exercise 列
- `conflict` ＝ idem_key 沒命中但目標 workout 已有同 `(exercise_id, set_number)` 未刪組
  （來源是 F151 之前、`idem_key` 為 NULL 的舊資料）
- 驗證：`uv run pytest` **362 passed**、ruff clean、encoding **63/63**

**驗收結果 4/5 pass、1 untestable**（報告在 scratchpad `codex-verify-F152-retry.md`）：
acceptance 原文只寫「前 N 筆預覽」未定義 N，驗收者無法判定筆數。**Ryan 已於 2026-08-13
補簽核 N = 5**，`feature_list.json` 的 acceptance 已更新為
「`preview` 回傳 `min(len(sets), 5)` 筆，恰為原 payload 的 index `0..N-1`」。
實作本來就是 5，**不需要改任何程式碼**，只要重驗這一條。

已知邊界（不影響 acceptance，寫給下一個 agent）：dry-run 只看冪等鍵層，不看 `client_uuid`
重放層。F151 之後的資料兩層結論一致；只有「F151 之前寫入、`idem_key` 為 NULL 又帶同一個
client_uuid」的舊資料會出現 dry-run 說 create、實寫判定為重放的落差。

## ⚠ 驗收環境陷阱（這場踩到，燒掉一次 Codex 額度）

第一次 `/codex-verify` **整輪零產出**：`init.sh` 在 `playwright install chromium` 那步
**無 stdout 卡死逾 5 分鐘**，Codex 依指示中止，逐條全部 `unverified`。

**純後端 feature 的驗收 prompt 要明講**：
- 不要跑 `init.sh`、不要執行任何會下載瀏覽器的指令（環境已就緒）
- 直接用絕對路徑 `& "C:\Users\user\.local\bin\uv.exe" run pytest -q`
- 單一指令 5 分鐘無輸出就中止、記為 blocked、繼續下一項，不要卡在同一個指令上

加上這三句後重試，三個指令 **45 秒內**全部跑完。

## 這場的流程變更（已落地，不用重做）

委派規則加了執行上限與保溫機制，寫在 `~/.claude/rules/common/agents.md` 與 vault
`templates/軟體開發/HARNESS.md`：50 分鐘上限（卡在主對話 1 小時 prompt cache TTL 之內）、
委派同輪排 `ScheduleWakeup` 保溫、停止條件寫進派工單、涵蓋 `Agent` 派工與
`/codex-verify` 等所有外包。細節見那兩份檔案。

## 工作區注意

- E1 尚未全通過，**不得提前發布**正式站或正式 APK metadata；repo assets 與 Drive 測試 APK 為 v151
- F151／F152 都是後端 only，未動 `app/static/`，依專案規則不必出 APK
