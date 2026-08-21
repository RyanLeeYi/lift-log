# session handoff

最後更新：2026-08-21（無人看管 dispatch 場，第三場）。**153/161 passing、8 failing**（F89、F95、F104、F124、F128、F149、F153、F160）。

## 接手第一件事

1. **正式站在 `SideProject\lift-log-prod\`**（git 工作樹之外），不是 `deploy/current`。
   維運指令從那裡跑，在 repo 目錄跑 `backup.py` 會被拒絕（exit 2，刻意的）。
   見 `docs/operations.md` 第 1b 節與 `docs/evidence/F161.md`。
2. **F159 已 `passing` 並歸檔**（2026-08-21）。⑦ 實機冒煙由 agent 在 Ryan 指示下做完，
   留在正式站的三筆冒煙資料也已依 Ryan 回覆刪除（見下）。**F105 的部署／出 APK 封鎖解除。**
3. **F160 草案已重寫，等 Ryan 簽核**（見下）。簽核前 `executor` 派工會被 hook 擋。

## 本場做的事（2026-08-21 第三場 dispatch，收件匣回覆「改 passing，順手刪掉那三筆冒煙資料」）

1. **F159 → `passing`**，整條原文搬進 `docs/archive/features.jsonl`，主檔只留 failing。
   `evidence` 指向 `docs/evidence/F159.md`。
2. **刪掉正式站的三筆冒煙資料**（user DB `68ea7b49-...`）：exercise 41 `F159-smoke-plank`、
   set 152（20kg×60 秒）、set 153（臥推 50kg×11）。
   **走 `sync.push()` 的正規 delete mutation，不是直接改表**——三筆都是 tombstone、各記一筆
   `sync_changes`（server_seq 220/221/222），control DB 的 `users.sync_server_seq` 也推到 222。
   手機下次 pull 會自己刪掉本地那三筆。刪前的 user DB 與 control DB 副本在本場 scratchpad。
3. 那次冒煙一併建的 workout id 11（8/21「全身」）**沒刪**——Ryan 指名三筆，且它零筆存活的組，
   history／heatmap 都是從 `sets` join 上來的，查詢層看不到它。要清的話多發一筆 delete 即可。
4. `uv run pytest` 全綠（463）、`uv run ruff check .` 全過、正式站 `/health` 回 `prod ok`。

**下一步**：F160 等 Ryan 簽核；其餘 failing 全部卡實機或 Ryan 本人。

## 本場做的事（2026-08-21 第二場 dispatch，收件匣回覆後）

Ryan 的回覆是「先做 F159 冒煙，F160 之後再談」。F159 的可委派部分上一場已完成，
剩下的 ⑦ 實機冒煙 acceptance 明文排除委派；F160 未簽核（hook 也會擋）。
所以本場只做狀態確認，**沒有動任何程式碼**：

| 檢查 | 結果 |
|---|---|
| `uv run pytest` | 全綠（463） |
| `uv run ruff check .` | All checks passed |
| android/ 自 F159 evidence 後有無改動 | 無（最後一筆是 `fc9e00c`），故未重跑 gradle |
| 正式站 `lift-log` 服務 | running / healthy |
| `G:` 磁碟 | 仍未掛載，v157 APK 還卡在 Downloads |

**下一步只有 Ryan 能做**：`docs/evidence/F159.md` 最後一節那三步冒煙（約 3 分鐘），
過了就把 F159 改 `passing`。

## 上一場做的事（2026-08-21 dispatch）

只有唯讀調查與一份規格改寫，沒有動任何實作程式碼。

### F160 ② 的前置問題有答案了，原草案起因是誤判

草案 ② 要求動工前確認「server 的 422 回應帶不帶得出 mutation_id」。查證結果：
**server 對單筆驗證失敗根本不回 422。**`app/services/sync.py::_process` 逐筆退成
`_conflict(mutation_id, "validation_failed")`，整個 request 仍是 200，同批其他 mutation 照常 accepted。
那道守衛是 F105 就寫下的，註解描述的正是本條要防的災難。

所以 F159 review 當初說的「時間型組被回 422 → 整批連坐」在現行程式碼**不可達**。
但連坐機制本身還在，觸發條件是**整包層級的 HTTP 錯誤**，最危險的是
**409 `unsupported_schema`**——server bump schema 後，還沒更新的 APK 第一次同步就把手上
最多 500 筆全部合法的 mutation 永久報廢。這是版本落差，不是壞資料。

順手查到的覆蓋缺口（已寫進 F160 ④）：`sync.py` 那道守衛**拿掉不會有任何測試變紅**
（`tests/` 內找不到 `validation_failed` 的斷言）；Android 端也沒有涵蓋非 retryable HTTP 的連坐分支。

F160 的 acceptance 與 `touches` 已依此重寫（多了 `app/services/sync.py`、`tests/test_sync.py`），
末尾留兩個待 Ryan 拍板的問題。**未簽核，未動工。**

## 卡住的事

- ~~APK v157 卡在 Downloads~~ **已解決（2026-08-21）**：`lift-log-v157-F162.apk` 已在
  `G:\我的雲端硬碟\lift-log-apk\`，解壓確認 `APP_VERSION = "v157"`。
  **`G:` 掛不起來的真正原因**：舊的 `GoogleDriveFS.exe`（8/9 起的 PID 1356）霸佔
  `\\.\Pipe\GoogleDriveFSPipe_user`，新開的每次 `CANNOT_START_IPC` 秒退，
  桌面版看起來「開著」但其實沒掛載。下次同樣症狀：砍掉舊的那串 process 再重開即可
- 剩下的 failing 幾乎都要 Ryan 或實機互動：F89／F95／F104／F124／F128 真機驗收、
  F149 要 Ryan 本人登入、F153 的 `touches` 只寫 `app/mcp.py` 仍不可信（第四場沒動）
