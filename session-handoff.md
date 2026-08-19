# session handoff

最後更新：2026-08-19。**150/158 passing、8 failing**（F89、F95、F104、F105、F124、F128、F149、F153）。
`.harness/current_feature` = F136（已 passing，下一條開工時覆寫）。線上正式站仍跑 `e8ff575`（F157）——**本輪 6 個 feature 尚未部署**。

## 接手第一件事

1. `git log --oneline -3` 對 origin/main（本輪已 push 到 `4f6cf11`），確認沒有第二個 session 在動 repo。
2. **部署**：本輪合併了 F158（MCP token UI＋唯讀／到期）、F136、F86–F88 的測試翻新與 v155 升號，
   正式站還沒跑 `scripts/deploy.ps1`。部署前跑一次 `uv run pytest`（447）。
3. Ryan 手機：`G:\我的雲端硬碟\lift-log-apk\lift-log-v155-F158-F136.apk` 是新版（設定頁多了 MCP token 管理）。

## 本輪完成（2026-08-19，主 session ＋ 平行 executor／verifier）

| feature | 做了什麼 | commit | 驗收 |
|---|---|---|---|
| F86 | ⑩ verify_f59/f60 改共用 helper（畫面 07/30 早已實作） | `553a27e` | 10/10 pass |
| F87 | ⑭ verify_f53–f58 改共用 helper | `f12e058` | 15/15 pass |
| F88 | ⑩ verify_f48–f52 改共用 helper | `8b307fa` | 10/10 pass |
| F158 | 第二段 read_only 授權邊界（主 session）`9d05e0e`；第三段 UI＋API 欄位 `1ec40db`；review 修正 `cdee86b`；APK v155 | 見左 | 8/8 pass＋2 P2 已修並 recheck |
| F136 | 折線圖鍵盤／SR 存取 | `282f1b7` | 5/5 pass（TalkBack unverified） |

隔離區 13 支 E2E 全數翻新完畢，`tests/e2e/README.md` 那節可在下次順手改成歷史說明。
證據都在 `docs/evidence/F<id>.md`；整條原文在 `docs/archive/features.jsonl`。

**平行派工實測**（供 harness 決策）：F86‖F158 零耦合同時派，主 session 同時做 F158 第二段；
executor 12–40 分、verifier 7–28 分；一次 API 521 中斷 worker（worktree 內容保住，SendMessage 續派即可）；
唯一合併衝突是 `tests/e2e/README.md` 兩個 worker 各改同一段（一分鐘手解）。
教訓：派驗收者不要要求 `git stash`（與 verifier-bash-guard 衝突，它會改用 clone 等效驗證）。

## 尚未完成

### F149 剩餘

1. release-signed APK 全流程冒煙：真登入、完整離線訓練、衝突處理、換裝置、MCP、匯出、刪帳
2. Web/APK/MCP/schema 版本一致
3. 派獨立 review 與 `acceptance-verifier` 逐條驗收，才可改 passing

## 記帳（不阻塞，但別忘）

- app 內建自我更新（F67）按「立即更新」後沒有動作，server log 也沒有下載請求。
  **這是一條沒查完的線索**，可能只是「安裝未知應用」權限沒開
- `scripts/backfill_sync.py` 的快照目錄用秒級時間戳，同一秒重跑會撞 VACUUM INTO 目的檔已存在
- `docs/evidence/F146.md` 末段第 2 項仍未處理
- v154 從未複製到 Google Drive；v155 已在（2026-08-19）
- **不要整份 `Read` `feature_list.json`**（334KB）。理由與挑欄位指令見 `CLAUDE.md` 工作規則 #1
- 正式站目前跑 `e8ff575`（F157）。前端版號仍是 v154——F156/F157 都只動後端，不需要新 APK
