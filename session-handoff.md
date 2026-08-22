# session handoff

最後更新：2026-08-22（無人看管 dispatch 場，第八場）。**158/166 passing、8 failing**
（F89、F104、F124、F128、F149、F153、F160、**F166**）。

## 接手第一件事

1. **F95 已 passing 並歸檔**（真機驗完）。長證據 `docs/evidence/F95.md`，截圖 `docs/evidence/F95_0*.png`。
2. **新開一條 F166（草案、未簽核）**：休息**歸零**那則提醒掛在第三個 channel `rest-alarm`
   （「休息時間到」，importance 4），不在 `REST_CHANNEL_IDS` 裡——只關掉它，開關仍顯示「開」
   而提醒不會出現，與 F65／F95 同型的靜默失敗。條文末尾有一個要 Ryan 拍板的選項（(a)/(b)）。
3. **18 支宣告 native 的 e2e 腳本可能全部腐爛**，見下。這是本場最有價值的副產物。
4. 正式站在 `SideProject\lift-log-prod\`（見 `docs/operations.md` 第 1b 節）。

## 本場做的事（2026-08-22 第八場 dispatch）

收件匣答案是「我手機連著電腦 你可以直接驗」——解鎖的是**真機驗收**，所以挑了四條要真機的
（F89／F95／F104／F128）裡唯一「實作已完成、只差驗」的 **F95**。

| 項目 | 結果 |
|---|---|
| 真機驗收 F95 | SM-N9750 / RF8NB0BSEFE，安裝 prod v158（原 v156）；③④⑤⑥ 全 PASS |
| `tests/e2e/verify_f95.py` | 修好後 **9/9 passed**（原本連設定頁都到不了） |
| `uv run pytest` | **486 passed** |
| `uv run ruff check .` | 全過 |

### E2E 腐爛：F146／F149 打斷了所有 native 模式的腳本

`verify_f95.py` 卡在 `wait_for_selector("input")`：假 plugin 宣告 `isNativePlatform: () => true`，
但 F149 之後 app 版 setup 只剩 Google 登入，**沒有 token 輸入框**。修法三件（腳本內，未動產品行為）：

1. 假 plugin 補 `AuthSession` / `LocalStore` / `Sync`（形狀抄 `verify_f144.py`），讓開機路徑走得完
2. 假 access token 用 e2e server 的 `LIFTLOG_TOKEN`，否則每支 API 401
3. `**/api/mcp-tokens/**` stub 成 `[]`——那支對 legacy scope **一律 401**（F147 刻意的），
   401 會被 `guard()` 判成登入失效踢回 setup。
   ⚠ 這條 route 必須註冊在 `reroute_public_host()` **之後**：Playwright 是後註冊的先比對

**同型的腳本還有 18 支**（f61–f71、f89、f103–f108、f141、f144…），本場只修了 f95。
要一次掃完的話，把上面三件抽成 `verify_f67.py` 的共用 helper 比較划算——但那會動到共用檔，
建議獨立開一條 feature 做。

### ⑥ 的 OEM 落差（判 PASS 但要記著）

acceptance ⑥ 寫「長按休息倒數通知 →『關閉這類通知』」，但 One UI 的長按面板只給
**app 層**的「關閉通知」（確認框寫「關閉此應用程式的通知嗎？」），那顆 channel 層的按鈕
在這支手機上不存在。改由系統「通知類別 → 休息倒數」製造同一個系統狀態
（`rest-timer` importance=0、app 層仍允許）驗完，並確認**開回去也會自動變回「開」**。

### ⑤ 的文案為什麼在真機上拍不到

`enableNativeNotify()` 同一個 tick 內既 `showError()` 也 `openSettings()`，系統設定頁立刻蓋掉畫面；
回 app 時 resume 重繪已把 `state.error` 清掉。連拍與返回後回捲都試過。文案判定改由 E2E 承擔。

### 裝置狀態已還原

`rest-timer` importance 回到 2、測試那組（伏地挺身 0kg×8）已刪、自由訓練已結束、
首頁「本週進度」回到 1/3。app 層通知設定全程未改。

### 沒出 APK

F95 本場只改了 `native-notify.js` 的一段**過期註解**（沒有行為變更），device 上跑的就是既有的
v158 prod APK。要出的話 `state.js` 得先升版，本場沒有值得升的東西。

## 卡住的事

- 剩下 8 條 failing：F89／F104／F128 要真機**且**還有未決事項（F89 ⑥ 的規格落差要簽核、
  F104／F128 有待拍板的方向題）、F124／F128／F160／F166 未簽核（`delegation-warmup` hook 擋 executor）、
  F149 要 Ryan 的 Google 身分、F153 要真 LLM key ＋ 人工對照。
- **手機還連著就能再驗**：F89 剩下的是 ⑨ 的 160ms 過場與 reduced-motion 觀感、⑧ 的逐條回歸，
  但 ⑥ 的規格落差要先簽核才能改 passing。
- 本場沒排保溫鬧鐘：`ScheduleWakeup` 只在 `/loop` dynamic mode 可用，headless dispatch 進不去。

## 上一場做的事（2026-08-22 第七場 dispatch）

只做歸檔收尾（commit `7651152`）：F161 原文從舊 `acceptance.jsonl` 搬進 `features.jsonl`、
主檔移除 F161／F162 骨架，`--dsm` 前後逐字相同、pytest 486 passed、ruff 全過。
並投了一筆 question 說 8 條全卡住。
