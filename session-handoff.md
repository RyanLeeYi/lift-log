# session handoff

最後更新：2026-08-21（無人看管 dispatch 場）。**152/161 passing、9 failing**（F89、F95、F104、F124、F128、F149、F153、F159、F160）。

## 接手第一件事

1. **正式站在 `SideProject\lift-log-prod\`**（git 工作樹之外），不是 `deploy/current`。
   維運指令從那裡跑，在 repo 目錄跑 `backup.py` 會被拒絕（exit 2，刻意的）。
   見 `docs/operations.md` 第 1b 節與 `docs/evidence/F161.md`。
2. **F159 只差 ⑦ 實機冒煙，清單已備妥在 `docs/evidence/F159.md` 最後一節**——
   手機已是 v156、正式站也是 v156、服務 running，Ryan 三步做完就能改 `passing`。
   acceptance 明文寫這步由 Ryan 本人執行，agent 不要代做（會寫進正式站真實訓練資料）。
3. **F160 草案已重寫，等 Ryan 簽核**（見下）。簽核前 `executor` 派工會被 hook 擋。

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

- **APK v157 仍在 `C:\Users\user\Downloads\lift-log-v157-F162.apk`**——`G:` 這場也沒掛載。
  Google Drive 桌面版開起來後：`Copy-Item ... "G:\我的雲端硬碟\lift-log-apk\"`
- 剩下的 failing 幾乎都要 Ryan 或實機互動：F89／F95／F104／F124／F128 真機驗收、
  F149 要 Ryan 本人登入、F153 的 `touches` 只寫 `app/mcp.py` 仍不可信（第四場沒動）
