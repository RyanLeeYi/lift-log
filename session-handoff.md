# session handoff

最後更新：2026-08-16。**143/155 passing、12 failing**。`.harness/current_feature` = F149。

## 接手第一件事

**F149 卡在一件只有 Ryan 能做的事：正式站沒有設定 Google OAuth client ID。**

`.env` 沒有 `LIFTLOG_GOOGLE_CLIENT_ID`（`.env.example` 有欄位但空白），Android 端也沒有任何
client id 資源。v154 APK 的登入畫面按下去毫無反應——server 沒有 audience 可驗 id_token、
app 沒有 client id 可要 id_token。F149 剩下的鏈（登入 → 綁 Google sub → 跑遷移 → 撤 legacy token）
全部堵在這裡。**不要嘗試繞過它自己造假登入**，那會讓後續驗收失去意義。

連帶狀態：**Ryan 手機上的 APK 已被換成 v154**，而 v154 強制 Google 登入，所以他目前
用不了手機 app（網頁版仍可用，legacy token 還沒撤）。Ryan 尚未回覆要「補 OAuth 設定」
還是「先退回舊 APK」。

## 本輪完成

### 正式站部署到 v154（commit `615b343`）

線上站原本停在 **v124**（落後 30 版，F149 的後端改動根本不在線上）。已部署並驗證：
`/health` 200、`/js/state.js` 回 v154（第一次查到 v124 是 Cloudflare edge 快取，加 query 參數即破）。

### 修 `scripts/deploy.ps1` 的假失敗（未 commit）

原本「停舊 process → 睡 4 秒 → 打一次 health」。F147 之後開機多了 control DB 與各 user
data DB 初始化，要 5~6 秒才聽得到 port，於是**連兩次把好好的版本判定成起不來並自動回退**。
已改成 30 秒輪詢。這是單次檢查的通病：把「還沒起來」當「起不來」。

### 修掉會讓帳號資料變孤兒的路徑問題（commit `935a1d9` + `.env`）

`control_db_path` 與 `user_data_dir` 的預設值是**相對 cwd**，而正式站 cwd 是 `deploy/current`。
不釘絕對路徑的話，登入建立的帳號與所有 user data DB 會寫進快照目錄，
**下一次部署 `current→previous` 就整批變孤兒**。已在 `.env` 釘到 repo 根的 `prod-data/`
（`.gitignore` 已加）。部署後確認 `prod-data/control.db` 正常生成。

### F149 遷移命令 — `scripts/migrate_legacy.py`（commit `615b343` + 未 commit 的 app_settings）

```
uv run python scripts/migrate_legacy.py --legacy-db ./liftlog.db --google-sub <sub> [--dry-run]
uv run python scripts/migrate_legacy.py --rollback <snapshot> --google-sub <sub>
```

合併策略（Ryan 尚未否決）：**target 既有列一律勝出**，legacy 只補 target 沒有的列
（順帶讓重跑天然冪等）；自然鍵撞但內容不同 → 不寫，列進 `conflicts` 明細。
domain 寫完走 `run_backfill()` 補同步層（D17：domain 是唯一事實來源）。
非 dry-run 先對 target 做 VACUUM 快照，路徑印在輸出最前面即回滾用。

七張表：exercises／templates／workouts／sets／body_metrics／daily_status／**app_settings**。
`push_subscriptions` 刻意不搬（裝置專屬，跨帳號搬移沒有意義）。

遷移前彩排（Ryan 真資料複本跑 v154 migrations）：14 workouts／179 sets／8 body_metrics／
40 exercises／3 templates，row count 一筆不差。備份在 `liftlog.db.bak-predeploy-20260816-2040`。

## 尚未完成（F149 剩餘）

1. **Google OAuth client ID**（阻塞中，見上）
2. 實際跑 `migrate_legacy.py` 綁 Ryan 的 sub，並撤銷 `LIFTLOG_TOKEN`
3. release-signed APK 全流程冒煙（真登入、離線訓練、衝突、匯出、刪帳）——現在只驗到
   「v154 裝得起來、顯示正式環境、擋在登入」
4. Web/APK/MCP/schema 版本一致（APP_VERSION 是唯一來源，gradle 自動導 versionCode，這塊 OK）
5. 全部完成後派獨立 review 與 `acceptance-verifier` 逐條驗收，才可改 passing

## 記帳（不阻塞，但別忘）

- app 內建自我更新（F67）按「立即更新」後沒有動作，server log 也沒有下載請求；
  當時改用 adb 直接裝 v154 繞過。**這是一條沒查完的線索**，可能只是「安裝未知應用」權限沒開
- `scripts/backfill_sync.py` 的快照目錄用秒級時間戳，同一秒重跑會撞 VACUUM INTO 目的檔已存在
- `docs/evidence/F146.md` 末段第 2 項（Web IndexedDB 離線佇列與 envelope 非目標的字面差異）仍未處理
- `G:\我的雲端硬碟\lift-log-apk` 未掛載，v154 尚未複製到 Google Drive
- **不要整份 `Read` `feature_list.json`**（334KB）。理由與挑欄位指令見 `CLAUDE.md` 工作規則 #1
