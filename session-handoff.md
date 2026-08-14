# session handoff

最後更新：2026-08-14（第三輪）。仍是 **142/155 passing、13 failing**——F149 進行中，尚未改 passing。

## 接手第一件事

**先看下面「等待裁決」那一節，那是 F149 的阻塞點，不解掉不要往下做遷移。**
其餘 F149 子項已完成四塊，證據見本檔「本輪完成」。`.harness/current_feature` 已設為 F149。

## 等待裁決（阻塞 F149 最大的一塊）

F149 的 PRD R8 要求遷移時「替需要同步的既有 entity 補 `sync_id`、version 與 change-log
baseline」，**但那正是 F155 的範圍，而 F155 的 acceptance 還標「待簽核」**。

- `app/models.py:21` 與 `app/migrations.py:47` 都註明「`sync_id` 對既有列是 NULL，回填是 F155 的事」
- F155 acceptance 第 ④ 條「兩邊都有同一筆資料時的取捨規則要在此條簽核時定義，不得靜默覆蓋」
  目前是空的——F149 要做的回填，其行為規則要等這條簽核才存在

已向 Ryan 提三個選項，等他回覆，**不要自行選一條做下去**：

1. F149 遷移只做綁定＋備份＋row count 驗證＋legacy token 作廢，回填留 F155（需重簽 F149）
2. 先簽核並做掉 F155，F149 遷移站在它上面（推薦：prereq F154 已 passing，工作量不變只是順序倒過來）
3. 自行定取捨規則做進 F149（已建議不要——F155 明文說該規則要簽核）

主 session 對第 ④ 條的建議：照 D17「domain 表當唯一事實來源」，domain 版本勝出，
被覆蓋的 sync 層那筆列進摘要給人看，不靜默丟棄。

## 本輪完成（F149 的四塊，均未 commit 前已全綠）

1. **每日 mutation 配額**（PRD R9 唯一沒實作的 quota）
   - 新表 `user_daily_mutations`（control DB）＋ `app/services/quota.py`
   - domain API 每次寫入扣 1、`/api/sync/push` 按批次筆數扣；超額整批擋下回
     **429 `mutation_quota_exceeded` + `Retry-After`**（Android `SyncHttpTransport.java`
     已把 429 列為 retryable，outbox 不會被丟）
   - 計數存 control DB 而非記憶體：記憶體版會讓「重開服務」變成清空配額的手段
   - 用單一 upsert 帶 WHERE 守衛，避免併發各讀舊值而雙雙放行
   - 上限走 `Settings.daily_mutation_limit`（預設 20000），測試可直接覆寫
2. **加密備份與 restore drill**（delegated）
   - `scripts/backup.py`：`VACUUM INTO` 一致快照 → Fernet 加密 → daily/weekly 兩池，
     保留 7／4 份；目的地與來源同盤時警告但不中止
   - `scripts/restore_drill.py`：一律先還原到隔離目錄驗 schema 與逐表 row count；
     只有 `--promote-to-active` 才寫回，且先查 `account_tombstones`，命中拒絕（exit 2）
   - `tests/test_backup.py` 5 條；`docs/operations.md` 營運手冊
3. **容器化與授權**（delegated ＋ 主 session 補洞）
   - `Dockerfile`（python:3.12-slim + uv，只裝 runtime 依賴）、`docker-compose.yml`、
     `.dockerignore`、`LICENSE`（MIT / Ryan Lee / 2026）
   - image 594MB，`up` 到可用約 5 秒，`down` → `up` 資料仍在（具名 volume）
   - **主 session 修正**：worker 版 `env_file: .env` 是必要檔，而 `.env` 是 gitignored
     ——乾淨機器 clone 下來 `docker compose up` 會直接失敗，正好打在 acceptance 情境上。
     改成 `required: false`＋`LIFTLOG_TOKEN: ${LIFTLOG_TOKEN:?...}`。
     **刻意不給 repo 內建預設 token**：公開 repo 的預設密鑰等於人人可讀訓練資料。
     代價是乾淨機器要多一步 `cp .env.example .env` 並填 token——這是對 acceptance
     「可跑」的解釋而非原文，驗收時可能被挑，需要時再跟 Ryan 確認。
4. **英文／繁中公開 README**（第三輪）
   - `README.md` 改為英文主頁，新增 `README.zh-TW.md`；兩邊都有 Local-first／MCP 定位、
     Mermaid 架構圖、Docker quick start 與「為什麼不用 RAG」。
   - 明確標示 pre-release／F149 尚未完成，未把尚未通過的正式發布寫成已完成。
   - README 本地連結與 `docker compose config --quiet` 全綠。

Gates：`uv run pytest` 全綠（備份 worker 實測 404 passed）、`uv run ruff check .` 全綠。

## 尚未完成（F149 剩餘）

1. 既有資料遷移命令（dry-run／備份／回滾／row count 比對）— **被上面的裁決卡住**
2. 舊單一 Bearer token 作廢：`Settings.token` 目前必填且 `app/api/deps.py:_is_legacy_request`
   仍會放行。正式切換後要讓它失效，但 docker demo 模式正好靠這條路徑——兩者要一起設計
3. release-signed APK 全流程冒煙、Web/APK/MCP/schema 版本一致，以及其餘 frozen gates
4. 全部完成後派獨立 review 與 acceptance-verifier 逐條驗收，才可改 passing

`20 帳號×2 裝置隔離／quota` 與每日備份已由 D15 從 F149 release acceptance 降到
`docs/operations.md`，不是剩餘 release blocker；不要再依舊 handoff 把它補回 scope。

## 其他未結項（沿用上一輪）

- `G:\我的雲端硬碟\lift-log-apk` 未掛載，v154 尚未複製到 Google Drive
- `docs/evidence/F146.md` 末段兩個規格裁決（legacy token 是否收掉、Web IndexedDB
  離線佇列與 envelope 字面差異）仍未處理
