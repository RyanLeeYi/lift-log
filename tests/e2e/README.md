# tests/e2e — 前端回歸腳本

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_fNN.py`

**不要**用 `uv run --with playwright`——那是 ephemeral 疊裝，冷環境每次重建很慢。
Playwright 已是 dev 依賴，瀏覽器由 `init.sh` 的 `uv run playwright install chromium` 裝好。

## 兩批腳本，狀態不同

### 現役（verify_f61 起）

共用 `verify_f67.py` 的 helper（`start_server` / `setup_and_home` / `start_from_home` / `PHONE`），
所以 F81 首頁改版時只要改 `start_from_home()` 一處，全批跟著活。**新腳本一律走這條路，別自己複製一份啟動樣板。**

### 🟡 隔離區（verify_f48–f60，2026-07-30 從舊 session 的 scratchpad 搬進來）

**這批原本 13 支多數目前跑不起來，不是現役回歸防線**（`verify_f59`／`verify_f60` 已於
F86 ⑩ 翻新完成，`verify_f48`–`verify_f52` 已於 F88 ⑩、`verify_f53`–`verify_f58` 已於 F87 ⑭ 翻新完成
（皆 2026-08-19），現況見下表；13 支全部翻新完畢，隔離區已清空）。放進 repo 的目的是**保存**——
它們原本散在 `%TEMP%\claude\...\scratchpad\`，那些目錄不保證長存，再不搬就沒了。

失效原因：全部在等 `.home-start`，而 F81 首頁改版後那個 class 已不再出現在 DOM
（只剩 `app.css` 裡一條沒人用的規則）。每支還各自複製了一份 `free_port` / `start_server` 樣板，
所以 F81 改的時候沒有一個地方能一次修好——這正是現役那批改走共用 helper 的原因。

而且失效不只在首頁：它們測的 /body、日曆、logger、編輯課表，正是 F86–F89 陶土夜色改版要重做的畫面。
**現在翻新等於做兩次**，所以翻新綁在對應的改版 feature 裡，不另外開一場：

| 腳本 | 翻新時機 |
|---|---|
| `verify_f53`–`verify_f58`（/body） | 已翻新（F87 ⑭，2026-08-19）——刪掉自帶的啟動樣板，改用 `safe_port`／`start_server`；`.home-start` 早於此輪之前已換成 `wait_home()`（不需要 `start_from_home()`：這批走底部導覽直接進 `/body`，不經開練流程）；現役可跑，不再是隔離區 |
| `verify_f59`、`verify_f60`（動作表現、批次列） | 已翻新（F86 ⑩，2026-08-19）——刪掉自帶的啟動樣板，改用 `safe_port`／`start_server`；現役可跑，不再是隔離區 |
| `verify_f48`–`verify_f52`（課表清單／編輯頁） | 已翻新（F88 ⑩，2026-08-19）——刪掉自帶的 `free_port`／`wait_up`／`subprocess.Popen` 樣板，改用 `verify_f67` 的 `TOKEN`／`safe_port`／`start_server`；本來就沒有殘留的 `.home-start`（改版過程中已先換成 `wait_home`／`start_from_home`）。現役可跑，不再是隔離區 |

翻新的做法：刪掉自帶的啟動樣板，改 import `verify_f67` 的 helper，並把 `.home-start`
換成 `start_from_home()`。**條文的目的不變，變的是手段**——照 handoff「上游 feature 改動讓下游測試失效」
那節的處置原則：先分辨「測試過期」還是「產品回歸」，過期就改驗目的、不改寫凍結的 acceptance。

⚠ 在翻新之前，**別把這批的「沒跑」當成「通過」**。這與 handoff 記錄的四次「假綠」同族，
只是型態換成「假存在」——目錄裡有檔案，看起來像有覆蓋，實際上一條都沒跑。

#### 2026-07-30 的一次實測（F94）：上面那段結論被證實了

F94 原本打算「先讓 13 支跑起來，改版留給 F86–F88」。實際動 `verify_f48` 之後，
一層一層卡的是：`.home-start`（F81）→ 版號搬進設定畫面（F81）→ 課表入口的 emoji 沒了（F76）
→ 挑課表的項目 `.exercise-item` 改名 `.tpl-choice`（F82）→「結束訓練」搬出 `.picker-foot`（F83）
→ 今日菜單整段重做（F83）。**改到第六層還沒到底，而後面每一層都在改版後的畫面上。**

也就是說「先跑起來、改版之後再說」這條路不存在——要讓它跑起來，就是在對改版後的畫面重寫，
那就是 F86–F88 ⑩/⑭ 本來要做的事。這一節原本的判斷（翻新綁在對應改版 feature）是對的。

## 共用 helper（`verify_f67.py`）

新腳本一律 import 這些，不要自己複製：

| helper | 用途 |
|---|---|
| `start_server(port, db, release_dir)` | 起一台隔離的測試伺服器 |
| `safe_port()` | 取埠。**不要用 `free_port()`**——Windows 動態埠範圍是 1024-15000，會抽到 Chromium 的 unsafe port（6669 等）直接 `ERR_UNSAFE_PORT` |
| `e2e_tmp()` | 暫存檔的家（系統暫存目錄）。**暫存 DB 不要建在 repo 內** |
| `setup_and_home(page)` / `wait_home(page)` / `start_from_home(page)` | setup token、等首頁、按主要入口 |
| `open_settings` / `back_home` / `read_version` / `open_templates` / `end_workout` | 導覽。畫面改版時改這裡一處 |
| `reroute_public_host(page, base)` | app 版模擬時把公開站請求導回本機（不碰正式站） |

### 防呆提案：怎麼讓「腳本隨 UI 改版靜默失效」更早被發現

F48–F60 從 F81（7/29）壞到 F93 驗收（7/30）才被當成問題，中間還被誤報成「F93 的回歸」白查一輪。
共用 helper 解決了一半（改一處全批跟著活），另一半是**偵測**——目前沒有任何機制會告訴你某支腳本已經死了。
三個方向，依成本排序：

1. **腳本清單化**（最便宜）：`tests/e2e/` 放一份 `manifest.toml` 標每支的狀態（現役／隔離）與最後通過日期。
   隔離超過 N 天就在 handoff 開場提醒。缺點是要人手更新，會漂移。
2. **每晚全量跑一次**：排程工作跑完把結果寫進 `.harness/`。抓得到真回歸，但 13 支目前必紅，
   得先有辦法區分「已知壞掉」與「新壞掉」，否則變成人人忽略的紅燈。
3. **入口 smoke test**（推薦）：一支很小的腳本只驗共用 helper 本身走得通
   （setup → 首頁 → 課表 → 設定 → 開練 → 結束）。UI 改版讓 helper 失效時**它會第一個紅**，
   而不是等某支 feature 腳本在第六層才炸。成本低、訊號明確，且不需要維護清單。

**未實作**——F94 ⑥ 只要求提案。
