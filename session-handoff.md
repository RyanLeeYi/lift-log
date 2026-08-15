# session handoff

最後更新：2026-08-15。**143/155 passing、12 failing**——F155 已 passing，F149 仍進行中。
`.harness/current_feature` = F149。

## 接手第一件事

上一輪的「等待裁決」已全部解掉，**不要再照舊 handoff 停下來等**。兩個裁決結果：

1. **F149 vs F155 順序**：Ryan 選「先簽 F155 再做 F149」。F155 已 passing，
   F149 的 R8 回填直接站在 `scripts/backfill_sync.py` 上面，不必再自己定回填規則。
2. **legacy 單一 Bearer token**：Ryan 選「拆出獨立 `LIFTLOG_SECRET_KEY`」。已落地（見下）。

## 本輪完成

### F155 既有資料回填進同步層 — **passing**

`scripts/backfill_sync.py` ＋ `tests/test_backfill_sync.py`（7 條）。證據見 `docs/evidence/F155.md`。

- 三個方向全走 `app/services/projection.py` 這座唯一橋樑（`record_write` / `apply_payload`）
- ④ 取捨規則照 **D17**：domain 版本勝出，被覆蓋的舊 payload 進 `overridden` 明細
- ② 經 Ryan 重簽補了例外：自然鍵已被另一個 sync_id 佔用的孤兒不投影（UNIQUE 約束讓兩筆
  並存在結構上不可能），但必須列進 `unresolved` 明細附兩邊 payload
- 獨立驗收兩輪：第一輪 ①③④ ACCEPT／② REJECT，修完針對性重驗 ②③ 皆 ACCEPT

### F149 的一塊：token 選填 ＋ CSRF 金鑰拆分（commit `4d8fb42`）

- `LIFTLOG_TOKEN` 不再必填。留空＝legacy 路徑整條關閉，只能 Google 登入（PRD 非目標要的）
- **它原本兼任 web CSRF 的 HMAC 金鑰**，所以不能單純改選填——留空會讓 CSRF token
  變成由 session id 推導的可預測值，且連 Google 登入那條路一起受害。已拆給 `LIFTLOG_SECRET_KEY`，
  未設時由 `control_db.ensure_web_csrf_secret()` 產一顆存進 control DB 的 `schema_metadata` 並沿用
- 補了兩道守衛：token 未設時 `expected` 會是 `"Bearer "`，**送空 token 就拿到 legacy 全庫存取**
  （繞過 CSRF、rate limit、每日配額、user 隔離）。`app/api/deps.py::_is_legacy_request`、
  `app/mcp.py::DomainTokenVerifier.verify_token` 各一處
- 文件同步：`.env.example`、`docker-compose.yml`、`README.md`、`README.zh-TW.md`、`CLAUDE.md`

Gates：`uv run pytest` 413 綠、`uv run ruff check .` 綠、`docker compose config --quiet` 通過。
純後端改動未動 `app/static/`，**不需出 APK**。

## 尚未完成（F149 剩餘）

1. **既有資料遷移命令**（dry-run／備份／回滾／row count 比對）——現在沒有阻塞了，
   回填規則就用 `scripts/backfill_sync.py`
2. release-signed APK 全流程冒煙（真登入、離線訓練、衝突、匯出、刪帳）
3. Web/APK/MCP/schema 版本一致
4. 全部完成後派獨立 review 與 `acceptance-verifier` 逐條驗收，才可改 passing

`20 帳號×2 裝置隔離／quota` 與每日備份已由 D15 降到 `docs/operations.md`，不是 release blocker。

## 記帳（不阻塞，但別忘）

- `scripts/backfill_sync.py` 的遷移前備份是**明文** VACUUM 快照，放在
  `<user data dir>/backfill_backups/` 且不自動清理。曝險沒增加（user data DB 本來就是明文
  SQLite、同機同碟），`data_db_size()` 只算 db＋wal 不掃目錄所以不會誤爆 quota——
  但與 `backup.py` 的 Fernet 加密池不同調。F149 遷移收尾時一併決定保留期限
- `docs/evidence/F146.md` 末段第 2 項（Web IndexedDB 離線佇列與 envelope 非目標的字面差異）
  仍未處理；第 1 項 legacy token 已由本輪解決
- `G:\我的雲端硬碟\lift-log-apk` 未掛載，v154 尚未複製到 Google Drive
- **不要整份 `Read` `feature_list.json`**（334KB）。理由與挑欄位指令見 `CLAUDE.md` 工作規則 #1
