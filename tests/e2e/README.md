# tests/e2e — 前端回歸腳本

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_fNN.py`

**不要**用 `uv run --with playwright`——那是 ephemeral 疊裝，冷環境每次重建很慢。
Playwright 已是 dev 依賴，瀏覽器由 `init.sh` 的 `uv run playwright install chromium` 裝好。

## 兩批腳本，狀態不同

### 現役（verify_f61 起）

共用 `verify_f67.py` 的 helper（`start_server` / `setup_and_home` / `start_from_home` / `PHONE`），
所以 F81 首頁改版時只要改 `start_from_home()` 一處，全批跟著活。**新腳本一律走這條路，別自己複製一份啟動樣板。**

### 🟡 隔離區（verify_f48–f60，2026-07-30 從舊 session 的 scratchpad 搬進來）

**這 13 支目前跑不起來，不是現役回歸防線。** 放進 repo 的目的是**保存**——
它們原本散在 `%TEMP%\claude\...\scratchpad\`，那些目錄不保證長存，再不搬就沒了。

失效原因：全部在等 `.home-start`，而 F81 首頁改版後那個 class 已不再出現在 DOM
（只剩 `app.css` 裡一條沒人用的規則）。每支還各自複製了一份 `free_port` / `start_server` 樣板，
所以 F81 改的時候沒有一個地方能一次修好——這正是現役那批改走共用 helper 的原因。

而且失效不只在首頁：它們測的 /body、日曆、logger、編輯課表，正是 F86–F89 陶土夜色改版要重做的畫面。
**現在翻新等於做兩次**，所以翻新綁在對應的改版 feature 裡，不另外開一場：

| 腳本 | 翻新時機 |
|---|---|
| `verify_f53`–`verify_f58`（/body） | **F87 體重體脂改版**（該頁 DOM 本來就要重做） |
| `verify_f59`、`verify_f60`（動作表現、批次列） | **F86 動作表現改版** |
| `verify_f48`–`verify_f52`（課表清單／編輯頁） | **F88 編輯課表改版** |

翻新的做法：刪掉自帶的啟動樣板，改 import `verify_f67` 的 helper，並把 `.home-start`
換成 `start_from_home()`。**條文的目的不變，變的是手段**——照 handoff「上游 feature 改動讓下游測試失效」
那節的處置原則：先分辨「測試過期」還是「產品回歸」，過期就改驗目的、不改寫凍結的 acceptance。

⚠ 在翻新之前，**別把這批的「沒跑」當成「通過」**。這與 handoff 記錄的四次「假綠」同族，
只是型態換成「假存在」——目錄裡有檔案，看起來像有覆蓋，實際上一條都沒跑。
