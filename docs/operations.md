# 備份與 Restore Drill 營運手冊

支援 F149／PRD R9。腳本在 `scripts/backup.py` 與 `scripts/restore_drill.py`，純 Python
（`uv run python` 執行），Windows 家機與 Linux 容器共用同一套。

## 1. 金鑰

備份用 [Fernet](https://cryptography.io/en/latest/fernet/) 對稱加密（`cryptography` 套件，
已在既有依賴樹裡，沒有新增相依）。金鑰只透過環境變數 `LIFTLOG_BACKUP_KEY` 讀取——不寫進
程式、log、檔名或這份文件。

產生一把新金鑰：

```powershell
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

把輸出存進密碼管理器；備份與 restore 都要用同一把。金鑰遺失＝所有備份無法解密，等同沒有備份，
所以務必和 `.env` 分開保存一份離線備份。跑排程時只在執行當下的 process 環境注入
`LIFTLOG_BACKUP_KEY`，不要寫進 `.env`（`.env` 會被 `git status` 檢查到、也可能被其他流程印出）。

## 1b. 正式站的實際位置（F161）

正式站整包住在 git 工作樹**之外**，所以在 repo 跑 `git clean -xdf` 不會碰到它：

```
SideProject\lift-log\        <- 開發工作樹；測試站(8138)吃這裡，可隨意清
SideProject\lift-log-prod\   <- 正式站(8137)
  current\  previous\        程式碼快照（deploy.ps1 換名切換）
  .venv\  .venv-previous\    依快照 uv.lock 建的環境，與程式碼同進同退
  .env                       正式站設定
  data\control.db  data\users\
  release\
```

兩件容易踩到的事：

- **任何維運指令都要從 `lift-log-prod` 跑**，否則 `.env` 讀不到、會靜默套用開發預設值。
- mission-control 啟動正式站用的是 `.venv\Scripts\python.exe -m uvicorn`，**不是**
  `uvicorn.exe`。uv 建的 `.exe` shim 把自己 venv 的絕對路徑寫死在裡面，換版時
  `.venv-staging` 改名成 `.venv` 會讓它壞掉（只印一行 `Failed to canonicalize
  script path` 就結束）。`python.exe` 靠 `pyvenv.cfg` 與自身位置解析，不受改名影響。

## 2. 每日備份怎麼排程

`scripts/backup.py` 每次執行對 control DB 與 `LIFTLOG_USER_DATA_DIR` 下每個 `<uuid>.db` 各產生
一份加密快照，寫進 `--dest-dir` 底下的 `daily/<name>/` 與（週一另外再寫一份）`weekly/<name>/`。

**一定要從正式站那一側跑**（F161 起）。`Settings` 讀的是「當下工作目錄的 `.env`」，
而正式站的 `.env` 已經隨整個正式站搬出 git 工作樹。在 repo 裡跑會靜默套用預設值
（`./control.db`、`./users`）——備份看起來成功，備到的卻是開發用的檔案：

```powershell
$prod = "C:\Users\user\OneDrive\Desktop\SideProject\lift-log-prod"
$env:LIFTLOG_BACKUP_KEY = (Get-Content <金鑰檔路徑> -Raw).Trim()
Set-Location $prod                       # <- .env 從這裡讀
& "$prod\.venv\Scripts\python.exe" "$prod\current\scripts\backup.py" --dest-dir D:\lift-log-backups
```

用的是正式站自己的 `.venv` 與快照裡的 `scripts\backup.py`，整條路徑都不碰工作樹。

`--control-db` 與 `--user-data-dir` 預設讀 `Settings`（即 `.env` 的
`LIFTLOG_CONTROL_DB_PATH` / `LIFTLOG_USER_DATA_DIR`），通常不必另外指定。

**Windows（Task Scheduler）**：建一個每日觸發的工作，動作是執行

```powershell
powershell.exe -NoProfile -Command "$env:LIFTLOG_BACKUP_KEY = (Get-Content <金鑰檔路徑> -Raw).Trim(); $prod = 'C:\Users\user\OneDrive\Desktop\SideProject\lift-log-prod'; Set-Location $prod; & \"$prod\.venv\Scripts\python.exe\" \"$prod\current\scripts\backup.py\" --dest-dir D:\lift-log-backups"
```

金鑰檔本身要被排除在任何雲端同步／git 追蹤之外，且與家機 DB 不同顆磁碟（見第 4 節）。

**Linux 容器（cron）**：

```
0 3 * * * LIFTLOG_BACKUP_KEY="$(cat /run/secrets/liftlog_backup_key)" cd /app && uv run python scripts/backup.py --dest-dir /mnt/backup-volume
```

`--now` 只在補跑或測試時手動指定 ISO-8601 時間戳；正常排程不要帶，讓腳本用當下 UTC 時間，
保留策略與週一判定才會準。

## 3. 保留策略

daily 池留最新 **7 份**、weekly 池留最新 **4 份**（每週一額外多寫一份進 weekly 池）；每次執行
結束都會清掉各自池子裡超出份數的最舊檔案。兩個池子互相獨立，所以「四週前的週一快照」即使
daily 池已經被清掉，仍留在 weekly 池裡——這就是每日高頻保留＋每週長期保留的用意：daily
池撐得住「昨天手滑刪錯資料」，weekly 池撐得住「一個月前的迴歸要對照」。

備份快照一律用 SQLite `VACUUM INTO` 產生，不直接複製 `.db` 檔——這個專案的 DB 開 WAL，
直接複製檔案可能拿到寫入中途的不一致狀態；`VACUUM INTO` 是 SQLite 官方提供、在同一個唯讀
transaction 內產生一致快照的做法。

## 4. 磁碟分離

`--dest-dir` 理論上不能與 active DB（`LIFTLOG_CONTROL_DB_PATH`、`LIFTLOG_USER_DATA_DIR`）在
同一顆實體磁碟——同一顆磁碟故障時，備份會跟著資料一起沒了，備份就失去意義。腳本用
`os.stat().st_dev` 比對來源與目的地是否同一顆磁碟；偵測到同盤只印警告、**不中止**備份：

- 停止備份代表「今天完全沒有備份」，比「今天的備份放錯磁碟但至少存在」更糟——後者至少在
  「DB 損毀但磁碟沒壞」的情境下還能救。
- 判斷同盤與否需要人的常識（外接硬碟、NAS 掛載、雲端同步資料夾算不算「同一顆」見仁見智），
  腳本用 `st_dev` 做技術判斷，實際部署仍要營運者自己確認 `--dest-dir` 真的指向另一顆磁碟
  （建議：另一顆實體硬碟或異地 NAS／雲端儲存掛載點）。

## 5. Restore Drill 怎麼跑

`scripts/restore_drill.py` 一律先還原到 `--restore-dir` 指定的**隔離目錄**，驗證 schema
（比對 `app.models.Base` / `app.control_models.ControlBase` 的資料表清單）與（有 `--source-db`
時）逐表 row count 一致，兩者任一失敗都會印錯誤、回傳非 0 exit code。

```powershell
# 驗 control DB 備份
uv run python scripts/restore_drill.py --db control `
  --backup-dir E:\lift-log-backups --restore-dir C:\temp\restore-drill

# 驗某個 user DB 備份，並比對回產出當下的來源 row count
uv run python scripts/restore_drill.py --db <user-uuid> `
  --backup-dir E:\lift-log-backups --restore-dir C:\temp\restore-drill `
  --source-db C:\path\to\users\<user-uuid>.db
```

**每次正式發布前**（PRD R9 硬性要求）：對 control DB 與至少一個 user DB 各跑一次上面的隔離
drill，確認能解密、schema 完整、row count 一致，再繼續發布。隔離目錄跑完即可整個刪除，
不影響 active 服務。

### 5.1 拒絕還原已刪帳號

只有明確加 `--promote-to-active` 才會把隔離目錄的還原結果寫回 active 路徑；這一步會先查
`--control-db` 的 `account_tombstones` 表（PRD R7／R9：「已刪帳號不得從一般啟動或自動 restore
流程恢復」）。命中 tombstone 就印 `[REFUSED]`、exit code 2，不寫入任何檔案：

```powershell
uv run python scripts/restore_drill.py --db <user-uuid> `
  --backup-dir E:\lift-log-backups --restore-dir C:\temp\restore-drill `
  --promote-to-active --active-dir <LIFTLOG_USER_DATA_DIR> --control-db <LIFTLOG_CONTROL_DB_PATH>
```

平時的 restore drill（第 5 節開頭那兩個範例）不會觸發這個檢查，因為它們從不寫回 active——
這是刻意的：drill 是「驗證備份可還原」，不是「真的把資料復活」，兩者的風險等級不同。

## 6. Log／檔名不得洩漏的欄位

備份檔名只用 `control` 或既有的 UUID 檔名（`<user_id>.db` 去掉副檔名），不含 email、
Google `sub` 或絕對路徑；所有 `print()` 輸出同樣只印相對路徑或 db 名稱。這對應 PRD R9：
「Log、metrics 與錯誤不得包含 token、Google ID token、email、訓練 payload、體重、MCP 參數或
user DB 絕對路徑」。

## 7. Legacy 資料遷移怎麼跑（F149 ①③④）

`scripts/migrate_legacy.py` 把 cutover 前的單庫 `liftlog.db` 搬進某個 user 的 data DB。
方向永遠是 legacy → target，**target 既有列一律勝出**，所以重跑第二次會全部 skip。

### 識別值只走環境變數或互動輸入

目標 user 的 Google `sub`（或 email）**不接受命令列參數**——參數會留在 shell 歷史
（`ConsoleHost_history.txt`、`.bash_history`）與 process table 裡，那就是 F149 ③ 要防的留痕。
腳本只從兩個地方取：

1. 環境變數 `LIFTLOG_MIGRATE_GOOGLE_SUB`，或 `LIFTLOG_MIGRATE_EMAIL`
2. 兩個都沒設且 stdin 是 TTY 時，用 `getpass` 提示輸入（不回顯、不進歷史）

非互動環境（排程、CI）沒設環境變數就直接中止，不 fallback。用環境變數時記得別讓那行
`$env:...=` 進 shell 歷史——互動輸入是預設也是最安全的做法。查無 user 的錯誤訊息只會說
「依 google_sub 查詢」，不回印識別值本身。

### 順序

```powershell
# 1. 先試算：不備份、不寫入，只印逐表 row counts 與 conflicts
uv run python scripts/migrate_legacy.py --legacy-db ./liftlog.db --dry-run

# 2. 正式跑：開頭會先印出快照路徑，那就是回滾要用的檔案
uv run python scripts/migrate_legacy.py --legacy-db ./liftlog.db

# 3. 要回滾時
uv run python scripts/migrate_legacy.py --rollback <步驟 2 印出的快照路徑>
```

每次輸出的 JSON 摘要含每張表的 `before_target`／`legacy_total`／`migrated`／`conflicts`／
`after_target`——**把它整段留存**，那就是 ① 要求的「逐表 row counts」與 ④ 遷移後一致性的比對基準。
`conflicts` 非 0 代表自然鍵撞到但內容不同，那些列不會寫入，要人工處理後再跑一次。
