# session handoff

最後更新：2026-08-20（第三輪）。**152/161 passing、9 failing**（F89、F95、F104、F124、F128、F149、F153、F159、F160）。
`.harness/current_feature` = F162（已 passing）。

## 接手第一件事

1. **正式站已經搬家了。** 不再是 `lift-log\deploy\current` + 工作樹的 `.venv`，改成
   **`SideProject\lift-log-prod\`**（git 工作樹之外）。任何維運指令要從那裡跑，
   **在 repo 目錄跑 `backup.py` 會被拒絕**（exit 2，這是刻意的）。完整說明見
   `docs/operations.md` 第 1b 節與 `docs/evidence/F161.md`。
2. `git log --oneline -3` 對 origin/main（本輪推到 `47b5d45`），確認沒有第二個 session 在動 repo。
3. **F159 仍只差實機冒煙**（Ryan 本人登入，agent 不得代輸憑證）；**F160 是草案、未簽核**。
   兩者狀態與上一輪相同，細節見上一版 handoff 的 git 歷史。

## 本輪完成（2026-08-20 第三輪）

### F161 — 正式站搬出開發工作樹

承接 mission-control 已關閉的 F44。原本兩個問題：開發期 `uv sync` 會流進正式站、
`git clean -xdf` 一行刪光正式資料（實測會刪 `liftlog.db`／`prod-data/`／`.env`／`release/`／`deploy/`，
git 全程不警告）。根源相同：正式站住在工作樹裡。

- 搬到 `lift-log-prod\`：`current/ previous/ .venv/ .venv-previous/ .env data/ release/`
- `deploy.ps1` 依快照的 `uv.lock` 建 `.venv-staging` 再換名，環境與程式碼同進同退
- mission-control `services.toml` 三行改指新位置（**該檔未 commit，是 Ryan 自己的部署設定**）
- 逐表 row count 搬遷前後一致，加密備份在 `D:\lift-log-backups`，金鑰 `C:\Users\user\.liftlog\backup.key`

**兩個踩過的坑（下一個人請不要重踩）**：

1. **uv 的 `.exe` shim 不能改名**——絕對路徑寫死在 trampoline 裡，`.venv-staging` → `.venv`
   一改名就壞，log 只有一行 `Failed to canonicalize script path`。所以 `services.toml` 用的是
   `python.exe -m uvicorn`，**不是 `uvicorn.exe`**。不要「順手改回來」。
2. **`.env` 搬走後 `backup.py` 會靜默備錯**——落回 `./control.db`／`./users`，那在工作樹底下
   剛好是測試站的檔案，exit 0 印 `[OK]`。已改成拒絕執行，回歸測試在 `tests/test_backup.py`。

### F162 — 體重圖改折線圖，折線圖抽共用模組並支援聚合

- 新增 `app/static/js/line-chart.js`：幾何、點渲染、浮動框、鍵盤互動。`exercise-detail.js`
  與 `body.js` 共用
- `body.js` 移除 `barChart()` 與 `BAR_COUNT`（24 筆靜默上限）
- **N > 50 時聚合**成區間平均（日→週→月），標題顯示單位，浮動框帶 min/max
- **正式 supersede 六條既有條文**，清單在 `feature_list.json` 的 `F162.supersedes`，
  理由與對照表在 `docs/evidence/F162.md`。改那張圖之前先讀那份檔案

**三件容易踩的事**：

1. **`.line-tip` 的三個行內 class 必須各自唯一**（`line-tip-date`／`line-tip-sets`／`line-tip-best`）
   ——`verify_f134.py` 用單一選擇器取值，重複就撞 Playwright strict mode
2. **圖表底部的 `.bars-foot` 不是裝飾**——x 軸是序位等距，沒有那兩個日期就看不出區間長度，
   而且它是 F57 ⑤ 明文要求
3. **新增前端模組要同步加進 `app/static/sw.js` 的 shell 清單**——有測試守著
   （`test_sw_shell_list_matches_static_files`），漏了會離線少檔

**聚合門檻已與 E2E 耦合**：`verify_f134.py` 從 `line-chart.js` 讀出 `AGG_MAX_POINTS` 並斷言
壓力情境筆數沒超過它。改任一邊的數字，腳本會直接中止並說明原因，不會讓斷言莫名翻紅。

## APK v157 — 已建好，**還沒進 Google Drive**

`G:` 當時沒掛載（Google Drive 桌面版沒跑），所以只做到建置與驗證：

- 暫存在 **`C:\Users\user\Downloads\lift-log-v157-F162.apk`**（10.7 MB）
- 已用 `unzip -p ... state.js | grep APP_VERSION` 驗過是 `v157`，且內含 `line-chart.js`
- **Google Drive 開起來之後**：`Copy-Item C:\Users\user\Downloads\lift-log-v157-F162.apk "G:\我的雲端硬碟\lift-log-apk\"`
- ⚠ `android\app\build\outputs\apk\release\app-release.apk`（無 `prod`）那顆 **7/30 的殭屍檔還在**，
  CLAUDE.md 警告的坑是真的，複製一律走 `apk\prod\release\`

## 下一場

剩 9 條 failing，幾乎都卡在 agent 做不到的事：

- **要 Android 實機**：F89、F95、F104、F124、F128、F159
- **要 Ryan 本人**：F149（APK 冒煙、Google 登入）
- **要先重審規格**：F153 的 `touches` 只寫 `mcp.py` 不可信（這條連續兩輪 handoff 都寫了，還沒動）
- **未簽核**：F160
