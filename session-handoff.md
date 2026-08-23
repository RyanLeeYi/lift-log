# session handoff

最後更新：2026-08-23（無人看管 dispatch 場，第十一場）。**160/166 passing、6 failing**
（F89、F104、F128、F149、F153、F166）。本場**沒有 feature 轉 passing**——F89 卡在真機。

## 接手第一件事

1. **先看收件匣**：本場投了一則 high question
   `[blocked] F89 ⑩ 真機驗收：dev app 要你登入、prod 會寫真資料、通知仍被系統關著`。
   在 Ryan 答之前，F89／F104／F128／F166 的真機部分**全部動不了**，不要再重試一次同樣的路。
2. 08/22 那則 `allowNoti=false` 的 high question **仍未回答**，本場重新確認症狀還在。
3. 本場改動：`RestOverlay.java`（兩個 private → package-private）＋
   新檔 `android/app/src/test/java/com/ryanleeyi/liftlog/RestOverlayMotionTest.java`。
   feature 狀態未動，只補 F89 的 evidence。

## 本場做的事（2026-08-23 第十一場 dispatch）

收件匣答案是 `Run, start with F89`（兩則同內容）。

`baton-dispatch` 五問：Outcome 清楚、Ownership 可切，但 **Independence 直接否決**——
F89／F104／F128 共用同三支 Java 檔，F166 雖然檔案不重疊，剩下的工作卻同樣需要**那一支實體手機**。
adb 是獨佔資源，worktree 隔離不了它，兩個 worker 同時操作同一台手機只會互相踩。
→ **全部 direct，零派工**（連唯讀 agent 都沒派：沒有需要 fresh context 判定的成品）。

### F89 ⑧：code audit 通過

`RestOverlay` 的 13 個非 private 進入點逐一比對：11 個第一行就 `onMain(() -> ...)`；
`permitted`／`headsUpWanted`／`advanceDraftSetNumber` 不碰 view（後者只把 int 加一，
唯一呼叫端 `requestLog` 本身已在 onMain 區塊內）。
→ ⑧ 的「所有碰 view 的進入點經 onMain()」**目前成立**。⑧ 剩下的 F63／F64／F69–F71 回歸仍未做。

### F89 ⑨：補上回歸檢查（本場唯一的程式碼產出）

原缺口是「reduced-motion 只驗到不崩」——而「動效整條被拿掉」的實作也不會崩。
`RestOverlayMotionTest`（Robolectric）兩個方向各驗：
`ANIMATOR_DURATION_SCALE=0` → `animateIn` 直接就位；`=1` → 確實從 alpha 0 / scale .92 起跑。
另加「查不到＝預設要動效」與 null target 不炸。

- Android 單元測試 **46 tests / 0 failures**（原 41 ＋ 新 5）
- 突變測試：`reduceMotion` 改成恆 `false` → 2 條紅；還原後全綠
- `uv run pytest` **487 passed**、`uv run ruff check .` 全過

⚠ 這**不等於** ⑨ 通過：160ms 過場的實際觀感仍需真機或高幀率錄影，
自動化只證明了分支邏輯與起始狀態。

## 卡住的事

### F89 ⑩ 真機：三個獨立擋路點（本場的主要發現）

1. **dev app 要 Google 登入**。已把既有 `app-dev-release.apk`（v161）裝上 RF8NB0BSEFE，
   停在登入畫面。**這是新變化**：07/08 那幾場用 dev app 驗 F89／F104 時 legacy 單一 token
   路徑還在，F149 關掉之後 dev app 就從「裝了就能用」變成「要 Ryan 本人登入」。
   → 下一個接手的人：**不要再花時間找繞過登入的路**，沒有。
2. **走 prod app 會寫進真實訓練資料**。休息倒數只由 `app.js:2574`（記完一組）啟動；
   `RestTimerService` 是 `exported="false"`，`adb am` 叫不動，沒有純原生的拉起入口。
3. **`allowNoti=false`**（延續 08/21、08/22）。F63／F72／F73 的通知回歸在這台手機上產不出證據。

### 其餘（延續前場，未變）

- F166：③④ 的程式碼早在 `09afde9` 就落地、E2E 也補了，只剩 ⑥ 真機——與上面第 3 點同一個擋路點。
- F149 要 Ryan 的 Google 身分、F153 要真 LLM key ＋ 人工對照，headless 一律做不了。
- **e2e 腐爛**：18 支舊腳本多半卡在登入畫面。同一段假 plugin 已經抄第三次，抽成共用 helper
  值得獨立開一條 feature（尚未開，因為需要簽核）。
- 本場沒排保溫鬧鐘：`ScheduleWakeup` 只在 `/loop` dynamic mode 可用，headless dispatch 進不去。

## 順帶觀察（未追）

prod app v160 首頁今晚顯示「同步錯誤 · 待同步 1 筆」。可能是 08/21 實機冒煙後
以 delete mutation 清資料留下的殘骸，也可能是真的同步失敗。已寫進 question 與 F89 evidence。
