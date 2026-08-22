# session handoff

最後更新：2026-08-22（無人看管 dispatch 場，第九場）。**158/166 passing、8 failing**
（F89、F104、F124、F128、F149、F153、**F160**、**F166**）。
F160 實作完成、待驗收結果；F166 實作完成、卡在真機那條。

## 接手第一件事

1. **8 條全部簽核了**（收件匣 8 筆 `[sign-off]` 都回 "Sign off as-is"，commit `a20771a` 已 push）。
   `delegation-warmup` 的 ②③ 兩道閘門不再擋任何一條。
2. **F160 已實作並 commit（`241a3b3`）**，`acceptance-verifier` 的判定結果見下方；
   verifier 判 pass 就改 `passing` ＋ 整條原文搬 `docs/archive/features.jsonl`。
3. **F166 卡在 ⑥ 真機**——不是 F166 的問題，是那支手機上 lift-log 的通知在系統層是關的。
   已投 question（high）。細節見下。
4. **F124 簽核了但沒答案**——條文本身是「待決」清單。已投 question 建議不做。
5. 正式站在 `SideProject\lift-log-prod\`（見 `docs/operations.md` 第 1b 節）。

## 本場做的事（2026-08-22 第九場 dispatch）

收件匣解鎖的是 8 條 feature 的簽核。照 `baton-dispatch` 五問把它們按**共用檔案**分四組，
不是一條一個 worker：

| 組 | feature | 判定 | 理由 |
|---|---|---|---|
| rest-overlay | F89 F104 F124 F128 | **direct**（本場未動工） | 四條全撞 `RestTimerPlugin.java`，永遠不能平行；且要真機互動迴圈 |
| sync | **F160** | **dispatched**（executor / worktree） | 檔案自足、done criteria 可斷言、與其他組零交集 |
| notify-gate | **F166** | **direct** | 一行常數 ＋ 兩條 E2E，派工成本大於工作本身 |
| blocked | F149 F153 | 不動工 | 要 Ryan 的 Google `sub`／真 LLM key ＋ 人工對照 |

### F160（dispatched，`241a3b3`）

整包層級的 HTTP 錯誤（409 `unsupported_schema`／403 `device_mismatch`）不再連坐整批 outbox：
`SyncClient.syncOnce()` 那個 `else` 分支從 `markPushPermanentFailure` 改走 `scheduleRetry`。
`markPushPermanentFailure` 保留但已無 HTTP 呼叫點（主 session 的裁決，不是刪掉）。
`syncStatus()` 新增 `failed_items`（`mutationId`/`entityType`/`entityId`/`errorCode`/`createdAt`），
predicate 與既有 `failed` 計數完全相同。

主 session 集中驗證（不是只看 worker 回報）：
- `uv run pytest` **487 passed**（基準 486 ＋ 新增 1）
- `uv run ruff check .` 全過
- `gradlew testProdDebugUnitTest --tests '*SyncClientTest*'` **tests=8 failures=0**，
  含新增的 `unsupportedSchemaFailureStaysRetryableAndDoesNotPoisonPending`，
  且 `oversizedMutationBecomesPermanentErrorWithoutCrashing`（⑤ 的 BatchTooLarge）仍綠

⚠ **worker 回報裡有一個值得記的查證**：規格背景寫「422 來自 FastAPI 對 `SyncPushIn` 的外層驗證」，
但 `app/errors.py::on_validation_error` 實際把 `RequestValidationError` 轉成 **400**。
修法在 code-path 層級生效（任何非 retryable、非 session 的 `TransportFailure` 都涵蓋），
所以數字對不上不影響結果，但條文那句話是錯的。

⚠ **F160 動到 Android Java，要出 APK 才會到手機上**（CLAUDE.md 那條規則的字面是
「動到 `app/static/` 才要出」，但 Java 改動同樣只能靠 APK 送達）。**本場還沒出。**

### F166（direct，`09afde9`）

`REST_CHANNEL_IDS` 補上第三個 channel `rest-alarm`（歸零那則「休息時間到」，importance 4）。
判定規則一字沒動（查不到不算被關、拋錯退回 `areEnabled`），只是清單多一個 id。
`verify_f95.py` 補 ④ 的正反兩條，**11/11 passed**（原 9/9）。`ruff` 全過。
`APP_VERSION` 升到 **v159**，APK 已 build 並裝上 SM-N9750（路徑確認是
`apk/prod/release/app-prod-release.apk`，`unzip` 驗過版號與那行常數）。

## 卡住的事

### F166 ⑥ 真機：手機上 lift-log 的通知在系統層是關的

三個 channel 全部正常（default=3、rest-timer=2、rest-alarm=4），系統「應用程式通知 →
顯示通知」畫面上讀到「開」，**但** `dumpsys notification` 說
`AppSettings: com.ryanleeyi.liftlog (10917) allowNoti=false`。

`areEnabled()` 是 `native-notify.js` 的唯一事實來源，它一 false，app 內「休息提醒」開關
就一定顯示「關」，**跟 channel 狀態無關**。所以「關掉 rest-alarm → 開關顯示關」這個觀察
在目前狀態下**無法區分是不是 F166 造成的**——我把 rest-alarm 關掉再開回，兩邊都是「關」。
證據無效，沒有拿它充數。

同一份 dumpsys 裡 `com.ipass.ipassmoney` 也是 `allowNoti=false`，所以懷疑是 Samsung 那層的
批次設定，不是這個 app 的問題。**這條也會讓 F89／F104／F128 的真機驗收不可靠**
（F89 ⑥ 的浮動計時開關要先開休息提醒）。

**裝置狀態已還原**：rest-alarm importance 回到 4；app 內「休息提醒」開關點過兩次（一開一關，
淨值為零）；沒動 app 層通知設定；沒碰那筆 pre-existing 的「待處理衝突 1 筆」。

### F124 簽核了，但條文是「待決」清單不是規格

三個問號（要不要做延後派送／就緒訊號從哪來／範圍是否擴及六個事件）都沒答案。
已投 question 並建議**不做**：F123 之後殘留風險只剩「銷毀與收掉之間那一瞬按下去」，
後果是那一按沒反應、鈴照響、再按一次即可；為它加一套事件暫存 ＋ 就緒握手，
等於在幾乎走不到的路徑上新增一條狀態機（重播順序、過期命令、重複派送都是新的錯誤面）。

### 其餘

- F149 要 Ryan 的 Google 身分、F153 要真 LLM key ＋ 人工對照，headless 一律做不了。
- **e2e 腐爛確認擴大**：`verify_f65.py` 本場實跑，卡在 `wait_for_selector("input")`，
  與上一場對 `verify_f95.py` 的診斷完全同型。上一場說的「18 支可能全部腐爛」不是猜測。
  修法（假 plugin 補 `AuthSession`/`LocalStore`/`Sync`、假 token 用 `LIFTLOG_TOKEN`、
  `**/api/mcp-tokens/**` stub 成 `[]` 且註冊在 `reroute_public_host()` 之後）已在
  `verify_f95.py` 驗證可行，抽成共用 helper 值得獨立開一條 feature。
- 本場沒排保溫鬧鐘：`ScheduleWakeup` 只在 `/loop` dynamic mode 可用，headless dispatch 進不去。
