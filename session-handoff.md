# session handoff

最後更新：2026-08-22（無人看管 dispatch 場，第十場）。**160/166 passing、6 failing**
（F89、F104、F128、F149、F153、F166）。
**F124 已 passing 並歸檔**；APK `lift-log-v161-F124.apk` 已上 Google Drive（**尚未裝機**）。

## 接手第一件事

1. **F124 做完了**：原生→前端控制事件不再被丟掉。整條原文在 `docs/archive/features.jsonl`，
   證據在 `docs/evidence/F124.md`。驗收（`acceptance-verifier`）①–⑥ 全 pass、無 severity。
2. **APK v161 已出但沒裝機**（headless 沒接手機）。Ryan 要驗 ⑤ 的真機流程就裝這顆。
3. **收件匣答案有一則過期**：`Run, start with F160` ——F160 在**同一天更早的第九場**就
   已 passing 並歸檔。這是 2026-08-21 記過一次的同型故障（DEVLOG 第四場）。
   另一則 `全做：六個原生→前端事件都暫存重播` 就是本場做的 F124。
4. 正式站在 `SideProject\lift-log-prod\`（見 `docs/operations.md` 第 1b 節）。

## 本場做的事（2026-08-22 第十場 dispatch）

收件匣解鎖的是 **F124 的三個待決問題**（① 要不要做延後派送、② 就緒訊號從哪來、
③ 範圍是否擴及六個事件）。Ryan 答「全做」，所以先把原本的「待決清單」改寫成
可逐條判定的 ①–⑥ acceptance 才動工（Plan → 條文凍結 → 實作）。

`baton-dispatch` 五問：只有一組工作、三個檔案互相咬合（Java retain ↔ static queue ↔
JS 訂閱時機）、核心是「事件順序 vs 還原順序」的未知行為判斷 → **direct**，
唯一派出去的是唯讀的 `acceptance-verifier`。

### 做法：三層，缺一層就還是會掉事件

| 情況 | 處置 |
|---|---|
| plugin 在、JS 也訂閱了 | 直接送 |
| plugin 在、JS 還沒訂閱（Activity 重建，onCreate 早於 WebView） | Capacitor 內建 `notifyListeners(..., retainUntilConsumed=true)` |
| plugin 不在（Activity 被回收，`instance == null`） | `PendingRestControl` static FIFO（上限 32、TTL 5 分鐘），`load()` 重放 |

**第二層是平台既有能力，不是自寫的**——`Plugin.java` 在沒有 listener 時把 payload 存進
`retainedEventArguments`，第一個 listener 掛上時 `sendRetainedArgumentsForEvent()` 依序送出。
只有第三層它救不了。原本以為要自建「前端取件」握手（F125 ③ 那種），實際上只要換一個
既有 API 的參數。

判定放在 `RestTimerPlugin.dispatch()` 這個唯一出口，所以九種動作全涵蓋，不逐動作列舉。

### 順序才是真正的坑（④）

前端訂閱從 module eval 當下改成 `startupRestore.then(...)`。**事件不掉了以後，
「什麼時候訂閱」就直接決定它們落在 F66 快照還原之前還是之後**：還原之前收到 `stop`
會撞上 `restStartedAt === null` 直接 return、隨後還原又生出一輪殭屍倒數；
`focus` 讀不到 `restExerciseId` 而 early-return（＝「停了但沒跳頁」）。
修好丟失卻沒修順序，等於把靜默丟棄換成靜默錯序。

`MainActivity.onCreate` 因此才敢恢復處理 `EXTRA_BACK_TO_APP`／`EXTRA_FOCUS_REST`
（⑤；原本刻意不掛，理由就是 F124 本身）。

### 驗證

- Android 單元測試 **41 tests / 0 failures**（新增 `PendingRestControlTest` 4 條）
- `tests/e2e/verify_f124.py` **3/3**——量的是 `addListener` 與開機還原的先後
- `uv run pytest` **487 passed**（與 F160 收官基準相同）、`ruff` 全過
- 兩處都做了突變測試：Java 側改 `removeFirst`→`removeLast`／拿掉 TTL 過濾 → 2 條紅；
  JS 側把訂閱改回 module eval → E2E 第三條紅（2/3、exit 1）。還原後皆綠

## 卡住的事

### F166 ⑥ 真機：手機上 lift-log 的通知在系統層是關的（延續上一場）

`dumpsys notification` 說 `AppSettings: com.ryanleeyi.liftlog allowNoti=false`，
但系統設定畫面顯示「開」。`areEnabled()` 是 `native-notify.js` 的唯一事實來源，
它一 false，app 內「休息提醒」開關就一定顯示「關」，跟 channel 狀態無關 →
**F166 ⑥ 在這台手機上無法產生有效證據**。同一份 dumpsys 裡 `com.ipass.ipassmoney`
也是 `allowNoti=false`，懷疑是 Samsung 那層的批次設定。已投 question（high）。
這條也讓 F89／F104／F128 的真機驗收不可靠。

### 其餘

- F149 要 Ryan 的 Google 身分、F153 要真 LLM key ＋ 人工對照，headless 一律做不了。
- **e2e 腐爛**：18 支舊腳本多半卡在登入畫面（`verify_f65.py`／`verify_f95.py` 實測同型）。
  修法（假 plugin 補 `AuthSession`/`LocalStore`/`Sync`、`**/api/mcp-tokens/**` stub 成 `[]`
  且註冊在 `reroute_public_host()` 之後）在 `verify_f95.py` 與本場的 `verify_f124.py`
  都驗證可行，**同一段假 plugin 已經抄第三次了**——抽成共用 helper 值得獨立開一條 feature。
- 本場沒排保溫鬧鐘：`ScheduleWakeup` 只在 `/loop` dynamic mode 可用，headless dispatch 進不去。
