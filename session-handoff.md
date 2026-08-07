# session handoff

最後更新：2026-08-07 夜（**126/138 passing**；F134／F137 已收，F135 實作寫完但仍 failing。線上仍 v124，最新正式版 APK 仍是 v139-F130）

## 接手就看這段（8/7 第二場收官時的狀態）

**這場只做了一件事：F135（高 N 時折線圖點重疊）的實作 ＋ 自己那份 E2E。**
commit `d0eeeda`，已 push。**F135 仍是 failing**，缺的是 review 與獨立驗收。

| 完成定義（F135 ⑦） | 狀態 |
|---|---|
| `verify_f135.py` 釘住 N=50／N=21 的直徑與相鄰圓緣間距 | **23/23 pass**（N=50 未選中點 4.00px、N=21 6.00px、N=21 相鄰圓緣間距 6.00px ≥ 1px） |
| `verify_f134.py` 不回歸 | **60/60 pass** |
| `uv run pytest`（前端 feature，跑子集） | `tests/test_exercises.py` 10 passed |
| `uv run ruff check .` | 乾淨 |
| `APP_VERSION`／`CACHE_NAME` 同步升號 | **v146** 兩處都升了 |
| **`/codex-review`** | **沒跑** |
| **獨立驗收** | **沒跑**——`verify_f135.py` 是我這條線寫的，逐條判定不能由同一條線收 |
| **dev APK ＋ 真機 320px** | **沒出、沒驗**（⑦ 明文要求） |

**修法一句話**：未選中點與 PR 獎盃 icon 依區間內點數 N 分級縮小（≤20→8px／21–40→6px／>40→4px，
獎盃 11／9／8px），只改 CSS class，**x 座標公式與命中判定完全沒動**，所以 F134 ⑥ 的命中寬與
⑤「頭尾與內部一致」都不受影響（verify_f135 的 ⑤ 有逐點量出來）。選中點維持 13px ＋ 光暈（③）。

⚠ **④ 的獎盃在 N=50 下仍然重疊**（icon 8px、點距 5.03px，最小間距 **-2.97px**）。
這不是漏做：條文 ④ 寫的是「重疊無法避免時可縮小 icon，但不得省略任何 PR 標記」，
腳本把它印成 `[量測]` 而非斷言。**驗收者要自己判這算不算滿足 ④**——測資是 50 筆全累進 PR 的極端情境。

**下一步最短路徑**：① `/codex-review`（Codex 額度上場已用盡，可能要退 `claude -p`）→
② 出 dev APK 真機驗 320px → ③ 獨立驗收 → ④ 改 passing → ⑤ 然後做 **F136**（`touches` 與 F135 完全重疊，只能串行）。

**順帶**：`CLAUDE.md` 補了「Vault 連動」一段（`0c4cec0`）——之前 repo 裡沒有指向 vault
PLAN／DEVLOG／DECISIONS 的入口，開場容易漏讀。

## 前一場（8/7 白天）收官時的狀態

**這場收掉三條**：F131（背景記組即時寫入）、F132（日曆補記組號）、F133（組號唯一約束）全部 **passing**，三要件（evidence／reviewed_by／verified_by）都齊。F133 已 ff 併入 main，migration 也在真 `liftlog-dev.db` 套用了。

**F134（折線圖）差最後兩步**

| 已完成 | 還缺 |
|---|---|
| 實作已 ff 併入 main（`63962a4`）；`verify_f134.py` **46/46**、pytest 296、ruff 乾淨；`verify_f86` 38/38、`verify_f87` 38/38、`verify_f59`／`verify_f58` ALL PASS（在**主工作區**跑的，見下方 F137 的陷阱）；review 的 P1 已修並自證會紅；v145 dev APK 已出並裝上手機 | ① **獨立驗收沒跑**（我指揮了實作，逐條判定不能由我來）② **真機 320px 觸控沒驗** ③ 以上過了才改 passing、才出正式版 APK |

**真機 320px 那步有個字面問題**：F134 ⑫ 寫「真機確認 320px 寬的觸控命中」，但 Note10+ 原生不是 320dp。做法是 `adb shell wm density 540`（1080 ÷ 320 × 160 = 540 → 邏輯寬度剛好 320dp），**驗完 `adb shell wm density reset`**。Ryan 尚未表態要不要改用這條路（另一條是把 320px 認定為 E2E 責任、真機只驗原生寬度，那要回簽核改條文）。

**下一步最短路徑**：① 派 acceptance-verifier 驗 F134（含上面那個 density 手法，要求它還原）→ ② 過了改 passing → ③ 然後照 **F137 → F135 → F136** 的順序做（F135／F136 的 `touches` 完全重疊，只能串行）。

### 這場新開並已凍結的三條（都是 F134 的 review 副產品）

| id | 內容 | 為什麼不是 F134 的缺陷 |
|---|---|---|
| **F135** | 高 N 點重疊（320px／N=50 → 間距 5.1px，點直徑 8px 黏成一條）。**方向 ① 拍板**：未選中點依 N 分級縮小（≤20→8px、21–40→6px、>40→4px）；真正的驗收是「相鄰圓緣間距 ≥ 1px」可量測 | F134 ⑥ 的門檻 `min(44, W/N)` 在等距佈局下對內部點恆成立（`W/(N-1) > W/N`）擋不住；⑧ 又禁止縮點以外的三種解法。**Ryan 裁示不改 ⑥ 的條文** |
| **F136** | 折線圖浮動資訊沒有鍵盤／螢幕閱讀器入口（`.line-pt` 無 `role`／`tabindex`，`.line-tip` 無 `aria-live`） | 長條圖的 `aria-label` 已等價保留在 `.line-pt`，**不是無障礙回歸**，是新互動缺非指標入口 |
| **F137** | `verify_f58.py`／`verify_f59.py` 的 `REPO` **寫死主工作區絕對路徑** → 在 worktree 裡跑會測到主工作區的舊碼 | 既有基礎設施缺陷。F134 的 agent 因此吃過一次假失敗。**危險的一半是假通過**——驗收要求「在 worktree 改個 DOM，證明腳本看得到」 |

F137 排在 F135／F136 之前是刻意的：不先修掉它，後兩條在 worktree 裡的驗收本身不可信。

### F86 ⑤ 已標 `superseded_by: F134`（`83de4b7`）

只取代長條圖的呈現細節；`.bars-max`／`.bars-foot`／獎盃累進判定／y 值定義／空區間文案 F134 都明文承接。**F86 本身仍是 failing**（從 8/4 就是，evidence 空，與本次無關）。

### ⚠ 這場的三個坑（值得記）

1. **`isolation: "worktree"` 的 agent 從 `origin/<default-branch>` 開分支，不是本地 HEAD**（`worktree.baseRef` 預設 `fresh`）。我把 F134 規格 commit 成 `e42aed6` 才派工，worker 拿到的仍是 `9164c28`＝當時的 `origin/main`，回報「檔案不存在」後正確停工，白燒 41k token。**判準一行可查：`git log origin/main..HEAD` 有輸出，那些 commit 對 worktree agent 就不存在。** 已改全域規則與三個角色檔（見下），**沒有改 `worktree.baseRef` 設定**——那是全域開關，會讓 HEAD 停在半途分支時污染 worker 基底。
2. **沒產生變更就停工的 agent，worktree 會被自動回收、無法 resume**，只能重派。我一度以為可以 resume。
3. **測試綠在沒測到的地方**：F134 第一版 `verify_f134.py` 只量中段點的命中寬（index 3），42/42 全綠，而頭尾點其實只有半格（18px）。review 抓到後補測 index 0／n-1，改回舊公式時精準紅在那兩條。**「全綠」只證明被斷言的東西成立。**

### 這場的環境狀態（接手前先確認）

- dev(8138)／prod(8137) 都在跑。**dev server 這場重啟過**（F133 併入後要讓它跑含重試邏輯的新碼）：`/health` 回 `200 {"status":"ok","env":"dev"}`
- **`liftlog-dev.db` 已套用 F133 的唯一索引**（`ix_sets_workout_exercise_set_number_active`）。備份：`../lift-log-backups/liftlog-dev-20260807-pre-f133-migration.db`
- **prod 的索引還沒套用**：`migrate_schema()` 掛在 `app/main.py:50` 的啟動流程，prod 下次重啟自動套用（自帶「有重複資料就中止」防呆，prod 舊撞號已於 8/6 清乾淨）。驗收者判定這不擋 F133 passing
- 手機裝的是 **dev v145**，已登入
- dev DB 有這場驗收造的資料：workout 80（深蹲 #1,2,4,5,6／#3 軟刪；硬舉 #2,3,4,5／#1 軟刪）刻意保留當 F132 證據
- **`.claude/worktrees/agent-a1e004955c81f8154` 刪不掉**（OneDrive 鎖住，`git worktree remove` Permission denied）。內容已 ff 併入 main，**可以安全 prune**：`git worktree prune` 或手動刪目錄
- `G:\我的雲端硬碟\lift-log-apk` 仍不存在（Google Drive 未掛載）→ 正式版 APK 依 Ryan 決定延後，等 F134 一起出

### 全域 harness 改動（不在本 repo）

`~/.claude/` 改了三處，起因是上面第 1 個坑：`rules/common/agents.md` 的機制敘述改正（含可查判準與「不改設定」的理由）、`agents/executor.md`／`mech-executor.md`／`acceptance-verifier.md` 各加「規格檔看不到時改讀 prompt 給的絕對路徑、註明、不停工；自己推導位置仍算越界」的例外、新增記憶 `worktree-agent-base-ref.md`。改動前有跑 plan-verifier 冷讀，它砍掉了我原本要改 `worktree.baseRef` 設定的那項（4×P1／4×P2，其中「不做 C1 也行」最關鍵）。

### 這場的 review 與驗收都是 Claude，不是跨模型

Codex 額度用盡，所以 F132／F133／F134 的 review 走 headless `claude -p`、驗收走 acceptance-verifier。**跨 session、跨 context，但不跨模型**——獨立性打折，evidence 裡每條都註明了。

## 前一場（8/6）收官時的狀態

**三條 feature 各卡在哪**

| Feature | 程式碼 | 缺什麼才能改 passing |
|---|---|---|
| F131 背景記組即時寫入 | 早就寫完 | ⑥-b／⑥-c／⑦／⑧-b 的獨立驗收**沒跑完**（agent 撞額度死在中途）。附錄 A 已簽核，判準都寫死了，照著重跑一輪即可 |
| F132 日曆補記組號 | **已進 main**（`b3c39ab`），284 passed + ruff 乾淨 + 會紅的 E2E 回歸 | 沒跑 `/codex-review`、沒驗收、**沒出 APK**（v144 版號已升） |
| F133 唯一約束 | **未併，WIP 在分支** `worktree-agent-ada03419976d2c2f3`（`6a46360`） | 實作寫完但**一行測試都沒跑過**（撞額度）。要先跑 pytest／ruff、再 review、再驗收 |

**落地順序不能反**：F132 先、F133 後。F133 的唯一約束一上，日曆補記若還在自算組號，就會從「靜默寫錯」變成使用者看得到的 409。F132 已經進去了，所以這個前提現在成立。

**下一步最短路徑**：① 出 v144 APK（F132 動到 `app/static/`）→ ② 重跑 F131 那四條驗收 → ③ F133 跑測試 + review。

## 這一場（8/6）：補完 F131 兩條驗收、開並做掉組號收尾的 feature

### Ryan 這場的三個裁示

1. 日曆補記自算組號 ＋ DB 缺唯一約束 → **開兩條新 feature 標 failing**（F132／F133，acceptance 待簽核）
2. F131 缺的 ⑩-6、⑧ → **這場補完，改 passing 出正式版**
3. prod 舊撞號 → **照 created_at 重編成 1..5**

### 已完成

- **prod 舊撞號已修**：`liftlog.db` workout 33／exercise 30 依 `created_at` 重編為 1..5
  （id 69 是軟刪的，佔號 #3，未軟刪剩 1,2,4,5——符合軟刪語意）。
  全庫未軟刪重複組號現為 **0 筆**。備份：`../lift-log-backups/liftlog-20260806-111526-pre-renumber.db`
- **⑧ 永久失敗態 pass**：把 workout 78 從 dev DB 移除製造 404（curl 覆核 `POST /api/workouts/78/sets` → 404），
  背景按「完成這組」→ 浮動視窗紅字「**沒記到 1 組——回 app 處理**」；回 app 後出現既有橫幅
  「⚠ 同步失敗 1 組（點此捨棄）」，**未新增任何 UI**；按捨棄後橫幅消失。
  ⚠ **401 不能拿來驗這條**——`SetUploader.java:101` 刻意把 401 歸為可重試（review 時改的），
  永久失敗態只有真正的 4xx 走得到。
- **⑩-6 前景行為比對 pass**：v139 的 dev APK 本機沒有，從 `b9ee5f6` 重建（詳見下方陷阱），並排比對：

  | 前景操作 | v139 | v143 |
  |---|---|---|
  | 記一組 | workout 79 建立、`sets.id=440`、`#1`、標題「第 2 組」、倒數 30s | `sets.id=441`、`#2`、標題「第 3 組」、倒數 30s |
  | 原位編輯 | reps 8→9、`set_number` 不變 | reps 9→10、`set_number` 不變 |

  唯一差異＝組號來源（v139 由 JS 自算、v143 由 server 指派），即 8/5 拍板 (b) 的刻意變更。
- **修掉一處文件與碼相反**：`F131.spec_feedback` ③ 原本還寫著「Ryan 拍板 (a) 維持現狀」，
  但 8/5 晚已改判 (b) 且程式照 (b) 改了（`f829f85`）。已補 ③-續 與 ② 的例外說明。
- **F132／F133 已開條目**（failing，acceptance 待 Ryan 簽核）：
  F132＝日曆補記改由 server 指派組號（`calendar.js:432`／`504` 算的是**筆數**不是最大值，軟刪後必撞）；
  F133＝`(workout_id, exercise_id, set_number)` 唯一約束 ＋ 撞了重試，取代行程內鎖。

### 這場踩到的陷阱（重建舊版 APK 要用）

- **`npx cap sync` + `gradlew assembleDevRelease` 建出來的 dev APK 會指向正式站**。
  站別是 `scripts/build-apk.ps1` 在建置前改寫 `app/static/js/env.js` 的 `const SITE` 那一行決定的，
  只跑 gradle 不會改。第一顆 v139 裝上去就是「dev package 連 prod API」，開啟顯示「正式環境」＋
  「Token 無效」（dev token 打 prod）。**沒有登入**，prod 資料未受污染。重建時手動把 SITE 改成 `dev` 才對。
- **git worktree 建的舊版無法用 gradle 簽章**：`android/keystore.properties` 是 git-ignored，
  worktree 內沒有 → gradle **靜默**產 `app-dev-release-unsigned.apk`，不噴錯也不警告。
  解法：留在 worktree 出 unsigned，再用主 repo 的金鑰簽（金鑰不進暫存目錄）。
- **`apksigner.bat` 會吃掉含特殊字元的密碼**，報成「Unexpected parameter(s) after input APK」。
  改用 `java -jar <sdk>/build-tools/36.0.0/lib/apksigner.jar` ＋ `--ks-pass env:VAR` 才過。
- 降版安裝要 `adb install -r -d`；同簽章 → **資料與登入狀態保留**，不用重新輸入 token。

### `/codex-verify` 的判決與後續（8/6 下午）

跨模型重驗回來：**零 fail，但 9 條 unverified／untestable，不可改 passing**。Codex 自己接了 adb，
獨立重現了 ⑩-1～⑩-5（sets 443–447），完成定義也全過（284 passed、ruff 乾淨、`init.sh` exit 0）。

缺口分三類，處置如下：

1. **規格問題**（②、⑩-6、⑨）——「完全不變／完全相同／不得回歸」沒有有限邊界，**任何有限次操作都證不完**。
   驗收者不肯把代表性操作升格成 pass 是正確行為。→ Ryan 簽核了**附錄 A**（`1ad94be`），
   不改原條文，只把「怎麼算驗過」講死：A-1 五項前景比對清單、A-2 回歸判定、A-3 取證程序、
   A-4 怎麼造失敗、A-5 outbox 操作、A-6 對帳的可觀測契約。**今天的證據已滿足 A-1／A-2。**
2. **真的沒測**（⑥-b、⑥-c、⑦、⑧-b）——派 acceptance-verifier 去補，**跑到一半撞額度死掉**。
   它死前已確認 ⑧-b 的失敗態（浮動視窗紅字 ＋ 既有橫幅），但沒有完整報告，不算數。
3. **結構限制**（⑤、⑩-7）——release 版 `run-as` 被擋。A-3 已寫明可接受的取證程序（debuggable build），
   但**取證者不得是實作者**，所以還是要別人跑一次。

### 這場的委派與踩到的 subagent 陷阱

- **F132 由 executor 在 worktree 完成**：兩處自算組號都拿掉、版號升 v144、新增 `tests/e2e/verify_f132.py`
  （會紅的回歸——抽掉修法後組號變 `[1,2,4,5,5]` 與 `[2,2,3,4]`，兩處都撞號）。已 ff 併入 main。
- **`isolation: "worktree"` 的 agent 拿到的是「建立當下的 base」**，不是派工當下的 HEAD。
  今天先 commit 規格再派工，兩個 worker 的 `feature_list.json` 裡**還是沒有 F132／F133**。
  → 派 worktree agent 時，**規格原文直接寫進 prompt**，不要只給檔案路徑。
- **沒產生變更就停工的 agent，worktree 會被自動回收**；回收後 resume，它會落到共用主 checkout。
  F133 第一個 agent 兩次都正確停下（沒猜規格、沒在共用目錄動 `app/`），最後是重派一個新的才動得了。
- 兩個 background agent 最後都死於月額度上限，F133 死在跑測試之前。

### 還沒收的

- **F131 仍 failing**：補測那四條 + 重驗一輪（判準見附錄 A-4／A-5／A-6，都寫死了）
- **F132 仍 failing**：沒 review、沒驗收、沒出 APK
- **F133 未併**：WIP 在 `worktree-agent-ada03419976d2c2f3`（`6a46360`），一行測試都沒跑過
- ⑩-7 仍是「執行者＝取證者」，沒有獨立第三方驗過
- prod 站台仍是 v124（線上版本與 APK 各自獨立，這件事一直沒動）

### 環境狀態

- dev(8138)／prod(8137) 兩台 server 都在跑
- 手機裝的是 **dev v143**（v139 比對後已裝回），已登入，`SYSTEM_ALERT_WINDOW` 仍有效；
  驗收 agent 猝死留下的失敗橫幅與卡住的計時器，收官時已在手機上清掉
- `release-dev/lift-log-v139.apk` 是這場重建並簽好的，之後要再比對可以直接用
- dev DB 的 workout 79 是這場驗收造的測試資料（肩推 2 組）；workout 78 是 ⑧ 的拋棄式標的，已刪

## 前一場（8/5）：F131 真機驗收續（⑩-3 過，⑩-4 開頭撞額度）

### 新驗過的（dev APK v141，workout 76，exercise_id=2）

| 驗收 | 判定 | 證據 |
|---|---|---|
| ⑩-3 背景按下 → 立刻按 ✕ → 那組仍在 | **pass** | 12:09:45 背景按「完成這組」，1 秒後按 ✕；`sets.id=419`、`set_number=10`、`rest_seconds=51` 仍在 DB；server log 對應一筆 `POST /api/workouts/76/sets 201` |
| ⑩-2 回 app 只有一筆（再驗一次） | **pass** | 回 app 後清單只有 `#10` 一列，無重複 |

### ⚠ 待 Ryan 裁示：兩條寫入路徑的 set_number 算式不同

同一場、同一動作，前景寫入拿到 `#1`、背景寫入拿到 `#10`。原因：

- 前端算的是 **可見（未軟刪）sets 的 max + 1**
- server（③ 新增的 `_next_set_number`）算的是 **含軟刪 sets 的 max + 1**（沒有 unique 約束，跳號是刻意的）

只有在「最高的幾組都被刪掉」時才會分叉（本次 workout 76 的 1–9 全是軟刪）。
兩種都符合 ③ 的字面（「client 有帶就沿用」），所以這是規格層的取捨，不是實作 bug。
選項：(a) 維持現狀、接受偶發跳號；(b) 讓 JS 記錄路徑也不帶 set_number，統一由 server 算
（但那動到 ② 的「前景行為完全不變」）。**別自己決定，回到簽核。**

### ⑩-4 / ⑩-5 也過了（同一場稍後）

| 驗收 | 判定 | 證據 |
|---|---|---|
| ⑩-4 飛航兩組 → 開網路 → 都進、組號正確 | **pass** | 飛航下按兩組，視窗依序顯示「離線，已排隊 1 組」→「2 組」；關飛航後**不碰 app**，20 秒內 `id=421`（5 次、`set_number=12`）與 `id=422`（6 次、13）依序落地，`NetworkCallback.onAvailable` 觸發生效；落地後狀態列自動消失 |
| ⑩-5 背景按下 → `force-stop` → 重開 → 不重複 | **pass** | 12 秒後重開 app，`client_uuid=0f316374…` 仍只有 1 列（`id=423`、`set_number=14`），沒有新增列 |

### ⑩-7 原生側 pass（用 debuggable build 取證，之後已還原）

release 版 `run-as` 會被擋（`package not debuggable`），所以 Ryan 授權後改跑：
`assembleDevDebug` → 移除現有 dev app → 裝 debug 版 → 用 `.env.dev` 的 token 登入 → `run-as` 讀檔。

證據（`shared_prefs/liftlog_secure.xml`）：
- 明文 token 出現次數 **0**
- **鍵名也是密文**（`name="AWG2/QRiy6dD…"`），只有 androidx 自己的 keyset 鍵是明文
- 檔案內容是 `__androidx_security_crypto_encrypted_prefs_key_keyset__` 開頭的密文 map

**同時發現（既有狀況，非 F131 引入）**：全裝置搜同一顆 token，
`app_webview/Default/Local Storage/leveldb/000003.log` **有明文**——那是前端 `localStorage` 的那份，
從 F125 時代的 setup 畫面就這樣。⑩-7 的括號寫的是「EncryptedSharedPreferences；⑤」，
即這條管的是**原生側那份**；WebView 那份要不要處理是另一條 feature 的事，交給 Ryan／verifier 判。

**已還原**：debug 版移除、重裝 `release-dev/lift-log-v141.apk` 並重新登入，
`appops SYSTEM_ALERT_WINDOW` 重新授權（移除 app 會一起清掉）。萃取出來的 prefs 檔已刪除。

### 兩輪獨立驗收（8/5 傍晚）

1. **`/codex-verify`（gpt-5.6-terra）**：完成定義全過（`pytest 283 passed`、`ruff` 乾淨、`init.sh` exit 0）；
   **③ pass**（省略組號得 `[1,2]`、軟刪保留號碼、顯式帶值得 `7`）；其餘因碰不到手機一律 unverified，**零 fail**。
   它抓到我漏的一件事：前言要求的 `superseded_by` 沒填 → 已補（commit `09f0daf`）。
2. **acceptance-verifier（自己用 adb 重跑真機，workout 77）**：
   ①、⑧離線、⑩-1、⑩-2、⑩-3、⑩-4、⑩-5 **全部 pass**，證據是它自己按出來的 DB 列與截圖。
   仍 unverified：**⑩-6**（本機沒有 v139 可並排比對）、**⑩-7**（它評估還原風險太高，沒做）、
   **⑧ 的永久失敗態**（沒去製造 404/401）。

### ⚠ 拍板 (a) 的前提被推翻了：撞號真的會發生

我當初推薦 (a) 的理由是「跳號只是顯示，撞號才是資料問題，而 server 端把軟刪算進去就不會撞號」。
**錯的是後半句**——驗收者在 workout 77 實測到兩列同組號：

```
(430, 'e04c6235-…', 77, 1, set_number=7, 10:10:39)   ← 原生背景寫入（server 指派）
(433, '45458475-…', 77, 1, set_number=7, 10:14:12)   ← 前景寫入（JS 自己算）
```

原因不是軟刪，是**兩個寫入者各算各的**：JS 算的是它自己畫面上的 max+1，而它畫面上沒有那筆
剛剛由原生寫進去的組（還沒對帳），於是算出同一個號。**只要保留兩套算式就會有這個 race。**
(b)（JS 也不帶 `set_number`、一律 server 算）才真的消掉它。**要回去重新拍板。**

### set_number 改走 (b)，並修掉真正的根因（8/5 晚）

Ryan 8/5 改判 **(b)**：`logCurrentSet()` 不再帶 `set_number`，一律 server 算
（離線分支只在本機那份補號給畫面用）。改完跑 `/codex-review`，抓到三條，**都修了**（commit `f829f85`）：

- **P1 配號不是原子操作**（真正的根因）：`_next_set_number()` 是 SELECT MAX 再 INSERT，
  兩個 client_uuid 不同的請求同時進來會讀到同一個值。(b) 只消掉「兩套算式」，沒消掉「兩個請求」。
  修法：配號＋寫入包進 `_SET_NUMBER_LOCK`（行程內）。天花板寫在註解：多 worker 就要改唯一約束加重試。
  **留了會紅的測試** `tests/test_set_number_race.py`（兩執行緒卡 barrier 同時進場）；拿掉鎖實測會 fail。
- **P1 離線編輯把顯示用組號送出去**：`saveEditDoneSet()` 展開 `s` 會把本機那個號一起送進佇列，
  等於從編輯這條路把 client 自算組號放回來。已剔除再送。
- **P2 下一組號碼對不上**：改用 `saved.set_number + 1`，不是本機值 +1。

真機（v143）重跑原本會撞號的序列：前景 `#14` → 背景 `#15`，全 DB 已無任何重複組號。

### 舊資料已修
- dev `liftlog-dev.db`：id 433 由 `#7` 改成 `#13`（撞號那筆），全庫已無重複。
- **prod `liftlog.db` 也有撞號、但不是 F131 造成的**：workout 33／exercise 30（啞鈴彎舉，7/20）
  五筆組號是 1,1,2,2,3（id 64、70 撞 1；66、71 撞 2）。成因是 F131 之前就有的舊路徑，
  **沒有動它**——那是正式訓練資料，要不要重編號等 Ryan 決定（照 created_at 重排會是 1..5）。

### 組號機制還沒關上的兩個洞（F131 範圍外，下一場先決定怎麼開條目）

1. **日曆補記仍自己算組號**（`calendar.js:432`、`calendar.js:504`）——而且算的是**筆數**不是最大值：
   一場有 #1–#5、#3 被軟刪 → `existing = 4` → 送出 `5`，直接撞既有的 #5。
   比原本前景那條更容易撞。`/codex-review` 沒點名是因為那兩行不在這次 diff 裡。
   修法與主線同一招：把 `set_number` 那行拿掉，讓 server 算。
2. **DB 沒有唯一約束當最後防線**。現在靠行程內的 `_SET_NUMBER_LOCK`，前提是單一 uvicorn worker；
   而且**只要 client 有帶號，鎖也擋不住**（server 照單全收）——這正是第 1 點會出事的原因。
   要加 `(workout_id, exercise_id, set_number)` 唯一約束＋撞了重試，**得先清掉 prod 那筆舊撞號**。

Ryan 8/5 尚未決定這兩件要開新 feature 還是當 bug 直接修——下一場先問。

### 還沒做的
- ⑩-6、⑧永久失敗態的**獨立**證據（⑩-7 我自己驗過，但執行者＝驗收者）
- prod 舊撞號要不要修（workout 33／exercise 30，見上）
- 上面收完才改 passing → 出正式版 APK
- **F131 目前仍是 failing**；121/131 passing 不變

### 這場的環境狀態（接手前先確認）
- dev server 是我**手動起的**（mission-control MCP 連不上、服務原本沒在跑）：
  `Start-Process .venv\Scripts\uvicorn.exe -ArgumentList "app.main:app_factory","--factory","--host","0.0.0.0","--port","8138","--env-file",".env.dev"`
  ——用 Bash 背景跑會被連帶殺掉，要 detached。prod（8137）本來就在跑，沒動過。
- 手機裝的是 **dev v143**，已登入、`SYSTEM_ALERT_WINDOW` 已授權、飛航模式已關。
- 改後端要重啟 dev server 才會生效；改前端要升版號（`state.js` ＋ `sw.js`）才推得過 SW 快取。

### 環境備忘（這場踩到）
- **mission-control MCP 連不上**、`lift-log-dev` 沒在跑（站台 502）。手動起：
  `Start-Process .venv\Scripts\uvicorn.exe -ArgumentList "app.main:app_factory","--factory","--host","0.0.0.0","--port","8138","--env-file",".env.dev"`
  （port 8138 是 `mission-control/services.toml` 定的）。**用 Bash 背景跑會被連帶殺掉**，要 detached。
- 飛航模式可用 `adb shell cmd connectivity airplane-mode enable|disable`（免 root）。
- 浮動視窗倒數中只有「回 app 記下一組」，**「完成這組」要先按「停止」才會出現**——背景驗收都要先停止。

## 前一場（8/4 之七）：F131 真機驗收（做了一半）

### 已驗過的（真機 SM_N9750，dev APK v140，workout 76）

| 驗收 | 判定 | 證據 |
|---|---|---|
| ⑩-1 背景按下、**不回 app**、直接查 DB | **pass** | 18:53:42 按下 → `sets.id=417`、`exercise_id=2`、`set_number=9`（**伺服器指派**）、`rest_seconds=146` |
| ⑩-2 回 app 後只有一筆 | **pass** | `set_number=9` 只有 id 417 一列 |
| ⑩-6 前景行為不變 | **pass**（部分） | 第 7、8 組走前景路徑照常寫入（415、416） |
| ① 當場開新一輪 | **pass** | 按下後視窗立刻回到「休息中 1:54」，不等 HTTP |
| ⑧ 失敗要明確 | **pass** | 真的發生一次 400 → 視窗顯示「沒記到 1 組——回 app 處理」、app 內出現「同步失敗 1 組（點此捨棄）」 |

### ⚠ 過程中兩個發現

1. **第一次寫入 400 不是 F131 的 bug**：dev server 跑著改動前的程式碼（`set_number` 仍必填）。
   `restart_service lift-log-dev` 之後同一個操作就 201。**動前端/後端契約的 feature，驗收前先重啟 dev server。**
2. **真的抓到一個回歸並已修**（commit `8c0a21f`）：畫面長出不存在的第 10–13 組（DB 只有 9 組）。
   根因是 `refetchActiveWorkoutSets()` 注入的原生 outbox 假組，下一次回前景時**自己符合
   「有 client_uuid、沒有 id」的本機未同步條件**，於是每切一次前景就再注入一次。
   已加 `native_outbox` 標記 ＋ 跨來源以 client_uuid 去重。**資料層乾淨，是純顯示層的 bug。**

### 幻影組修法已驗過（v141）

修完後在 v140 上**沒有生效**——SW 還快取著舊的 `app.js`。**改前端就要升版號**
（`state.js` APP_VERSION ＋ `sw.js` CACHE_NAME 同步），這是 sw.js 開頭那條規則，這次踩到了。
升 v141 重建後：切三次前景，logger 穩定停在「第 11 組」（9 筆真資料 ＋ 1 筆 failed outbox），
不再每次 +1（修前是 13 → 17）。

### 還沒驗的（下一場從這裡接）
- ⑩-3 背景按下 → 立刻按 ✕／停止 → **那組仍在**（本條是 F131 的核心價值）
- ⑩-4 飛航模式背景記兩組 → 開網路 → 兩組都進、組號正確
- ⑩-5 背景按下 → `am force-stop` → 重開 → 不重複寫入
- ⑩-7 token 不得以明文存在裝置上
- 全部過了才 `/codex-verify` → 改 passing → 出正式版 APK

**注意**：dev app 的浮動視窗權限這場才授權（`appops ... SYSTEM_ALERT_WINDOW: allow`），
測試前要先確認設定頁的「浮動計時」是開的。

## 前一場（8/4 之六）：F131 實作完成

### 現況

F131（背景記組即時寫入）**已簽核凍結、程式碼寫完並通過兩輪 review**，commit `45ec320`。
`feature_list.json` 仍是 **failing** —— 缺的只有 ⑩ 的十條真機驗收。

- 測試：`uv run pytest` 283 passed、`ruff` 全過、`:app:compileProdReleaseJavaWithJavac` 過
- 版本已升 v140（`state.js` APP_VERSION ＋ `sw.js` CACHE_NAME），**APK 還沒出**
- 手機 SM_N9750（RF8NB0BSEFE）當時是連著的

### 下一場入口（照順序）

1. `.\scripts\build-apk.ps1 -Site dev -Tag F131` 出 dev APK 裝上手機
2. 跑 F131 ⑩ 的十條驗收（背景不回 app 直接查 DB、✕/停止後那組仍在、飛航兩組、force-stop、前景不變、token 不得明文…）
3. 過了才 `/codex-verify` → 改 passing → 出正式版 APK

### ⚠ 動工前必須先問 Ryan 的一件事

條文 ① 字面寫「**成功後**視窗才切休息態」，我實作成「**進 outbox 後**就切」。
理由：照字面等 HTTP 成功的話，**離線時倒數永遠不會開始**，而離線是健身房的常態；
進 outbox 已經是不可遺失的落地（跨行程存活、停止不清、失敗會回報）。
這是對凍結 acceptance 的偏離，**要 Ryan 認可或改回字面**，不可自行決定。

### 這一場的技術重點（值得記）

- **server 算 `set_number`**：`SetCreate.set_number` 改選填，`_next_set_number()` 取
  「該 workout 該動作最大組號 +1」，**軟刪的組仍佔號**（後端沒有唯一約束，重用會靜默撞號）。
  這樣原生側就不必把 F32 的規則再實作一份。
- **401 不是永久失敗**（review CRITICAL）：`SetOutbox` 沒有 failed→pending 的回復路徑，
  把 401 標 failed 等於 token 過期時整批組永久送不出去。比照 5xx `break` 保持 pending。
- **`elapsed` 要累加不要推算**：`targetSeconds - remaining` 在 ±15s 之後會歸零或多算 15 秒，
  而那個值直接寫進 `rest_seconds`。
- **`onOutboxState()` 曾經寫了沒接上**：`apply()` → `attach()` 在視窗已附著時只重畫秒數，
  `paintLogStatus()` 沒有呼叫點。機制寫了不等於接上了。
- **原生 pending 的組伺服器與前端都沒有**：不補進清單，使用者會以為沒記到而重按，
  uuid 不同 → 冪等擋不住 → 同一組兩筆。
- Codex review 這場**連兩次被中止**（背景任務 killed、無報告），退到第 2 層
  `claude -p` headless reviewer——它抓到的反而更硬。第 2 層是同模型，回報時要講清楚。

## 前一場（8/4 之五）：F130

## 這一場（8/4 之五）：架構討論 + F130（完成）

### 討論結論（尚未寫成條文，Ryan 已表態方向）

Ryan 想要「**背景記組即時寫入**」，取代 F125 現行的「排入 → 回 app 才寫」。
下一場要把它寫成 **F131 條文送簽核**（F130 已被本場佔用）。討論中確認的事實：

- **今天原生完全不打 API**（F104 ④ / F125 ② 明文禁止）。唯一例外是 APK 自我更新
  `AppUpdatePlugin.java:98`，token 由 JS 當參數傳入、原生不留。
- **既有資料遺失缺陷（v138 就有，非 F128 造成）**：`RestTimerService.java:177`，
  按浮動視窗 ✕／停止走 `ACTION_STOP` → `PendingLog.clear()`，那組從沒寫進 DB 就被清掉，
  而視窗前一秒才說「已排入，回 app 後記錄」。建議修法：`clear()` 從 `ACTION_STOP` 拿掉，
  只留在寫入成功／補送成功／結束訓練三處。**若 F131 即時寫入做了，這條自動消失**。
- **F128 草案的漏洞**：`PendingLog.enqueue()`（PendingLog.java:53）舊的還在就回舊 uuid、
  丟掉新資料。F125 下安全（按鈕鎖住按不到第二次），但 F128 讓視窗回就緒態 →
  背景第二組會被靜默吞掉。F128 若要做，得先決定單格鎖住 vs 佇列化。
- **即時寫入的技術難點**（排序）：① set_number 誰算（現在前端算好帶進來，
  `services/workouts.py:289`）→ 建議搬進 server ② token 要進原生側（現在只在 WebView
  localStorage `api.js:6`）③ 原生要自己一套離線重試 ④ 回 app 的畫面對帳（建議直接重抓
  這場 sets）⑤ workout_id 走鐘。**不是問題**：背景網路（前景服務在跑）、重複寫入
  （server 對 client_uuid 已冪等，`workouts.py:285`）。

### F130（passing，v139）

`allowBackup` true → false，並新增 `res/xml/data_extraction_rules.xml`。

**codex review 第一輪的 P1 值得記**：`allowBackup=false` 在 targetSdk 36 的 Android 12+
**不涵蓋「裝置對裝置轉移」**（換機時部分 OEM 的直接複製）。光關 allowBackup 沒有達到
宣稱的安全邊界，要靠 `dataExtractionRules` 的 `<device-transfer>` 才擋得住。

另一個容易寫錯的地方：`data-extraction-rules` 裡**只寫 exclude 時，沒列到的網域一律視為包含**，
所以兩個區塊都要逐一排除 root/file/database/sharedpref/external 五個，不能只排 root。
`android:dataExtractionRules` 是 API 31 的屬性，minSdk 24 要配 `tools:targetApi="31"`。

驗證：兩 flavor merged manifest ＋ **aapt2 dump xmltree 於已封裝的 APK 內**確認
（`allowBackup=false`、`dataExtractionRules=@0x7f100001`、versionName=139）。
codex-verify 五條全 pass，F67 20/20、F93 12/12 E2E 不回歸。

**下一場入口**：寫 F131（背景記組即時寫入）條文給 Ryan 簽核。

## 前一場（8/4 之四）：F129 —— 原生停止時凍結 rest_seconds，補 codex review P1

F127 丟棄殭屍倒數時沒先凍結 `pendingRestSeconds`，`resumeRestAfterRestore()` 直接
`stopRestTimer()`，害「滑掉 app → 通知按停止 → 重開 app → 記下一組」那組漏休息秒數。
已出貨 v137 有這個資料缺口（畫面上看不出來）。修法對照 app.js:2989 活著的 stop 路徑，
用快照＋停止時刻回推：`accumulatedMs + (resumedAt ? stoppedAt - resumedAt : 0)`。

**codex review 抓到 P1**：凍結的秒數沒綁動作，冷開機後若選了「別的」動作記組，
會被誤貼上舊動作的休息秒數。修法：discard 分支多記 `pendingRestExerciseId`
（`stopRestTimer()` 清 `restExerciseId` 前先存起來），`pickExercise()` 選到不同動作時
丟棄該值，`finish()` 換動作同樣清。

**真機驗證跑了四輪**（Note10+，每輪都精準到秒對帳，沒有一次是「大概對」）：
- 同動作（P1 修前）：174.3s → DB 174
- 同動作（P1 修後）：295.4s → DB 295
- 跨動作（P1 的目標場景）：改選別動作記組 → DB `None`（正確丟棄，沒誤貼）
- 暫停態：暫停在累計 23s，之後多耗 5 分鐘才點中停止 → DB 23（沒被那 5 分鐘拖長）
- 停止→刻意等 162.75s→重開：657.218s → DB 657（重開延遲完全沒算進去）

codex-verify 跑了四輪才過——不是實作有問題，是頭三輪逐一挑證據的形式缺口
（acceptance 忘了拿掉「草案未簽核」標記、暫停態沒測、缺明確時間戳），
每輪都是真缺口就補，不是硬凹。第四輪明確給結論：可以 passing，無實質缺口。

### 這場的操作教訓

1. **通知欄展開後的按鈕座標不要用截圖肉眼估**——列表因其他通知到達／展開狀態改變
   而頻繁位移，連續 3 次點擊誤中鄰近的其他通知或系統設定卡片（甚至跳出 Google
   Discover 文章）。改用 `adb shell uiautomator dump`（`MSYS_NO_PATHCONV=1` 前綴，
   否則 Git Bash 會把 `/sdcard/...` 誤譯成 Windows 路徑）取得 `text="停止"` 節點的
   精確 `bounds` 換算中心點，一次點中。倒數還在跑的通知（超時秒數持續變動）會讓
   `uiautomator dump` 卡在「could not get idle state」，這種情況退回展開後截圖，
   但只能用**同一張截圖內部的座標**，不能沿用前一張的位置。
2. **evidence 裡不要塞反引號包住的中文到 `python -c` 的 bash 字串**——這是全域記憶
   已經記過的坑，這場又踩了一次：`` `text="停止"` `` 被 shell 當成命令替換，
   內容被吃掉還順便真的執行了 `uiautomator dump`。改用 Edit 工具直接修字串，不經 shell。
3. **codex-verify 的第三輪一度整個崩潰**（Windows sandbox orchestrator 掛掉，
   exit -1073741502），不是 F129 的問題，是 Codex 那次執行的環境故障。
   照 skill 的退路規則重試一次（簡化 prompt）就正常了——不是每次失敗都要立刻退
   acceptance-verifier，先判斷是不是真的訊息裡就是環境錯誤字樣。
4. **Codex 驗收會針對「證據夠不夠格」而非「邏輯對不對」來回好幾輪**，屬於正常
   現象不是卡關——前三輪都指出真缺口（簽核標記沒拿掉、少一個分支沒測、
   少一個時間戳），照補就一輪輪過，不必因為輪數多就懷疑方向錯了。

## 下一場的入口：F128 草案等簽核

Ryan 原本預期「浮動視窗按完成這組之後，視窗會像 app 內一樣長出 ±15s／停止／暫停」。
現況不是這樣，根因是**開新一輪的決定在前端 JS**，而 app 在背景時 WebView 被凍住。
（記錄本身沒掉——F125 已保證。停住的是介面。）

**F128 條文已寫進 feature_list.json，status failing、標明「草案未簽核」。**
動工前要先讓 Ryan 拍板 ⑥ 的 (a)/(b)：樂觀倒數先開，但那筆寫入可能被 F125 的驗證關卡
清掉（換 workout／換動作），要不要為那種情況多做一條「這組沒記到」的回報。

最需要注意的技術點是 ④：回到 app 時前端必須**接手**原生已經在跑的那一輪，
不能再 scheduleRestNotify 開一輪新的，否則會變成兩輪各數各的。

### ⚠ 先修 F129，再做 F128

F127 的 codex review 收工後才回來，抓到一條 **P1，我已讀碼確認屬實**：

F127 的丟棄路徑直接呼叫 `stopRestTimer()`，**沒先凍結 `state.pendingRestSeconds`**。
而 `logCurrentSet()` 只有它非 null 才送 `rest_seconds`（app.js:2165）。
⇒「滑掉 app → 通知按停止 → 重開 app → 記下一組」那一組的**組間休息秒數會漏掉**。
對照組 app.js:2989（活著的 stop 路徑）有做這件事。

條文寫成 **F129**（failing，草案未簽核）。⚠ 修法有個坑：不能直接用
`restElapsedSeconds()`（那算到「現在」），要用快照 ＋ `stoppedAt` 回推。公式在條文 ④。

**這條影響已經出貨的 v137**——資料會少一個欄位，畫面上看不出來。優先度高於 F128。

## 這一場（8/4）之二：F127 —— 原生端結束的休息不再復活

Codex review F126 抓到的 P1，開成 F127 簽核後做掉。**這個 bug 比 F126 早**：
時間到那則的「停止」自 F72 ⑤ 就在，走同一條 `emit()` 遺失路徑。

做法：原生在明確結束這輪時寫 `liftlog_rest_state.stopped_at`（時間戳），
前端開機取件，`stoppedAt > restStartedAt` 就丟掉快照。
**存時間戳而不是布林旗標**是關鍵——那正是「有人按停止」與「行程被殺」的分界線，
用「服務不在了」當判準會把 F66 整個殺掉。順帶解決舊標記污染新一輪（比大小自然過關）。

### 條文踩到一個不可能存在的情境

F127 ⑥-3 寫「時間到 heads-up 按關閉（app 已滑掉）」——**這個組合不可能發生**：
F123 ③ 明訂 heads-up 只在 app 前景時貼，app 一滑掉就換手。
實測時間到那一刻 `dumpsys notification` 完全沒有 rest-alarm。
驗的是同一條程式路徑的可達形式（id 2001「休息結束」上的「停止」）。
**2026-08-04 Ryan 簽核改寫 ⑥-3** 成「休息結束通知（id 2001）的停止」，
條文與驗收證據現在一致。改寫理由連同原文一起留在 acceptance 裡，沒有把歷史抹掉。

### 這場的操作教訓

「從最近使用清單滑掉」沒有 adb 指令（`am` 沒有 remove-task）。做法是
`input keyevent KEYCODE_APP_SWITCH` → 對卡片 `input swipe` 往上。
驗完要確認**服務還活著**（`dumpsys activity services` 有 3 行）才是對的情境。

通知上的鈕座標**每次都要重新截圖算**——同一顆「停止」我第一次點空，
第二次才中，中間白跑了一輪還誤以為是復活。


## 這一場（8/4）：F126 驗收通過——而昨天的「bug」根本不存在

### 兩個誤判，都不是程式的問題

**誤判一：`actions=1`。** 昨天收工前量到的那則是**時間到**的通知（`finished` 分支本來就
只有一顆「停止」）。倒數中那則一直都是 `actions=2`。教訓：探針拿到數字之前，
先確認量的是哪一個狀態下的通知。

**誤判二：`allowNoti=false`。** 我昨天把它當成「通知被系統擋住」的證據，戳了一輪權限，
還把 dev app 整個重裝。實際上 `dumpsys notification | grep AppSettings` 顯示**幾乎每支 app
都是 `allowNoti=false`**——那是 Samsung 的別的欄位，跟能不能發通知無關。
教訓：把某個欄位當成因果證據之前，先看它在**對照組**上是什麼值。

**真正的原因**：通知就在通知欄裡，只是 Samsung 把常駐通知排在**下方**，我從來沒往下捲。
（「請勿打擾」開著時還會把 LOW 頻道整個藏掉——那是 F123 ⑦ 早就寫明的限制。）

### 驗收怎麼做的（可重複）

- 探針：`adb shell dumpsys activity services <pkg>` → `foregroundNoti=Notification(channel=… actions=N)`
  一次答出通知在不在、掛哪個頻道、幾顆鈕。要看鈕的名字與去向：
  `dumpsys notification --noredact` 裡的 `[0] "停止" -> …` / `[1] "回到 app" -> …`。
- 通知欄要看得到：先 `cmd notification set_dnd off`（**驗完還原**，這場已還原 `zen_mode=1`），
  展開後**往下捲**，再點 chevron 展開該則才會出現兩顆鈕。
- ⑦ 四條路徑逐條實測，證據寫在 F126 的 evidence 欄。

### 這場踩到的操作坑

座標點擊在**版面會變的頁面**上很容易打錯（有休息卡 vs 沒休息卡，主按鈕在不同 y）。
我的 `+15s` 連點打到了 REPS，把一組記成 16 下。**每次點擊前先截圖確認版面**，
不要沿用上一輪的座標。

### 狀態

F126 → **passing**（evidence 完整）。正式版 `lift-log-v136.apk` 已上 Google Drive。
剩下 failing：F86 / F87 / F88 / F89 ⑨ / F95 ⑥ / F105 / F124。
**線上站仍是 v124**，本機 v136——要不要部署由 Ryan 決定。

## 這一場（8/3）之三：F125 —— 背景記組改為「排入 → 回 app 寫入」，跨行程保全

方向 A 判死之後 Ryan 選了 **C-完整版**。做法與逐條驗收見 F125 的 evidence，這裡只留教訓。

### 三條可重複使用的教訓

1. **「app 切到背景」不等於「JS 被凍住」。**
   Chromium 的 page freezing 有延遲，剛切出去那幾十秒 JS 還活著、bridge 事件當場就寫入了。
   第一次驗「殺行程」時看起來全綠，其實**根本沒走到補送**——測資躲開了要測的路徑。
   真正驗到的做法：**臨時把背景分支的 `emitLog` 拿掉**出一顆一次性 dev APK，
   讓「JS 真的沒收到」成立，驗完再還原。與 F118／F121 同一類錯誤。

2. **照 review 的字面改，可能修掉假想風險卻打死真實主路徑。**
   Codex P2 要求「補送必須等於 `restExerciseId`」，照做之後真機驗到補送整個不發生
   （halt 過的那輪重開時 `restExerciseId` 是 null，而那正是主要情境）。
   風險是真的，判準不對——最後改成比 **workoutId**，才同時擋住跨場寫入又不打死主路徑。

3. **原生→前端的補送要「前端取件」，不能「原生推送」。**
   app 剛起來時 `notifyListeners` 一定會掉（前端還沒訂閱）。同一個坑的一般化版本記在 F124。

### 兩個必須記住的實作約束

- **清除只掛在使用者明確結束的路徑**（`ACTION_STOP` 分支），**不放 `onDestroy()`**——
  系統低記憶體回收服務時也會走那裡，而那正是最需要保住待記組的時刻。
- **uuid 必須在「排入」那一刻由原生生成**。前端原本是寫入當下才 `crypto.randomUUID()`，
  那樣補送會變成新的一筆，伺服器的冪等去重完全不生效。

### 順帶修掉的

`logQueued` 只在 `setDraft()` 清、`setActive()` 沒清 → 新一輪已經開始，視窗卻停在「已排入」。
**這也解釋了 8/3 稍早那筆「已排入後圓環仍寫休息中」**——不是狀態字沒更新，是新一輪真的開始了。

## 待辦：F126（條文已擬，等簽核）

倒數中的通知也要有「停止」與「回到 app」，且**倒數中的「回到 app」不停倒數**
（與時間到的 heads-up 相反）。條文草稿在對話裡，尚未寫進 feature_list.json。

## 這一場（8/3）之二：F123 —— app 內改用通知列，浮動視窗只在 app 外

F122 收工後 Ryan 想清楚要更大的改動：**app 內一律不顯示浮動視窗**。
離開計時頁時倒數照跑，app 內只留通知列橫條；時間到從上方跳 heads-up，
兩顆鈕「關閉」（＝這輪結束）與「回到 app」（＝停止＋跳回所屬動作計時頁）。
**app 外完全不變**——浮動視窗、就緒態、視窗上的「完成這組」（F104）全部保留。

### 規則收斂成一句

**視窗在 app 內只負責「你看不到的倒數」→ 現在連這個也不負責了；app 內交給通知列。**
`shouldShow()` 因此塌成 `active && !dismissed && !appForeground`，
而 `headsUpWanted()` ＝ `appForeground && !restCardVisible`，正好是視窗以前在 app 內出現的那一格。
**三個介面（卡片／heads-up／浮動視窗）任何時刻只有一個在講「時間到」。**

### 這一場最該記住的三條

1. **通知的頻道換不掉。** 已貼出的通知改頻道不會變成 heads-up，而且倒數那則每秒更新，
   同頻道等於每秒彈一次。做法是**另開一則**通知（id 2003）走 IMPORTANT_HIGH 的新頻道，
   倒數那則（2001）留在 LOW。另外 `setOnlyAlertOnce(true)` 必須設——超時每秒重貼。
2. **`stopRestTimer()` 會清 `restExerciseId`。** 第一版的「回到 app」寫成 `stop` → `focus`，
   實機測到「停了但沒跳頁」：stop 清掉了 focus 要讀的那個 id。順序必須 **focus → stop**。
   我原本的註解還把這件事寫反了——**真機驗收才抓到，不是讀 code 讀出來的**。
3. **收尾掛在既有紀律上。** heads-up 的取消放進 `stopAlarm()`，
   因為那裡本來就寫著「每一條離場路徑都要呼叫」；自己在三個呼叫點各加一次遲早漏一個。

### 已知限制（條文 ⑦ 的實機補充）

heads-up 在 Note10+ 上是 One UI 的**單行簡短樣式，兩顆鈕要展開才看得到**。
`heads_up_notifications_enabled=1`，不是被關掉，是系統的彈出樣式，**app 端無法覆寫**。

## 這一場（8/3）：F122 —— 已停止的浮動視窗不得在 app 內冒出來

Ryan 真機回報：app 外按停止 → 回 app → 切到別的頁面，視窗又出現。

**先確認它不是實作走鐘**：現況正是 F100 ③（只有 ✕ 會讓視窗消失）與 F108 ②
（不在所屬動作計時頁就顯示）相乘的結果，兩條都是凍結條文。所以這是**規格衝突**，
先跟 Ryan 討論、簽核新條文（F122）才動手。

**規則不是「有沒有計時」單一條件，是情境 × 狀態**：

|                        | 倒數中 | 已停止（就緒態） |
|------------------------|--------|------------------|
| app 外                 | 顯示   | 顯示             |
| app 內・所屬動作計時頁 | 藏     | 藏               |
| app 內・其他頁面       | 顯示   | **藏**（本次修的） |

一句話：**視窗在 app 內只負責「你看不到的倒數」，在 app 外負責整輪休息。**

改動只有 `RestOverlay.java` 兩處：`shouldShow()` 的前景隱藏條件加上 `halted`、
`setHalted()` 補呼叫 `apply()`。驗證方式與逐條結果見 F122 的 evidence。

### 這一場最該記住的兩條

1. **「藏」與「結束」是兩件事，別混用。** 另一個看起來更直覺的方案是「回前景就把這輪作廢」，
   但那要真的推翻 F100 ③，而且會因為一個不相干的動作（回了一趟 app）把待記組與調過的秒數丟掉。
   改「什麼時候藏」是 F69 本來的管轄範圍，語意乾淨、狀態不損。
2. **dumpsys 探針要有明確簽章。** overlay 在 `dumpsys window windows` 裡是
   **liftlog.dev 那個「沒有 /MainActivity」的 window**；用這個判 SHOWN/HIDDEN，
   不靠肉眼看截圖。截圖只當佐證。

### adb 導頁的坑（下次直接用）

**各頁的返回鈕不是同一顆**：計時頁／動作清單／日曆／體重是左上角圓形 ←，
**課表與表現是頁面中央的文字鈕「← 回首頁」**。我第一次批次點五個分頁時，
後三次其實原地沒動（點在空白處），dumpsys 照樣回 HIDDEN ——
**「探針是綠的」不等於「那一步真的發生過」**，每一步都要用截圖確認人在哪一頁。

## 這一場（跨 7/31 夜～8/1）

| | 內容 | 驗證 |
|---|---|---|
| F106 | 設定頁兩顆開關改真 switch，出路移到可點副標 | verify_f106 32/32 ＋ 真機 |
| F107 | 「可能延遲」改成兩個條件才警告（消滅誤報） | verify_f107 13/13 |
| F103 | 停止後可再開始、回 app 視窗消失、±15s 同步 | verify_f103 16/16 ＋ 真機 |
| F108 | 休息綁定發起它的動作（Ryan 真機回報） | verify_f108 20/20 ＋ 真機 |
| F110 | 「回 app 記下一組」跳到所屬動作的計時頁 | verify_f110 11/11 ＋ 真機 |
| F111 | 組列清單超過兩組時至少兩列 | verify_f99 19/19 ＋ 真機 |
| F112 | 就緒態可先設定這組之後的休息秒數 | verify_f112 20/20 ＋ 真機 |
| F113 | 組列編輯改懸浮視窗 ＋ 修 384×727 的 39px 觸控違規 | verify_f113 15/15 ＋ 真機 |
| F114 | 日曆頁不產生頁面捲動（標題與補記鈕同時可見） | verify_f114 14/14 ＋ 真機 |
| F119 | Ryan 裁決 B：自訂區間由五顆藥丸取代，不補回 | verify_f56 16/16 |
| F120 | 退檔說明的「最近 null 個月」；退檔目標定為「全部」 | verify_f58 10/10 |
| F118 | 補記換日期改查「那一天」而非畫面上的清單（**資料面**） | verify_f54 ＋ 先驗 RED |
| F115 | verify_f85 不再依賴「今天是幾號」 | verify_f85 94/94 |
| F121 | 動作表現頁退檔後把紀錄濾光（null 檔位算成今天） | verify_f59 8/8 ＋ 先驗 RED |
| F117 | 加動作視窗在 320×420 的雙層捲動 | verify_f52 ALL PASS |
| F109 | 360×640 休息態溢出 14px（並補查就緒態） | verify_f84 52/52 |

**已部署（2026-08-01，最新 v124）**：正式站 = v124（快照 commit facf4eb，env=prod、健康檢查 200）。
正式版 APK `lift-log-v124.apk` 已進 `release/`（F67 自我更新的來源）與 Google Drive，
`/api/app/latest` 回 version_code 124——Ryan 的正式版 app 會看到「有新版 v124」。
部署後查正式站 workouts = 7 筆，真實資料完好。手機上另有 dev v124。
（v122 也曾部署過，同一天稍早。）

## ⚠ F104 卡住了，要 Ryan 決定方向（下一場的第一件事）

實作與 E2E 都完成（16/16），原生視窗（待記組、± 兩顆、記下這組、失敗態）也做出來了，
但**真機驗出正常路徑在最主要的情境下走不通**：app 在背景按「記下這組」，那組**會記進去**，
可是 JS 整條鏈是等到 **app 回前景**才執行的——視窗因此在 3 秒門檻觸發時顯示「沒記到」。

**這推翻了我稍早的量測結論**：量到行程在背景仍是 oom_adj 200（fg-service）就推論
「WebView 會活著」。**行程活著 ≠ renderer 沒被暫停**，兩件事被我混為一談。

四個方向（A 保持一份實作／B 原生自己寫／C 原生排隊回前景補送／D 縮小到前景可用）
與各自代價寫在 feature_list 的 F104 evidence。我的意見：先試 A 並實測，不成再談 C，
B 不要走（PRD 關鍵決策二否決過）。

⑤ 的失敗態是**安全**的（不會記重複、不會開假的新一輪），所以現在的版本放著不會壞事。

## 這一段學到的（優先讀這幾條）

1. **「量到 A」不能推論「B 也成立」**（F104，最貴的一次）：行程在背景仍是 oom_adj 200
   ≠ WebView renderer 沒被暫停。我用前者推後者，做完整條 feature 才被真機打臉。
   **推論鏈上的每一步都要有自己的證據**，尤其是那種「聽起來很合理」的一步。

2. **測試驗的是公式，使用者感受到的是變化**（F111）：verify_f99 只驗「高度是列高的整數倍」，
   而 69px 是 1 列的整數倍、完全合法——所以「記到第三組時清單在眼前縮掉一半」是**全綠**通過的。
   改成驗「3 筆不得比 2 筆更矮」（相對比較）才抓得到。同一族的問題這一段出現了三次。

3. **觸控稽核會被「跑在哪個尺寸」騙過去**（F113）：計時頁的 ± 在 384×727 只有 39px，
   在 390×844 是 49px。稽核一直在跑，只是尺寸剛好避開。
   **Ryan 的實機尺寸（384×727）已釘進 verify_f102**，新的觸控規則都該加這個尺寸。

4. **跨層共享的狀態要有唯一擁有者**（F103 ② 的回歸）：`restCardVisible` 描述「人在哪個畫面」
   ＝前端擁有，卻被寫進原生 `hide()` 的每輪收尾一起清掉。判斷「這個旗標屬於誰的生命週期」
   比修 symptom 重要。

5. **旗標的名字描述「現象」時容易被讀成「意圖」**（F108）：`syncRestCardVisible` 的語意是
   「卡片看得到嗎」，true ＝ 看得到 ＝ 視窗要**藏**。我從想要的結果反推，整組斷言寫反。

6. **「暫停／停止」不等於「結束」**（F108 改壞 F103）：改共用函式時，把用到它的既有 E2E
   全部跑一遍。

7. **真機自動化用固定座標連續點會出事**：錯誤橫幅一出現整頁往下推約 180px。
   **每次 input tap 前先截圖確認版面**。

8. **假物件缺一個方法＝假的失敗路徑**（F107）：假 RestTimer 少了 `available()`，
   `startForegroundRest()` 在問它那一步就 catch 掉，看起來像「接不了手」其實連 start 都沒呼叫到。

9. **寫 evidence／handoff 一律用 scratchpad 的 .py 檔**：這一段有四次把含反引號的中文
   直接塞進 `python -c` 的 shell 字串，反引號被當成命令替換、內容被吃掉，事後才發現要補。

## 隔離區 13 支的翻新：**全部完成，13/13 ALL PASS**

F86 ⑩、F87 ⑬⑭、F88 ⑨⑩ 的「翻新腳本」那一項不再是阻塞點。

**共通失效點**（f48–f60 通掃）：
`.home-start` → `wait_home`／`start_from_home`（F81）；首頁 `.version-tag` → `read_version()`（F81）；
底部導覽 emoji → `.bottom-nav .nav-item`（F76）；「← 回首頁」→ `.back-btn`（F81，**templates 畫面例外**，
它至今仍是文字按鈕）；結束訓練 → `.end-workout, .picker-foot .btn-danger`（F83）；
`.exercise-item` → `.menu-card`／`.tpl-choice`（F82／F83）；✕ → `.tpl-item-del`（F76／F98）；
/body 的 `.ex-range` → `.range-pills`、`.ex-chartcard` → `.bars-card`、`.ex-prs` → `.pr-cards`、
`.ex-hist` → `.hist-list`（F86／F87）。

**原則：只改導覽（怎麼走到那個畫面）與已被取代的契約，不放寬任何仍然有效的斷言。**
翻不過去的紅燈一律另立 feature，不改斷言讓它變綠——這一輪因此撈出 **6 個真問題**
（F117 雙層捲動、F118 補記帶錯資料、F119 條文衝突、F120 null 文案、F121 退檔濾光紀錄、
以及 F115 測試自己的日期相依）。

### 這一輪最該記住的一條：**先量，再修**

F117 與 F109 都是「知道有問題但不知道是誰造成的」拖了很久的版面帳。
做法是在斷言旁邊加**診斷欄位**（需要多少 / 有多少 / 每個子節點各佔多高），一次就看出全貌：

- F117：`need 346 / have 336` → 只差 10px，而清單早已被壓到 0 → 差額只能從別處來
- F109：`602（四個子節點）＋ 24（gap）＋ 28（app 內距）= 654`，比 640 多 14

**兩處的診斷欄位都刻意留在腳本裡**：下次紅燈會直接說出是誰吃掉的，不必再猜一輪。
兩處也都**沒有動觸控目標**（F74／F77／F102 的間距都不放寬），差額從非觸控的內距與列距擠。

### 幾個具體的坑

- **`getMonth() - null` 是 `getMonth() - 0`**（F121）：F86／F87 加的「全部」檔位其 months 是 null，
  直接丟給 `monthsAgo` 算出來是**今天**。body.js 的 `datesFor` 早就註解警告過並處理了，
  但 exercise-detail 有**第二份重複的算式**沒跟著修 → 「唯一一次訓練在 10 天前」的動作退檔後清單全空。
  重複的算式才是 bug 的來源；修法是叫既有的那一份，不是再寫第三份。
  同一個 null 也讓退檔說明寫出「最近 **null** 個月」（F120）。
- **查「畫面上的清單」vs 查「那一天」**（F118）：補記換日期時 `body.metrics.find(...)` 查的是被時間窗
  篩過的清單，選到窗外的日子就帶入「最近一筆」的體重 → 使用者以為在補記那天，
  按下去卻把別天的體重 upsert 覆蓋上去。**資料面的錯，不是顯示問題。**
- **測試把月份交給運氣**（F115／verify_f60）：`today - 3 天` 在月初會滑到上個月，
  而日曆一次只畫一個月 → 那格根本沒被畫出來。測資要自己決定月份
  （放進「整個都在過去」的上個月固定日，或用本月 1 號）。
- **原本的測資剛好躲開 bug**（F118／F121 都是）：F118 選的日子剛好在窗內、F121 的動作剛好只練今天。
  新加的回歸都刻意造出**會分辨兩種實作的**情境，並在註解寫明「為什麼要這樣造」。

## 舊帳（沒動）

1. ~~翻新 verify_f48–f60 那 13 支~~ **已完成，13/13 ALL PASS**（見上一節）
2. **F89**：⑨ 動效觀感、⑧ onMain 條文與 F63 回歸未逐條驗
   （**⑥ 的規格落差已由 F106 解掉**——軌道與鈕現在是真的存在的零件，可照條文字面驗）
3. **F95 ⑥**：長按通知的手勢，真機
4. verify_f78 ③ 有一條既有 fail（`#000` 與陰影的硬編色，HEAD 就有，非本場造成）
5. ~~F109 360×640 溢出~~ **已解**（v133，見上方「先量，再修」）

## 這一場學到的

0-b. **旗標的名字描述「現象」時最容易被讀成「意圖」**（F108）：
   `syncRestCardVisible` 的語意是「app 內的休息卡看得到嗎」，true ＝ 看得到 ＝ 原生把視窗
   **藏起來**。我第一版把 E2E 的斷言整組寫反，差點照著錯的方向改實作。
   寫這種跨層旗標的斷言時，先問一次「true 代表什麼**現象**」，不要從想要的結果反推。

0-c. **「暫停／停止」不等於「結束」**（F108 改壞 F103 後補回）：
   第一版在 `stopRestTimer` 一律清掉這輪的所屬動作，結果浮動視窗的「再開始」算不出
   這輪屬於誰、卡片回不來。只有**真的結束**才清；halt 那條路要保留整輪的身分。
   verify_f103 抓到——**改共用函式時，把用到它的既有 E2E 全部跑一遍**。

0. **跨層共享的狀態要有唯一擁有者**（F103 ② 的真機回歸，Ryan 抓到）：
   `restCardVisible` 描述「人在哪個畫面」＝前端擁有，卻被寫進原生 `hide()` 的**每輪收尾**
   一起清掉。前端又對這個回報去重，條件改成不再變動的值之後就送不出第二次，
   第二輪起視窗就自己冒出來。**判斷「這個旗標屬於誰的生命週期」比修 symptom 重要**——
   它屬於「使用者在哪」，不屬於「這輪休息」。
   附帶一課：舊條件（含 restStartedAt、每輪 true↔false 跳）**碰巧**每輪都把它蓋回去，
   所以問題被掩護了很久。條件簡化掉一個看似多餘的項，可能同時拿掉一個沒人知道的同步點。

1. **真機自動化用固定座標連續點會出事**：錯誤橫幅一出現整頁往下推約 180px，
   下一下就打到上一列。本場因此誤關了「休息提醒」，一度以為實作壞了。
   **每次 input tap 前先截圖確認版面**
2. **假物件缺一個方法＝假的失敗路徑**：verify_f107 的假 RestTimer 少了 ，
    在問它那一步就 catch 掉，看起來像「前景服務接不了手」，
   其實連 start 都沒呼叫到。與 F95 的「假物件缺了某個 plugin」同族。
   靠「有沒有真的去問」那條前提斷言抓到
3. **跨層事件要帶足資料**：F103 ⑤ 的 payload 只有動作名時，前端無從得知該從幾秒重跑。
   兩條新路徑都設計成「只更新自己、不回送原生」，並各配一條反面斷言——
   回送會讓同一輪被啟動兩次（F100 第一版 halt→stop 互相抵銷是同一族）
4. **原生的兩態 view 重建後要重新套可見性**（F100 已學過一次，F103 的再開始鈕照做）

---

## 前一場：F66→F88 那一批（v102）

## 現況（一口氣做完 F66 → F88）

實作完成、E2E 全綠、已 commit 並 push：

| feature | E2E | 狀態 |
|---|---|---|
| F66 休息倒數持久化 | 22/22 | 驗收過，**等真機** |
| F65 通知 channel 被單獨關閉 | 8/8 | **等真機** |
| F95 前景服務 rest-timer channel | 7/7 | **等真機**（F65 review 挖出來的） |
| F94 E2E 隔離區 ＋ 暫存 DB | — | ④⑤⑥ 完成，②③⑦ **待簽核** |
| F86 動作表現改版 | 40/40 | 未派驗收 |
| F87 體重體脂改版 | 38/38 | 未派驗收 |
| F88 編輯課表改版 | 30/30 | 未派驗收 |
| **F89 浮動視窗原生重做** | — | **未動工** |

pytest 274、ruff clean、線上仍是 v96 快照（**這批還沒部署、也還沒出 APK**）。

### 下一場最重要的一件事：F89 之前先決定隔離區怎麼辦

**同一個問題出現了三次**：F94 ②③⑦、F87 ⑭、F88 ⑨⑩ 都寫著「翻新 verify_f48–f60 那批」。
實測 verify_f48 之後確認：那批不是「壞在首頁進入點」，是壞在 F76/F81/F82/F83 一連串改版，
改到第六層還沒到底。`tests/e2e/README.md` 早就寫過這個判斷（「現在翻新等於做兩次」），
我起草 F94 時沒讀它——這是我的疏忽，Ryan 簽的是我給的錯誤前提。

**建議**：三條的「翻新隔離區」子句一起處理成一個決定，不要每條 feature 各自帶一份。

### 這一批的技術重點（只記非顯而易見的）

- **F66**：「回收期間不計入」與「依實際經過時間續算」是同一個算式的兩面（暫停時
  `resumedAt=null`），不必為前者寫特例。排通知前**必須 await 權限查詢**——開機當下
  cache 還是空的，直接排會被擋掉而靜默失敗。
- **F95**：使用者實際長按的通知在前景服務的 `rest-timer` channel，不是 Capacitor 的
  `default`。F65 的假 plugin 沒有 RestTimer，所以整條主要路徑在測試裡不存在。
  **「假物件缺了某個 plugin」是假綠的新型態**。
- **F86**：獎盃圖示與長條擠在同一欄裡 → 有獎盃的欄可用高度少 12px → 最高那根被壓縮，
  比例從 0.80 變 0.88。E2E 若只驗「有畫出長條」完全看不到。
- **F87**：`months=null`（全部）丟進 `monthsAgo` 會算成今天（`getMonth() - null`），
  只查得到一天。門檻重算成 710（原 656）——長條區從 96 降到 80 是**因為 Ryan 的裝置是 727px**，
  96 會讓門檻落在 726，只差 1px 就是 F84 那個坑。
- **F88**：課表名的 17px 一直被「共用輸入框樣式」蓋掉（同 specificity 靠檔案順序決勝）。

### 兩次「註解害測試失敗」

`verify_f78` 與 `verify_f88` 都用純文字搜尋確認某個 token／字元已消失，而我在**註解裡**
提到它們就被算成殘留。兩次都是改寫註解、不寫出那個字。寫防呆檢查時要記得這件事。

### 真機待辦（累積 5 條，等出 APK 後一次做）

1. F66：訓練中滑掉 app → 重開，倒數要往前跳而不是重來
2. F66：**暫停中**滑掉 → 重開按「繼續」，不能當場炸響（review 抓到的 HIGH）
3. F65／F95：長按休息通知選「關閉這類通知」→ 回 app 開關要變「關」並給引導
4. F86/F87/F88：三個改版畫面的實機截圖（各自 acceptance 的驗收要求）
5. F87：矮螢幕（你的 727px）上體重頁底部按鈕不被推出可視區

---

## 前一場：F93 測試站／正式站分離（87/94、v96）

## 現況（F93：測試站／正式站分離，已完成）

**87/94 passing。** F93 的 ④ 與 ⑪ 卡在真機，2026-07-30 Ryan 實測回報全部 ok
（兩顆 APK 並存、桌面可分辨、各自連對站、資料互不干擾），已改 passing。

- 正式站 `deploy\current` 快照 = commit `a454db3`、v96、`env=prod`；測試站 8138 吃工作目錄、`env=dev`
- 兩站公開 hostname 都回 200（打公開站**一定要帶正常 UA**，Cloudflare 對 `Python-urllib` 回 403）
- prod DB 4 場 85 組完好；dev DB 43 場 216 組，互不相干
- Google Drive：`lift-log-v96-F93.apk`（正式）／`lift-log-dev-v96-F93.apk`（測試，橘色圖示、名稱「lift-log 測試」）

### 第一輪驗收判 fail 的兩條，與修法

1. **② `deploy.ps1` 用裸 `tar`** → PATH 順序不同的機器會選到 Git for Windows 的 MSYS2 tar，
   它把 `C:\...` 當遠端主機，回 `Cannot connect to C: resolve failed`、exit 128。
   改走 `System32\tar.exe` 絕對路徑。**我這台剛好 System32 在前，所以自己測不出來**——
   驗收者換了個環境就踩到，這正是跨環境驗收的價值。
2. **⑪ 既有 E2E 回歸**：`verify_f61.py` 的「app 版請求都在 `/api/` 之下」比 F61 凍結條文更嚴
   （③ 只寫「指向公開站」），而 F93 ⑫ 明訂環境標示來源是**免 auth 的 `/health`**，天生不在 `/api/` 下。
   白名單放行 `/health`，其餘不放寬。→ 14/14。

### 部署腳本還藏著兩個「從來沒執行過」的 bug

跑真實部署才浮出來，兩個都是 `-NoRestart` 路徑掩護的：

- **`mission-control` 這個 CLI 根本不存在**（中台沒裝 console script）。stop/start 三行從第一天起
  就是 CommandNotFoundException，先前每次部署都是手動重啟才沒發現。改打中台 REST（18600）。
- 中台 `/api/*` 擋 Bearer token。改從中台自己的 `.env` 現讀 `MC_API_TOKEN`（**token 不進這個 repo**），
  讀不到就中止——不能靜默跳過重啟，那會留下「檔案換了、服務跑舊碼」的半吊子狀態。

**教訓：`-NoRestart` 之類的旁路參數會讓主路徑長期無人執行。** 驗收者也用了它，所以第一輪也沒抓到。

### 自行補驗的兩條（第一輪判 unverified）

- **⑤ 建置腳本會不會擋不符的產物**：故意把 `env.js` 裡 dev 的網址改成 prod 再 build，
  腳本在核對 APK 內 `env.js` 那步 throw、exit 1，`release-dev\` 與 Drive 的 APK hash 完全沒變。
- **⑦ Drive 檔名可分辨**：兩顆同時在，SHA-256 與 `release\`／`release-dev\` 及兩站
  `/api/app/apk` 下載到的完全一致。

### 第二輪驗收結果：10 pass / 2 unverified（只差真機）

⚠ **Codex 額度用盡到 8/5 12:46**，第二輪是 **acceptance-verifier（同模型 fresh context）** 跑的，
不是跨模型。獨立性來自乾淨上下文，比 F92 那輪弱，判讀時要打折。

驗收者實際做了（不是讀 code 推論）：真的跑了一次 `deploy.ps1` 完整部署（含 stash → 部署 →
還原，並額外驗了 dirty-worktree 保護會拒絕部署）；真的做了一顆網址不符的 dev APK 確認 exit 1
且不出貨；自己查 git 證實 F48–F60 那 13 支確實壞在 F81 之後、與 F93 無關；
另外回歸跑了 f61/f67/f78–f85/f90–f92 共 13 支全綠。

**剩下的 ④ 與 ⑪ 只差真機**，Ryan 的待辦見上方「下一場」。

一個與 F93 無關但會咬人的環境瑕疵：**Windows PowerShell 5.1 讀不了這兩支腳本的中文註解**
（非 UTF-8 codepage → 解析失敗）。手動跑 `deploy.ps1`／`build-apk.ps1` 一律用 `pwsh`。

### 新開 F94（待簽核）

`verify_f48.py`–`verify_f60.py` 共 13 支自 commit `5a72c95`（F81 重建首頁、移除 `.home-start`）起
**全數逾時失敗**，是既有債不是 F93 回歸。原先打算綁進 F86–F88 順手修，但那三條還很遠，
先獨立成 F94 免得繼續被當成「F93 的回歸」重複調查。

### 下一場

1. **F66 → F65 → F86 → F87 → F88 → F89**（F94 插在哪由 Ryan 決定）
2. ⚠ 開工先寫 `.harness/current_feature`
3. ⚠ **Codex 額度用盡到 8/5 12:46**——這段期間 review 與驗收都只能同模型 fresh context

**現在有測試站可以用了**：改前端不必再直接推到正式站。工作目錄的改動即時反映在
8138／lift-log-dev.my-super-dev-server.work，正式站只在跑 `pwsh scripts/deploy.ps1` 時才換版。

---

## 前一場：F90 ＋ F91 ＋ F92（86/92；線上與 APK 同為 v95）

## 現況

`docs/signoff-2026-07-30.md` 的簽核已全數落地（D1 選 B 保留時間窗、D2 照建議、其餘照建議）。
**86/92 passing**，線上與 APK 同為 **v95**，`lift-log-v95-F92.apk` 已上 Google Drive
（`versionCode='95'` 已用 aapt2 確認）。

### 下一場從這裡開始

**F66 休息倒數持久化**（feature_list 的第一個 failing 就是它）。剩餘順序：
**F66 → F65 → F86 → F87 → F88 → F89**。

⚠ **開工時先寫 `.harness/current_feature`**（單行 feature id）。trace 歸因 2026-07-30 起改讀這個檔，
不再猜「第一個 failing」——沒寫的話 trace 全記成 `?`，`/harness-retro` 就少了那段資料。

F66 走的是 F90/F91 剛做完的那條還原路徑（`restoreActiveWorkout()` → `confirmActiveWorkout()`），
動工前先讀那兩支的實作，特別是 `confirmActiveWorkout()` 裡「送出當下的 id 快照」與
「404／已結束／離線」三條分支的分法——F66 的還原要掛在同一個地方，且**一邊失敗不影響另一邊**（F66 ⑥）。

### F90（commit `be0785a`..`b344c67`，1 實作 + 5 筆 review 修正）

狀態從 sessionStorage 搬到 localStorage，加 `date`（**存 workout 自己的日期，不是存檔時間**——
每次存檔都寫「今天」的話，練過午夜再記一組就會把昨天那場標成今天）。
`confirmActiveWorkout()` 向伺服器確認：404 清掉、**離線不清**、401 交既有 guard，
並用送出當下的 id 快照擋過期回應。舊 sessionStorage 資料一次性遷移。

**Codex review 五輪，抓到 2+3+2+2+1 條，全部成立、全部修掉**（詳見 DEVLOG）。其中三條是我自己造成的：
- 用 `arr.length` 當組數 → 刪掉中間組後（伺服器剩 `[1,3]`）下一組又送 3，**後端沒有組號唯一約束，撞號是靜默的**
- 改成用最大組號修上一條 → 又打破 `menuCounts()` 的「完成組數」語意，課表進度提前顯示做完。
  最終解是**兩個語意分開**：`setCounts` 是組數，`nextSetNumber()` 從 `doneByExercise` 的最大組號推
- `= doneSets.length` 覆寫了離線＋舊狀態遷移時的既有進度（那條路 `doneSets` 是空的）→ 改取 max，
  並在根因處補上：`reconcileDoneSets({remove})` 原本**從來不下修 `setCounts`**

**根治了一個既有缺陷**：`SetOut` 補上 `client_uuid`（sets 表本來就有的唯一鍵，前端
`reconcileDoneSets` 早就拿它當 key）。沒有它就無法判斷「佇列裡這筆是否已送達伺服器」——
POST 成功但回應途中斷線時會重複計組。

**測試**：`tests/e2e/verify_f90.py` **30/30**、pytest **255**、ruff clean；
回歸 F70 18/18、F71 27/27、F83 35/35、F84 54/54。版號 v90 → **v92**。

⚠ **一條路徑沒有自動化測試，我不假裝有**：「多筆離線組同步失敗並被使用者捨棄後，
`setCounts` 要跟著降」。要造出那個狀態得讓 flush 收到永久性 4xx，而那通常意味 workout 已被刪、
F90 又會先一步清掉狀態，兩者互斥。這條是靠讀 code 確認的。

### F91（commit `ca65e58`..`44b4061`）：workout 結束狀態進伺服器

F90 驗收 ④ fail 長出來的——伺服器沒有「已結束」的概念，前端問不到，
所以在手機按結束、網頁那份舊快取重整就會把它接下去。Ryan 選了「補伺服器端」（選項 A）。

`workouts.ended_at` ＋ 冪等 migration（舊資料一律 null，**不回填**）；
`POST /api/workouts/{id}/end` 冪等；`GET` 單筆與列表都回傳它；
`confirmActiveWorkout()` 還原時檢查，與 404 走同一條處置。

**⑥ 已結束仍接受寫入 sets**（不回 409），理由記在 `docs/decisions/ended-workout-still-accepts-sets.md`：
擋寫入會讓「離線記完、在另一台按結束」的組被 flush 標成 failed 而遺失，
而這條要解的是**續接**不是寫入。副作用要記著：**`ended_at` 因此不是「最後一組的時間」，不能拿來算訓練時長**。

**測試**：`verify_f91.py` 20/20、pytest 263（新增 TestEndWorkout 6 條 ＋ migration 2 條）。

#### 這條的三次同型錯誤（值得單獨記）

三次 review／驗收抓到的都是同一件事：**我用自己的判斷覆蓋了簽核過的規格，而且都在註解裡寫了說服自己的理由。**

1. ④ 明文寫「之後由佇列補送」，我實作成「失敗就算了」，註解寫「那是既有行為，不因此變差」
   —— 但不補送的話 `ended_at` 永遠是 null，**這條 feature 等於白做**
2. ④ 明文寫「在清本地狀態**前**呼叫」，我實作成先清再送，註解寫「順序不能反，不能讓使用者等」
   —— 理由根本不成立：「呼叫」不等於「await」，先發 fetch 再同步清狀態，使用者一毫秒都不會多等
3. 兩次的 E2E 都是**全綠**（19/19、20/20 之前那版），因為沒有任何一條在驗這些性質

**教訓**：註解寫得越完整、越像在合理化。往後實作與凍結條文有出入時，不要在程式碼裡解釋——
回簽核。另外，**條文裡的每個限定詞（「之前」「由佇列」）都要有一條對應斷言**，
不然 E2E 全綠只證明「我做的事我測了」。

#### 一處規格 bug（已回簽核修正）

④ 原文寫「「結束訓練」與「收工」」，但 F42 起「收工」已改名並移到 picker，UI 只有一個入口。
是我起草時照抄了 `app.js` 裡一句過期註解，沒確認 UI 現況。Ryan 裁決修正條文、不新增第二個入口。
（同 F34「把紅寫成琥珀」那一類：**fail 不一定是實作錯，可能是凍結條文描述錯了現狀**。）

### F92（commit `a3e859d`..`d88a728`）：空的 workout 不該看起來像練過

Ryan 問「日曆當天沒訓練為什麼標訓練項目」查出來的。**兩個畫面對「有沒有練」的定義不一致**：
日曆明細來自 `listWorkouts`（回當天所有 workout，不管有沒有組），本週進度來自 `trained_days`
（`workouts JOIN sets`）。所以按過一次「開始訓練」就會顯示「7月30日 · 上半身」。

改法：`selectDay()` 濾掉沒有有效組的 workout；新增 `DELETE /api/workouts/{id}`（**連軟刪除的組
都沒有時**才允許，否則 409）；「結束訓練」時該場沒組就刪掉。⑦ **不改成「記第一組才建 workout」**，
理由見 `docs/decisions/workout-created-eagerly-not-on-first-set.md`。

**實作時差點做錯**：把空場從 `cal.detail` 濾掉後，補記會找不到當天既有那場而**另建一場**——
反而製造新的空 workout。要分成「顯示用 `cal.detail`」與「寫入目標 `cal.reuseWorkoutId`」。

**測試**：`verify_f92.py` 15/15、pytest 267（新增 TestDeleteWorkout 4 條）。
驗收 ①–⑪ 全 pass（codex-verify 跨模型），它另驗到我沒測的情境：同日「空場課表」與「有效課表」
兩場並存時，標題只取有有效組的那場。

#### 一次安全事故（未外洩，但值得記）

清理前的 DB 備份被 `git add -A` 掃進 commit——裡面有 `push_subscriptions` 的
endpoint/p256dh/auth（手機推播憑證）與 6 筆體重體脂。**從未推送**，已從 commit 移除、
備份移到 repo 外的 `SideProject/lift-log-backups/`、blob 已 gc 回收。
根因：`.gitignore` 只有 `*.db`，而 `liftlog.db.bak-...` 結尾不是 `.db`。已補 `*.db.bak*`。
**教訓：要備份就一開始放 repo 外，不是先放進去再想辦法擋。**

### 2026-07-30 的資料清理（一次性，已執行）

清理前 113 場 workout 有 109 場沒有有效組（開發與測試留下的）。Ryan 選「全清」，
已刪 109 場 ＋ 連帶 129 筆軟刪除的 sets，剩 4 場 85 組、0 孤兒。
真正練過的四天：7/20、7/22、7/24、7/27。備份在 `SideProject/lift-log-backups/`。

### E2E 暫存檔會愈積愈多（未解，建議綁進 F86–F88）

repo 根目錄一度累積 12 顆測試 DB ＋ 2 個空目錄（7/17 起），2026-07-30 已手動清空。
**原因不是忘了寫清理**——是 Windows 檔案鎖：`proc.terminate()` 後 uvicorn 握把還沒放掉，
`unlink` 丟 `PermissionError`。f85 是 `except PermissionError: pass` 放過，
f90/f91/f92 改成重試 10 次×0.3 秒（比較好但仍可能漏）。
**根治**：暫存 DB 改建在系統暫存目錄而不是 repo 內。翻新隔離區腳本時（F86–F88）一起做最划算。

## 🟠 另一件要 Ryan 決定的事：線上站直接吃 repo 工作目錄

這輪才發現：**開發中的每一次存檔都即時對外**。v91 帶著會產生重複組號的邏輯上線過
（`curl` 線上 `sw.js` 拿到的就是 v91），是 Codex 問「為什麼沒 bump 版號」才查出來的。已 bump v92 汰換。

後果：①半成品會直接進到手機的 PWA ②「線上版號」不能當作「已驗收版本」的代理指標
③handoff 過去寫「線上與原始碼同為 vNN」其實是同一件事的兩種說法，不是兩邊對得上的驗證。

處理方式（線上改吃 `git archive` 快照、或部署前 checkout 到 tag）會改變部署流程，**留給 Ryan 決定**。

## 🟡 tests/e2e 隔離區

f48–f60 那 13 支已從舊 session 的 scratchpad 搬進 repo（再不搬就沒了），但**目前一支都跑不起來**，
全部卡在 F81 已移除的 `.home-start`。翻新綁進對應的改版 feature（F86 收 f59/f60、F87 收 f53–f58、
F88 收 f48–f52），已寫進那三條的 acceptance。細節見 `tests/e2e/README.md`。
`pyproject.toml` 對這 13 支豁免 E501（它們從沒過 lint）；**新腳本不在豁免內**。

## 現況（7/29 改版進行中）

**83/85 passing**，剩 F65、F66（acceptance 未簽核）與 F90（新開，未簽核）。
線上與原始碼同為 **v90**，已部署；`lift-log-v90-F85.apk` 已上 Google Drive。

### 下一場從這裡開始

**F86 動作表現改版**（設計稿 README §6 ＋ `screenshots/06-exercise-trends.png`）。
照這個專案的節奏：讀設計段落與截圖 → 逐條走 acceptance → 凍結進 feature_list（failing）→
實作 → ruff＋pytest＋E2E → `/codex-review` → `/codex-verify` → 改 passing → 出 APK → commit。

F86 已知要順帶處理的兩件（前面幾條欠下來的）：**獎盃／獎章圖示**要加進 icons.js；
**時間窗 chips 從 8 顆縮到 5 顆**，這樣寬高才能同時達到 44px
（目前 8 顆是靠 verify_f78 的 `allow_narrow` 例外放行的，不是真的合格）。

### 這輪的來源：design_handoff_liftlog_clay

Ryan 給的完整視覺改版稿（README ＋ 12 張 screenshots）。拆成 F78–F89 十二條，
目前完成 8 條：F78 色票/圓角 token、F79 內嵌字型、F80 後端排程、F81 首頁＋設定、
F82 挑課表、F83 今日菜單、F84 logger、F85 日曆。**剩 F86 動作表現、F87 體重、
F88 編輯課表、F89 浮動視窗重做（原生 Java，最重）**。

Ryan 在開工時定的四件事（不要再問一次）：全部做完含浮動視窗、三套字型全內嵌、
休息控制四顆（暫停/停止/−15s/+15s，覆寫設計稿的三顆）、首頁資料走真後端排程。
色票一律**照抄設計數值**，即使對比低於 F75 訂的門檻。

### 這輪反覆踩到的同一件事：假綠

四條 feature 各抓到一次「測試綠但東西是壞的」，型態都不同，值得逐個記：

- **F78**：`verify_ui_audit` 從頭到尾只量 logger 一頁，日曆／表現／體重的觸控缺口
  **從 F77 起一路假綠**。修法是逐畫面量，不是加更多斷言到同一頁
- **F83**：改版把 F38 的「動作表現」入口從菜單卡刪掉了，**沒有任何一支測試涵蓋它**
- **F84**：兩個。(a) 我在量主按鈕前先 `scroll_into_view()`，等於那條驗收永遠不會失敗；
  改成捲動前量測立刻抓到真的溢出 142px。(b) 停止鈕的警示色**從 F73 起就沒生效**——
  `.rest-controls .chip` 的 specificity 蓋過 `.btn-danger`，而 F73 的測試只驗 class
- **F85**：明細卡加了底色之後，沒選日期時是一個佔滿下半屏的空褐色方塊。
  改版前它沒底色、空著看不見，所以**測試與網頁模式都不會抱怨**，只有實機截圖看得到

**共同結論**：「有沒有變色／有沒有被切掉／版面長怎樣」只能問渲染結果
（`getComputedStyle`、`bounding_box`），問 class 名稱一定會有假綠。

**F85 補記**：這條規則我寫在 verify_f85.py 的開頭，然後在同一支 feature 裡違反三次——展開指示符只數 `.icon` 數量（`<span class="icon">` 也會過），斷言文字卻宣稱在驗 svg。Codex 第三輪抓到。**規則寫下來很容易，套用到當下這一行很難。**

### 測試 viewport 的教訓（F84，最貴的一個）

Ryan 的 Note10+ 把顯示密度調成 600，CSS 可視高度只有約 **727px**，正好落在我用的
390×844 與 360×640 **之間**，退讓門檻訂 700px 沒生效，主按鈕當場被切掉。
門檻改成依「版面實際需要 828px」訂（不是猜「這台看起來很大」），並把 384×727
永久釘進 verify_f84。**測試尺寸是自己挑的，挑的兩個剛好把真實裝置跳過去。**

### 這輪動到的規格取代（都記在 feature_list 的 superseded_by）

- **F78 ⑦（僅日曆格子）→ F85**：設計要求月視圖包在 padding 18/16 的卡片內，
  7 欄等分後 390px 手機上格子只有 41px。「7 欄月視圖 ＋ 卡片內縮 ＋ ≥44px」無解，
  格子改由版面決定尺寸
- **F19（僅日曆單組刪除入口）→ F85**：組列改 chips 後每列不再有 🗑，
  刪除搬進編輯 modal（單擊即刪的語意不變），logger 側不動
- **F34 ①（預設全收合）→ F85 ⑧**：改成第一個動作預設展開

### 環境備忘（每次都會忘）

- gradle 要先設 `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"`
  **和** `$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"`，兩個都缺一不可
- `adb` 不在 PATH，用 `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`
- 手機 package name 是 **com.ryanleeyi.liftlog**（不是 com.liftlog.app）
- `codex exec` 放背景跑時要 `< /dev/null`，否則它會停在
  「Reading additional input from stdin...」永遠不結束
- mobile-mcp 的點擊座標是**裝置像素**，截圖是 947 寬（縮放 1.52 倍），別直接拿截圖座標點

## 現況（7/28 UI 稽核後）

**75/77 passing**，剩 F65、F66（acceptance 未簽核）。線上與原始碼同為 **v81**，已部署；
`lift-log-v81-UI.apk` 已上 Google Drive。

### 這輪的來源：ui-ux-pro-max skill

裝在 `~/.claude/skills/ui-ux-pro-max`（原始碼 clone 在 `~/.claude/vendor/`，MIT）。
用它審視全 app 後開了四條：

- **F74**：浮動視窗按鈕 48dp 觸控區 ＋ 8dp 間距。原本約 29dp——**濕手在健身房按錯
  ✕（收起）和 ⏹（結束休息）後果完全不同**
- **F75**：兩個 token 對比不合格。`--led-dim` 2.86→5.92（它用在 12px 的 REST 標籤，
  小字加低對比最糟）、`--card-edge` 1.39→3.89（明亮環境看不見卡片邊界）
- **F76**：結構性 emoji 全面改向量。web 用 `app/static/js/icons.js`（Lucide 路徑內嵌、
  `currentColor`、線寬統一），原生用 4 個 vector drawable + tint。
  **新模組要記得列進 `sw.js` 的 SHELL**——專案既有測試會抓（離線時載不到）
- **F77**：所有按鈕觸控區 ≥44px。**用 Playwright 量 boundingBox 才抓到三處 CSS 看不出來的**：
  RPE 五個停點 68×32、休息秒數 chip 110×40、動作表現入口 48×40

**副作用**：圖示換掉後按鈕的無障礙名稱從「✓ 完成這組」變成「完成這組」，
verify_f70/f71/f73 的選擇器要跟著改；`name="繼續"` 還會同時命中「繼續下一組」
（get_by_role 是子字串比對），已收斂到 `.rest-controls` 範圍內。

**沒照做的一項**：skill 建議字型換 Barlow Condensed。現行系統字 ＋ 等寬數字在手機上
載入快、數字對齊好，換 Google Fonts 多一次網路請求且離線 fallback 難看——維持原樣。

## 現況（7/28 深夜四度收工）

**71/73 passing**，剩 F65、F66（acceptance 未簽核）。線上與原始碼同為 **v80**，已部署；
`lift-log-v80-F73.apk` 已上 Google Drive。

### F73：鬧鐘響時「停止」變色

計時頁的停止鈕轉紅＋輕微脈動；浮動視窗的 ⏹ 加紅色圓底。暫停中不算「響著」，不變色。

**實測抓到的坑（值得記）**：第一版用 `setTextColor()` 改浮動視窗按鈕顏色，**畫面完全沒變**——
⏹ 是 emoji，而 **emoji 是彩色字形，`setTextColor()` 對它無效**。改成設 view 底色才生效。
另外跨越 0 秒那一刻沒有 `render()`（ticker 只改文字），所以 class 也要在 ticker 裡一起切，
否則要等下一次重繪才變色，而那幾秒正是最需要它醒目的時候。

## 現況（7/28 深夜三度收工）

**70/72 passing**，剩 F65、F66（acceptance 未簽核）。線上與原始碼同為 **v79**，已部署；
`lift-log-v79-F72.apk` 已上 Google Drive。

### F72：歸零不是結束

- 倒數歸零後**服務繼續活著**：浮動視窗顯示 `-0:38` 往上數，通知顯示「時間到！超時 1:53」
- 鬧鐘走 **USAGE_ALARM**（手機靜音／勿擾仍會響）＋ 重複震動，**不自動停止**（Ryan 明確選的）
- 因為不會自己停，**通知列一定要有「停止」鈕**——否則得解鎖開 app 才關得掉
- 停止的三條路徑（app 內⏹、浮動視窗⏹、通知列「停止」）都會 `stopAlarm()`；
  `onDestroy` 也會——**鬧鐘響著時 force-stop 已實測，聲音／服務／通知／overlay 全無殘留**
- F64 ④ 的「歸零後 overlay 自動消失」被本條取代（feature_list 已標 `superseded_by`）

**連帶清掉一處死碼**：`stopForegroundKeepNotification()`（DETACH）在 F72 之後沒有呼叫點。
verify_f63 對應的檢查原本綁那個實作手段，改綁行為本身（單一通知 id ＋ 歸零後更新同一則）。

## 現況（7/28 深夜二度收工）

**69/71 passing**，剩 F65、F66（acceptance 未簽核）。線上與原始碼同為 **v78**，已部署；
`lift-log-v78-F71.apk` 已上 Google Drive。

### F71：暫停與停止

- 計時頁 REST 卡片與浮動視窗**都**有「⏸ 暫停／▶ 繼續」與「⏹ 停止」，狀態雙向同步
- **暫停期間不計入 rest_seconds**（簽核時 Ryan 選的）：休息時間從「now − restStartedAt」
  改成累計制（`restAccumulatedMs` + `restResumedAt`），這動到 F15 以來所有讀休息秒數的地方
- 停止＝結束這段休息，等同「繼續下一組」（已累計秒數凍結給下一組）
- **✕ 只是暫時收起**：效力到你回頭看見 app 內的倒數為止，之後再離開計時頁就會再出現（⑩）
- 原生→前端走 Capacitor 事件（`notifyListeners("restControl")`），不輪詢——背景會被節流

**驗收自省**：⑩ 第一次測失敗，查下去是那輪休息已經歸零結束（`active=false`，本來就不該顯示），
**情境選錯而非實作錯**。這是 F63 ③／F68 ⑤ 之後同一族的第三次，只是這次在下判斷前先查了狀態。

## 現況（7/28 深夜收工）

**68/70 passing**，剩 F65、F66（acceptance 未簽核）。線上與原始碼同為 **v77**，已部署；
`lift-log-v77-F69-F70.apk` 已上 Google Drive。

### F69／F70：浮動計時的最終行為

- **F69**：浮動視窗只在「看不到 app 內 REST 卡片」時出現——切出 app、鎖螢幕、或在 app 內切到別的頁面。
  規則收斂在 `RestOverlay.shouldShow()` 一處；app 前不前景由 `AppForegroundTracker`
  （ActivityLifecycleCallbacks）判定，**不用** WebView 的 visibilitychange（背景會被節流）。
- **F70**：離開計時頁不再取消休息。只有「繼續下一組」「結束訓練」「401 登出」會結束休息。
  倒數目標在休息開始時快照（`state.restTargetSeconds`），否則換動作後基準會跟著新動作的參考值跳掉。

**F70 是驗收 F69 時長出來的**：F69 凍結的 ① 寫了「app 內切頁 → 浮動視窗出現」，
但實測發現離開計時頁本來就會 `stopRestTimer()`——那個狀態根本不可達。回報後 Ryan 決定改行為，
另立 F70 而不是把 acceptance 改鬆。

**裝置實測抓到、E2E 測不到的 crash**：Capacitor 的 plugin 方法跑在 `CapacitorPlugins` 執行緒，
F69 從那裡建立 overlay 的 view，之後服務的 `CountDownTimer.onTick` 在 main thread 更新它 →
`CalledFromWrongThreadException` 直接閃退。修法是 `RestOverlay` 所有進入點經 `onMain()`
繞回 main looper。**碰 view 的原生程式碼一律要問「我現在在哪條執行緒」**。

## 舊現況（7/28 稍早）

**65/68 passing**。**F64 的程式碼已完成並驗過，但 status 仍是 failing**——凍結的 acceptance ⑤-b
明定「Samsung 的 OEM overlay 限制由 Ryan 實機回報，不由實作者判 pass」，那條還沒有證據。
其餘 ①②③④⑤⑥⑦ 全部 pass（自動化由 Codex 跨模型跑、裝置層由 acceptance-verifier 在模擬器實測）。
另剩 F65、F66（F62 review 長出來的，acceptance 未簽核）。
線上與原始碼同為 **v75**，已部署。`release/` 有 v65–v73、v75（自我更新的來源，取版號最大，舊檔可回退）。

### 下一步（Ryan 回來要做的第一件事）

裝 `lift-log-v75-F64.apk`（Google Drive，或在 app 內點版號更新），到「浮動計時」按開 →
授權「顯示在其他應用程式上層」→ 記一組 → 切去別的 app 看倒數還在不在。
**回報結果就能結掉 ⑤-b**：能看到＝F64 改 passing；被 Samsung 擋掉＝那是新 feature（引導加入電池／浮動視窗白名單），
不是把 acceptance 改鬆。

### F64 完成（7/28 深夜）：休息倒數浮到其他 app 之上

`RestOverlay.java` 用 `TYPE_APPLICATION_OVERLAY` 畫一顆可拖曳的小藥丸，秒數由 `RestTimerService`
既有的原生 CountDownTimer 推——**不是**由 WebView 每秒 call 過去（overlay 的使用情境必然是背景，
JS 計時器那時已被節流）。overlay 與 F63 的通知列倒數**並存**：關掉 overlay 不會停掉倒數。

兩個踩過的坑，都與 F63 ③ 同源（狀態的握把放錯層）：
- **view 握把必須是 static**：倒數歸零後服務已 stopSelf，後續 ACTION_STOP 會建立新實例，
  握把放實例欄位就關不掉舊 view
- **Codex review P2**：按 ✕ 關掉後改休息秒數 → 前端重下 ACTION_START → overlay 自己復活。
  修法是 `dismissed` 旗標，服務停止／歸零時清除（下一輪休息才重新顯示）

**Android app 現況**：release-signed APK（`lift-log-v64-F62.apk`）已上 Google Drive；
休息倒數在手機端排程，伺服器關掉／飛航模式也照響。

### F67／F68 完成（7/28 下半場）：app 會自己更新了

**F67**：sideload 版的自我更新。`GET /api/app/latest` 與 `/api/app/apk`（都要 token），
下載與安裝在原生 plugin（`AppUpdatePlugin.java`）——APK 有數 MB，走 JS bridge 會被迫 base64 且拿不到進度。
**前提是 ① `versionCode` 不再寫死**：先前每顆 APK 都是 1，在系統眼中同一版，任何更新流程都不可能成立；
現在由 `state.js` 的 `APP_VERSION` 推導，讀不到就讓 build 失敗。

**F68**：更新提示改懸浮視窗（開 app 自動彈、稍後再說記**版號**、版號兼任提示與入口 `v70 → v71`）。
③ 原文要求保留橫幅，Ryan 認為與可點版號重疊，**回簽核改寫**。

**發佈流程**（已寫進 CLAUDE.md 規則 6 與 docs）：build 完 `Copy-Item ... release\lift-log-v<N>.apk`，
`release/` 是自我更新的唯一來源（取**版號最大**，舊檔留著可回退），已 gitignore。

#### 這兩個 feature 的教訓（都與測試的盲點有關）

- **E2E 抓到兩個實作 bug**：①開機查更新時還在 setup 畫面、沒有 token，401 被吞掉之後再也不查——
  首次設定 token 的人到下次開 app 才看得到更新 ②`disabled: false` 在 HTML 仍算停用（有屬性就算數），
  橫幅點不下去。專案慣例是條件展開 `...(cond ? { disabled: "" } : {})`
- **驗收抓到我刻意做的錯誤決定**（F68 ⑤）：下載失敗時我主動關閉視窗、改用頁面 error-banner，
  註解裡還寫了理由——但條文寫的是「失敗訊息呈現在視窗內」。**我用自己的判斷覆蓋了簽核過的規格**。
  更關鍵的是 verify_f68 當時**完全沒有失敗路徑的斷言**，24/24 全綠掩護了它。補完後 29 條
- **我自己留過一條 `or True` 的假斷言**（永遠不會失敗＝空跑測試），已移除。與上面同源：
  **測試沒覆蓋到的地方，全綠沒有意義**

#### 驗收範圍的取捨（本場有意識地調整）

F67 驗收耗時 **51 分鐘**（重跑三套 E2E）。F68 起刻意縮範圍——只跑直接受影響的 verify_f68 與 verify_f67，
F61／F62 註明採信實作者紀錄。結果：**7 分鐘**，而且抓到了前一次沒抓到的 ⑤ fail。
複驗用 **SendMessage 接續同一個驗收者的 context**（不是新開），它記得自己上次的判準，2 分鐘完成。
判準：**改到共用模組就把範圍放回去**，只動呈現層就縮。

### F63 完成（7/28）：休息倒數進了通知列

前景服務（`RestTimerService` ＋ `RestTimerPlugin`）在通知列常駐顯示剩餘秒數，手機可以放口袋。
**倒數在原生層 CountDownTimer 跑**，不靠 WebView——JS 計時器一進背景就被節流，而背景正是這功能存在的理由。
型別選 `specialUse` 而非 `shortService`（後者 3 分鐘上限，休息調長會被系統斷掉）。
⑥ 的分工：前景服務接手時**不排** F62 的本機通知，歸零時由同一則通知自己轉成「休息結束」。

**②④ 回簽核接受模擬器**（原文寫真機）：② 是系統層行為、模擬器與真機無差；④ 在模擬器 Doze
（`mWakefulness=Dozing`、`deviceidle IDLE`）下誤差 -1 秒。
⚠ **但 ④ 真正想防的風險模擬器測不到**——OEM 省電策略（Samsung 尤其積極）可能殺掉前景服務。
**真機省電行為列為後續待辦**：Ryan 若在健身房發現倒數被殺掉，那會是一條新 feature
（大概是引導使用者把 lift-log 加進電池最佳化白名單）。

#### 這輪最重要的教訓：我測的是我想像中的流程

驗收第一輪判 ③ **fail**，抓到我完全沒測到的路徑：**倒數自然歸零後**再按「繼續下一組」，
「休息結束」通知永久殘留。根因是 Android 服務生命週期——`onFinish()` 已 `stopSelf()`，
之後的 `ACTION_STOP` 會建立**全新服務實例**，它從未 `startForeground()`，
其 `stopForeground(REMOVE)` 對前一實例貼出的通知無效。
我自己在模擬器上測的是「提前取消」（那條本來就正常），所以沒發現。

**兩條路徑的程式碼看起來完全對稱**（都送 `ACTION_STOP`），差別只在時序。
修法：`ACTION_STOP` 一律 `NotificationManager.cancel(NOTIFICATION_ID)`，不依賴 `stopForeground()` 的副作用。

這與 F68 ⑤ 同族：**測試覆蓋的是實作者想像中的使用方式**。往後寫 E2E／自驗先問一句
「使用者最常走的那條路徑，我測了嗎」。

#### 另一個我自己造成的險情：build 腳本前一步失敗沒有中止

版號 bump 用了 PowerShell 裡的 inline python，跳脫字元寫壞導致**整段沒執行**（SyntaxError），
但後續的 `cap sync` 與 gradle **照跑**，產出 v72 的內容卻被複製成 `release/lift-log-v73.apk`。
若沒發現，F67 會告訴 Ryan「有新版 v73」，裝到的卻是 v72，**且不會有任何錯誤訊息**
（系統只看 APK 內的 versionCode，檔名不管）。已刪除重做並以 `aapt2 dump badging` 確認 versionCode=73。
**教訓：多步驟建置腳本要讓前一步失敗中止後續**；版號 bump 改用獨立的 Bash heredoc 較可靠。

### 下一場開場

**F67 程式碼完成但 status 仍 failing**，因為還沒部署也還沒真機驗 ④⑤。
本場在「準備部署」時撞到用量門檻（5h 92%）收工，**刻意沒做到一半**——
線上換了版但 APK 沒進發佈目錄的話，Ryan 手機上的 app 會看到殘缺狀態。

Ryan 已經裝好 v65，**他要的是一顆 v66 讓他實測整條更新流程**。照這個順序做：

1. **`.env` 加 `LIFTLOG_RELEASE_DIR`**（絕對路徑，避免服務的 cwd 與 repo 不同找不到 APK）：
   `LIFTLOG_RELEASE_DIR=C:/Users/user/OneDrive/Desktop/SideProject/lift-log/release`
   （本場查過 `.env` 目前只有 `LIFTLOG_TOKEN` 與 `LIFTLOG_DB`）
2. **出 v66**：`state.js` 的 `APP_VERSION` 與 `sw.js` 的 `CACHE_NAME` 同步升到 v66 →
   `npx cap sync android` → `gradlew -p android assembleRelease` →
   `cp .../app-release.apk release/lift-log-v66.apk`（**v65 留著**，`_latest_apk` 取版號最大值）
3. **部署**：`mission-control restart lift-log`（會一併把 v63–v66 的前端變更推上 web 版，線上目前還是 v62）
4. **驗線上端點**：帶 token 打 `/api/app/latest`，應回 `version_code: 66`；`/api/app/apk` 應下載得到檔案
5. **請 Ryan 開 app**：v65 應顯示「⬆ 有新版 v66」→ 點擊 → 首次會要求允許「安裝未知應用程式」
   （app 會直接把他帶到設定頁）→ 授權後回來再點 → 下載進度 → 系統安裝器 → 裝完版號變 v66
6. 真機 ④⑤ 過了才跑驗收、才改 passing

### F67 已完成的部分（commit `7deddf0`）

- ① **versionCode 不再寫死**：由 `state.js` 的 `APP_VERSION` 推導，讀不到就讓 build 失敗。
  已用 `aapt2 dump badging` 確認 APK 內是 `versionCode='65' versionName='65'`（先前每顆都是 1，
  在系統眼中全是同一版，**任何更新流程都不可能成立**）
- ② `GET /api/app/latest` 與 `/api/app/apk`，都要 token；發佈目錄**用數值比大小**（字串排序會讓 v9 贏過 v65）
- ④ 下載與安裝放在原生 plugin（`AppUpdatePlugin.java`）：APK 有數 MB，走 JS bridge 會被迫 base64
  且拿不到串流進度。失敗一律刪掉半截檔案
- ⑤ 未授權安裝時直接開系統的「安裝未知應用程式」設定頁（與 F62 ⑤ 同一套處置）
- 測試：pytest **205**（新增 `tests/test_app_release.py` 5 條）、ruff clean、
  `verify_f67.py` **20/20**、F62 34/34 與 F61 14/14 回歸綠

**E2E 抓到兩個實作 bug（都不是測試問題）**：
1. **首次設定 token 的人看不到更新**——開機就查更新，但那時還在 setup 畫面沒有 token，
   401 被吞掉之後再也不查。已改成設定完 token 也查一次
2. **橫幅點不下去**——`disabled: false` 在 HTML 裡仍算停用（有屬性就算數）。
   專案慣例是條件展開 `...(cond ? { disabled: "" } : {})`，沒照著寫才出事

### 下一場開場

1. **先部署**：線上還是 v62，原始碼 v64（`mission-control restart lift-log`）
2. F63 動工前**先逐條走 acceptance 再簽核**——F61／F62 兩場都證明了這步會長出新條目
3. **Codex 額度用盡到 8/2 04:04 UTC**（7d 96%、credits 0）。這段期間 review 與驗收只能用同模型
   fresh context，獨立性較弱。F62 的 review 與驗收都是這樣跑的，想補跨模型審就是 8/2 之後的事

**mobile-mcp 已註冊**（user scope，`npx -y @mobilenext/mobile-mcp@latest`）：手機接著時可直接截圖／點擊
驅動真機驗證。手機連線的坑見下方。**Android 16 模擬器（AVD `Pixel_9`）也可用**——
Ryan 遠端時手機是圖形鎖無法解鎖，模擬器是唯一能互動的裝置，且能驗到 Android 13+ 的權限路徑。

### F62（7/28 完成）：休息提醒改走手機端本機通知

**做了什麼**：新增 `js/rest-notify.js` 當統一入口——web 走 F31 Web Push、app 走
`@capacitor/local-notifications`；分流只在這個檔案發生，`app.js` 只認一個入口。
app 版補上自己的通知開關（F61 之後原生殼原本沒有任何通知入口）。
Manifest 加 `POST_NOTIFICATIONS` 與 `SCHEDULE_EXACT_ALARM`。

**真機／模擬器實測**：飛航模式＋鎖屏照響（Ryan 隨身手機）；Android 16 模擬器上
倒數歸零到通知出現差 **5 毫秒**（精確鬧鐘 `window=0`、螢幕關閉）。

**這場最重要的教訓——真機抓到 E2E 抓不到的 bug**：
出現過「開關顯示開、通知被系統丟掉」（`NotificationRecord` 有進去、`appops POST_NOTIFICATION: ignore`）。
**假 plugin 的 E2E 永遠抓不到**，因為假 plugin 是照實作者對規格的理解寫的——我誤讀了
`checkPermissions()` 的語意，假 plugin 就跟著誤讀，測試自然全綠。與 F36「測試編碼了同一個 bug」同族，
這次換成「模擬物件編碼了同一個誤解」。**凡是用假物件替身的 E2E，都要問一句：它有沒有可能只是複製了我的誤解？**

**根因我第一次講錯了，值得記著**：`checkPermissions()` 在 Android 13 以下**會**查 `areNotificationsEnabled()`，
真正查不到系統開關的是 13+ 讀 `POST_NOTIFICATIONS` 那條。症狀屬實、修正方向也對（改用 `areEnabled()` 當
唯一事實來源），但敘述錯誤。**觀察到症狀不等於找到根因**。

**review（同模型 fresh context）抓到 1 HIGH + 4 MEDIUM，全部成立**：
- HIGH：原生殼切回前景**不重載頁面**，權限 cache 從開機起可陳舊 → ⑤ 的靜默失敗會從
  「去系統設定改完再切回來」這條路復活。已掛 `visibilitychange` refresh
- MEDIUM：自寫 plugin 查不到時**靜默退回** `checkPermissions()`＝把舊 bug 放回來且畫面無跡象
- MEDIUM：精確鬧鐘只在按鈕寫「可能延遲」卻**沒有出路** → 改成可點擊直接開系統授權頁
- MEDIUM ×2 → 列為 F65／F66，不在 F62 裡順手做掉

**Android 版本差異（你手機驗不到，換手機會遇到）**：Android 12 安裝即自動授予精確鬧鐘；
**13+ 不再自動授予**，要手動開「鬧鐘與提醒」，未開時按鈕顯示「開（可能延遲，點此修正）」。

### 我在真機測試上犯過的兩個錯（下次先自檢）

1. **盲點座標**：鍵盤彈出會推移版面，照舊座標點下去會打進鍵盤區、把雜字元灌進輸入框（結果是 401）
2. **沒先確認狀態就操作**：重新授權後開關**本來就已恢復成開**，我又點一次把它關掉，
   然後把「沒收到通知」誤判成 bug。差點寫成實作缺陷回報

### Android 工具鏈現況（都已設好，不必重做）

- Android Studio 2026.1.2.10 ＋ 內含 OpenJDK 21.0.10；`JAVA_HOME`／`ANDROID_HOME`／`ANDROID_SDK_ROOT`
  已寫進使用者環境變數，PATH 有 `platform-tools` 與 `jbr\bin`
- SDK 是舊工具鏈留下的（platform-35、build-tools 35/36），**授權先前已接受**
- keystore：`%USERPROFILE%\.android-keys\lift-log-release.jks`（alias `liftlog`），
  `android/keystore.properties` 已建且被 gitignore。**金鑰遺失＝無法對同一顆 app 發更新**
- 建置：`.\android\gradlew.bat -p android assembleRelease`（~1m40s，3.1 MB）；
  改前端後**必須先 `npx cap sync android`**，否則 APK 內還是舊畫面

### 真機連線的坑（下次直接照做，省 20 分鐘）

1. **USB 埠要插主機板後方**——插前面板時 `adb devices` 一直是 `offline`，`device` 狀態撐不過一次 install
2. `offline` ≠ `unauthorized`：前者是手機端 daemon 沒回應，`adb reconnect offline` 可推它進 `unauthorized`，
   這時手機才會跳授權框（**螢幕要解鎖才看得到**）
3. 授權後裝置會重新列舉，短暫從 `adb devices` 消失，等幾秒就回來
4. 用 `adb shell input tap` 打座標時**鍵盤彈出會推移版面**——盲點會打到鍵盤區、把雜字元灌進輸入框
   （本場踩到，結果是 401「Token 無效」）。每次輸入後先截圖確認座標再點

### F61 已完成（commit `07716d6` ＋ `58e23d9`）

- **acceptance ①–⑨ 已簽核凍結**（原草稿是 ①–⑦，本場逐條走過後改寫）。**最大的變更是 ③**：
  原定用 `server.url` 指公開站，查證後發現 Capacitor 官方 config 文件明寫 *"This is not intended for
  use in production"*，live-reload 指南甚至叫人別把它 commit。Ryan 改判**資產打包進 APK**。
  代價是 app 版沒有 F13/F14/F24 的自動更新鏈（改前端＝重 build 重裝），已寫進 README
- 打包路線連帶推翻了同源假設，衍生三處實作：①`js/env.js` 偵測 `window.Capacitor` → `api.js` 加 base URL
  前綴（web 版回空字串，行為零改變）②後端 CORS 白名單只放 `https://localhost`／`capacitor://localhost`
  ③app 版不註冊 SW
- **app 版 `pushSupported()` 強制回 false**：不註冊 SW 的話 `navigator.serviceWorker.ready`
  **永遠不 resolve**，`enablePush()` 會卡死在那一行而不是報錯。這是實作中才浮出來的坑，不是規格寫的
- release 簽章設定已進 `android/app/build.gradle`：讀 `android/keystore.properties`（已 gitignore），
  **檔案不存在時 release build 產出未簽章 APK**——刻意的，讓漏放金鑰在 build 當下就暴露
- 環境（本場裝好）：Android Studio 2026.1.2.10 ＋ 內含 **OpenJDK 21.0.10**；`JAVA_HOME`／`ANDROID_HOME`／
  `ANDROID_SDK_ROOT` 已寫進使用者環境變數，PATH 補了 `platform-tools` 與 `jbr\bin`。
  SDK 是舊工具鏈留下的（platform-35、build-tools 35/36），**授權先前已接受**，`sdkmanager --licenses` 可省
- **Debug APK 已建置成功**（`gradlew -p android assembleDebug`，2m16s，4.02 MB）。解開確認
  `assets/public/` 含完整前端（含 `env.js`），APK 內 `APP_VERSION` = v62 與原始碼一致（⑤ 在打包版成立）

### F61 驗收（①–⑨ 全 pass，已改 passing）

**驗收者是 acceptance-verifier（同模型 fresh context），不是跨模型**——先派了 `/codex-verify`，
但跑太久被 Ryan喊停中止（無報告產出、工作樹未被動過），改走 `agents.md` 的 fallback。
驗收者自己重跑 pytest 200／ruff／E2E 14/14／`assembleRelease`＋`apksigner verify`，
自己操作真機走完流程，事後清掉自己造的 workout 68／set 158。

⚠ **④ 有一處分工縫隙**：驗收者是在**已有 token** 的狀態下驗的，沒重跑「首次輸入 token」。
那步由實作者在 debug／release 兩次全新安裝時各驗過一次——鏈是完整的，但不是同一個人一次走完。

### 驗證與 review（本場）

- **新增 `tests/e2e/verify_f61.py`（14/14）**——順手開了 repo 的 `tests/e2e/`，待辦第 5 條踏出第一步。
  驗 web／app 兩種環境的分歧：API 前綴、SW 註冊與否、`pushSupported()`、版號兩處一致
- **模擬的界線要記住**：app 版是靠 `add_init_script` 注入 `window.Capacitor`，頁面仍由本機供檔，
  origin 不是真的 `https://localhost`。**驗的是前端分支邏輯，不是真機行為**——所以 ④ 無可取代
- 兩個 Playwright 眉角：`route.continue_(url=...)` **不能改協定**（https→http），要自己 fetch 再 fulfill；
  斷言別停在「有發出請求」，直接 `import('/js/api.js')` 做一次真往返，否則 1 個請求也算綠（前提太弱）
- pytest **200**（新增 `tests/test_cors.py` 5 條，TDD 先紅後綠）、ruff clean、F60 9/9 與 F49 17/17 回歸綠
- **`/codex-review` 跨模型：2 findings，都在建置文件、都成立**——P1 Android Studio 的 JBR 不在外部
  PowerShell 的 PATH 上，照原文件跑 `gradlew` 會停在 `JAVA_HOME is not set`；P2 `cd android` 之後再用
  `android\app\build\...` 會解析成 `android\android\...`。已修（commit `58e23d9`）並用實際 build 驗證。
  **程式碼本身零 findings**

### 本場的流程教訓

- **「已定案」不等於「查證過」**：③ 的 `server.url` 是前一場拍板的，但官方文件明文反對。動工前花一次
  Context7 查證就翻掉了整個載入策略——**在寫第一行 code 前查，比寫完再查便宜太多**
- **acceptance 逐條走過會長出新條目**：①–⑦ 走完變 ①–⑨，多出的 ⑧（CORS）⑨（README 已知限制）都是
  「改用打包路線」的必然後果，簽核前沒人想到。Ryan 選「先逐條走一遍再簽」是對的
- **winget 靜默安裝會卡在看不見的 UAC**：`--silent` 裝 Android Studio 時，installer 程序跑了 32 分鐘、
  `Program Files` 半個檔案都沒有。非互動 session 過不了提權，只能請 Ryan 自己執行安裝檔
  （檔案已下載完，不必重抓）。這台機器上還有一支 7/23 起就卡住的 VS Code `CodeSetup`，同一種症狀

---

## 前一場（7/27 早場）現況

**60/60 feature passing**，線上 **v61**，已 deploy（mission-control restart lift-log；本機與公開 `/health` 皆 200、
公開 sw.js 已是 v61）。

**本場（7/27）只做一件事：把上一場留下的 F60 驗完。** 未寫新功能、未重寫既有實作。
- E2E `verify_f60_own.py` **9/9**（腳本自身一處 bug：用了不存在的 `/api/workouts/{id}/sets`，改讀
  `GET /api/workouts/{id}` 的 `sets` 欄位。**是腳本錯不是實作錯**）、F49 回歸 17/17、pytest 195、ruff clean
- **Codex 額度已恢復**（7d 53%），故 review／驗收都回到跨模型：`/codex-review` **無 findings**、
  `/codex-verify` **①–⑦ 全 pass** 且事後 `git status` 零改動
- codex-verify 驗到實作者腳本沒涵蓋的兩件事，值得記住：①有歷史的動作預設值確實取最重組（42.5kg × 11），
  實作者腳本只驗了無歷史的 20×8 ②**部分失敗重試路徑**——第 2 組回 500 後重試，workout POST 仍為 1、
  UUID 序列 `[A,B,A,B,C]` 證明沿用不重建（F47 那條 P1 的回歸防線還在）
- 上一場列的三個風險全被證偽（勾選態真的變、`paint()` 重建整列對連點無害、收合列實測僅 24px）

## 前一場（7/26）完成：

- **F48** 課表三處清單超過兩項改捲動（列表頁／挑課表／今日菜單）
- **F49** 有課表時「臨時加動作」收成一顆入口鈕＋懸浮視窗（自由訓練維持攤開、點動作即進 logger）
- **F50** 四處可捲清單高度改為「填滿剩餘空間」（純 CSS flex，隨螢幕高度自適應）
- **F51** 編輯課表頁動作清單也改填滿剩餘空間（F50 漏掉的第五處，Ryan 真機發現）＋三顆鈕貼底
  （`.tpl-edit-foot { margin-top: auto }`——清單跨門檻塌陷時按鈕不再上跳 156px 造成誤存）
- **F52** 編輯頁加動作視窗高度穩定（搜尋篩選時不再縮短位移）＋`.tpl-items` 併入細捲軸共用樣式＋
  四畫面改掛 `fills` marker class（CSS 兩處重複的選擇器清單合成一條）
- **F53** 體重頁改 toggle 切換體重／體脂（圖表＋紀錄清單一起切）＋紀錄清單填滿剩餘空間
- **F54** 體重頁輸入表單收進懸浮視窗（畫面只留「＋ 記錄」）——固定區塊 584→408px，
  清單實得空間 844: 177→316px、**667: 55→139px**（F53 做不到填滿的螢幕現在可以）
- **F55** 「＋ 記錄」入口鈕移到畫面下方（清單之下、「← 回首頁」之上）
- **F56** 體重頁圖表可自選時間長度（1M–3Y＋自訂、預設 3M、清單跟著篩；沿用 exercise-detail 的
  `loadRange` 原子提交＋`reqSeq`）——門檻因 chips 一列重算為 **656**（固定區塊 452）
- **F57** 圖表 x 軸改為時間軸（domain＝選取區間）：兩個月空缺的水平間距是相鄰日的 60 倍，
  等距索引的斜率誤導解決；點數 ≤30 時每點加小圓（短跨度塌成豎線時仍看得出有幾筆）、最新值旁標量測日期
- **F58** 資料不足時停用超出範圍的區間檔位（**本輪唯一有後端**）：新端點 `GET /api/body-metrics/range`
  回 `{weight_first, fat_first, last}`；chips 灰掉但仍可點（點了說明最早紀錄日）；切 metric 時當前檔位
  不可用會自動退檔。可用性規則＝「起始日在資料範圍內」＋「第一個完整涵蓋所有資料的檔位」
- **F59** 動作表現頁套用同一套檔位停用（`first_session_date` 掛在既有 history 回應、不新增端點）

## ✅ F60（7/26 實作、7/27 驗收通過）

**F60 是什麼**：用課表批次新增的每列預設**摺疊成一行摘要**（勾選＋動作名＋「20kg × 8 × 3 組」＋▸），
點標頭才展開既有的 KG／REPS steppers ＋組數控制。動機是實測資料：4 個動作的課表每列高 **259px**、
390×844 下清單可視 439px、內容 1065px → **一屏只看得到 1 列**，要捲三屏才確認得完，
違背 F47「先展開讓人逐列確認」的本意。設計由 Ryan 從四個選項中選定（摺疊摘要＋點開微調）。

**改了哪些檔案**：
- `feature_list.json` F60 條目（acceptance ①–⑦ 已簽核＝**凍結**，不得改寫）
- `app/static/js/calendar.js`：新增 `batchRowNode(row, onCheckChange)`（整列**就地重畫** paint，
  不呼叫整頁 rerender——否則清單捲動位置與其他列的展開態會被沖掉）；`openBatch` 每列加 `open: false`；
  `addModal` 的批次態改用它，並把「全部記錄」的 disabled 改成 `syncLogBtn()` 就地 setAttribute
  （順手修掉 handoff 待辦第 3 條那類「disabled 沒反映到 DOM」的問題，只限這顆按鈕）
- `app/static/css/app.css`：`.batch-head` / `.batch-summary` / `.batch-caret`，`.ex-name` 從
  `.batch-pick` 底下移出（動作名現在點了會展開，不再切勾選）並加 ellipsis
- v60 → **v61**（sw.js CACHE_NAME ＋ state.js APP_VERSION 兩處都已改）

**實作時列出、7/27 驗證後全數證偽的三個風險**（留著當範例：實作者的疑慮值得寫下來讓驗證去回答）：
- ③ 的「點勾選不展開」靠 `e.target.closest('.batch-pick')` 擋冒泡 → 實測勾選態 true→false、class 加 `off`、
  展開態不動，**不是「兩個都被擋掉」**
- `paint()` 每次 `replaceChildren` 重建整列（含正在被按的 stepper 按鈕）→ 連點與 caret 同步實測無異常
- ⑤ 收合列高度預估 ~42px → 實測標頭 24px、4 列清單共 190px，360×640 也全可見（ellipsis 有效，未換行）

## Codex 額度（狀態已變，7/27 更新）

7/26 那場 Codex 額度用盡，F49／F50／F51–F59 的 review 都是 **Claude fresh-context subagent**（同模型跨 context，
獨立性弱於 Codex）。**7/27 Codex 已恢復**（7d 53%），F60 的 review 與驗收都走回跨模型。

**若想補跨模型審**：範圍是 commit `c67c89d`..`c52edb9`（F49–F59 的前端 diff），那段只有同模型 review 過。

規則缺口（收官時值得寫進全域 memory）：`agents.md` 的額度 fallback 假設兩邊不會同時見底，但 7/26 是 Codex 先掛、
Claude 側唯一退路又只能使用者手動觸發，等於檢查側開天窗。需要一條「兩邊都不可用時怎麼辦」。

## 驗證

E2E 腳本在 scratchpad：`verify_f48_own.py`（11 條）／`verify_f49_own.py`（17 條）／`verify_f50_own.py`（14 條）／
`verify_f51_own.py`（7 條）／`verify_f60_own.py`（9 條），
跑法 `PYTHONUTF8=1 uv run python <script>`。7/27 實跑：f60 9/9、f49 17/17、pytest 195、ruff clean。

⚠ **腳本散在各 session 的 scratchpad**（路徑含 session id，換 session 要自己去舊目錄撈）。這正是待辦第 5 條
「收進 repo `tests/e2e/`」要解的問題——本場又踩一次：接手時得先從 7/26 的 scratchpad 複製 f60／f49 過來。

**測試慣例（三次踩過才定下來，寫 UI E2E 前先讀）**：
- 驗「狀態保留」類行為，捲動一律用真實滾輪且**刻意用非邊界值**——設成最大值會與失敗態結果重合，測試永遠綠（F48）
- Playwright 真實 `click()` 對捲出視野的元素會先 auto-scroll，在重繪前污染 scrollTop → 用
  `locator.evaluate("e => e.dispatchEvent(new MouseEvent('click',{bubbles:true}))")` 或只點可見元素
- 版號斷言不要釘死數字，只驗「sw.js 與 APP_VERSION 兩處一致」，否則每次 bump 都要改腳本
- F50 之後清單會填滿螢幕，要測「真的在捲」得備足資料量（844 高度下 4 份課表根本塞得下）
- 視窗開著時 `.picker-foot` 的按鈕被遮罩蓋住、點不到（先關窗）
- **auto-scroll artifact 會兩面刃**：F48 那次靠它抓到真 bug，F51 這次 reviewer 因它誤報「捲動位置失效」
  （真實 click 點第一列 → 容器捲回 0 → 看起來像還原失效）。判定捲動相關行為前先確認用的是 dispatchEvent
- 版號斷言各腳本一律「兩處一致」不釘死數字（同一個坑踩了三次才全改完）
- **「元素可見」不等於「元素沒被蓋住」**（F53 教訓）：只驗 bounding box 在 viewport 內會漏掉「別的元素疊在
  它上面」。驗版面要同時量「有無溢出容器」與「與下方元素的重疊量」，或用 `elementFromPoint` 確認最上層是它
- 判「畫面有沒有釘死高度」不要拿 computed height 跟 `viewport − padding` 比：某些高度下 `height:auto` 的
  內容高度剛好等於該值（F53 在 667 踩到）。看行為——頁面是否可捲、清單是否被拉伸
- 驗「切換有沒有整頁重繪」不要看焦點（點按鈕本來就會帶走焦點），在容器上打 `dataset` 標記看節點是否被替換
- **批次字串替換一律加 `assert count == 1`**（F54 教訓）：pattern 寫錯（`onclick: () =>` vs `onclick: (e) =>`）
  時 `str.replace` 會無聲跳過，程式看起來改了其實沒改，只有 E2E 抓到
- **功能改善會讓舊測試變成「空跑」而不是變紅**（F54 教訓）：F53 的捲動測試因清單變高、資料不再溢出而
  `before=0`，斷言裡有「前提條件成立」（`before > 0`）才抓得到——這類檢查值得常態放進斷言

## 下一步 / 待辦

0. **建議下一步（兩個都待 Ryan 決定）**：
   a. **抽共用 `range.js`**（F59 review P3-6，reviewer 明確建議「抽」）：`PRESETS`／`monthsAgo`／`iso`／
      `presetAvailable(firstDate)`／`longestAvailablePreset(firstDate)` 現在在 `body.js` 與 `exercise-detail.js`
      各一份，邏輯逐字相同、只差 first 的來源。理由不是「重複不好」，而是它帶著**無法由程式強制的隱性契約**
      （註解自己寫「改一邊要改另一邊」＝靠人記；規則有反直覺的例外分支；改錯的後果是**靜默顯示錯誤的資料範圍、
      不會有測試爆**；`PRESETS 必須遞增`的契約原本只寫在一邊）。本輪只做了最小處置（兩邊註解互相標明）。
   b. **動作表現頁的 x 軸仍是等距索引**（F57 只改了 /body）。那頁的點是「每次訓練」而非日曆日，且有 BUCKET_CAP 16
      的聚合——時間軸要另外決定聚合點畫在哪個日期上。Ryan 在 F59 的選項中刻意沒選這個。
1. **F53 留下的規格模糊待裁決**：體脂頁籤「只列有體脂的日子」是實作解讀（acceptance ② 沒明說）。後果是
   沒量體脂的日子在該頁籤看不到也改不到，要補記得切回體重頁籤。另一案是「全部日子都列、沒體脂顯示 —」。
1. **手機實機掃 F44–F58**（正式站實測 `weight_first=2026-07-20`、`fat_first=null`——你的資料只有 4 天，
   所以手機上會看到「只有 1M 可點、其餘灰掉」，體脂頁籤因無紀錄而不限制。這正是 F58 要處理的情境）：F47 批次列在小螢幕的捲動與誤觸；F49 視窗「點即進」會不會誤觸；F50 四處清單的
   高度手感（min-height 下限與 `.pick-modal` 的 80dvh 是我定的，不合手就改那幾行）。
2. MVP 收官（預定 8/1）：對 PLAN 成功指標、跑 `/harness-retro` 檢討 `.harness/failures.jsonl`（**現 6 筆**）。
3. **未修的 UX 落差（verifier 發現，未列 feature）**：`save()` 設 `body.saving = true` 後沒立即 rerender，
   送出期間按鈕的 `disabled` 沒反映到 DOM——防雙擊功能有效（實測 1 個 POST），但視覺上看不出已停用。
   同型問題可能存在於其他 `saving` 旗標的畫面（課表儲存、logSet），要處理先加 feature。
3. **F50 acceptance ⑥ 的規格 bug（待 Ryan 決定）**：⑥ 寫「⏳ 待同步提示出現時清單讓位」，但
   `syncStatusLine()` 只在 home／logger 呼叫，該提示在這三個畫面永遠不出現。已用 error-banner 驗到等效行為
   並判 PASS，但條文本身描述了不存在的現狀（同 F34 那類）。要更正就回簽核，不自己改寫。
4. ~~Android app 方案未定~~ **已拍板 Capacitor**（`docs/decisions/capacitor-vs-native-android.md`），
   F61 實作完成、F62–F64 仍 failing 且 acceptance **未簽核凍結**（動工前要先逐條走過，見 F61 的教訓）。
5. 把關鍵回歸 E2E 從 scratchpad 收進 repo `tests/e2e/`——**已開頭**：`tests/e2e/verify_f61.py` 進了 repo。
   f48–f60 那批仍散在舊 session 的 scratchpad（`.../1145a883-.../scratchpad/`、`.../23fb3bcb-.../scratchpad/`），
   要搬趁早，那些目錄不保證長存。

## 版面門檻算式的鐵則（F50–F56 累積，動 /body 或 .fills 畫面前先讀）

`@media (max-height: N)` 的 N **必須** = 固定區塊 ＋ 最壞情況的額外區塊 ＋ 清單 min-height ＋ `.app` padding 28。
**五次踩坑**：①F53 門檻 700 少算清單下限 → 701–732 死帶 ②F54 門檻 556 少算 flash／error-banner（成功記錄一定
有 flash）→ 557–592 死帶 ③註解數字散兩處只改一處（F54 P3-1）④F56 加 chips 一列忘了它會在 ≤362px 寬換成兩行
（30→64px）→ 窄螢幕 657–672 殘留死帶（已改 `min-width: 30px` 讓它一行）⑤F56 的自訂日期面板（~50px）不在算式裡
——這條**刻意不提高門檻**，改在註解寫明「面板展開時允許整頁捲動」的例外（提高門檻的代價是 657–706 裝置連面板
收著也拿不到填滿）。
算式的唯一來源在 `app.css` 那段註解；`.body-list` 的 min-height 上方只留指向它的提示。矮螢幕退讓一律用
`flex: none`（吃回內容高），**不要**把 min-height 設 0（卡片會塌成只剩標頭、子節點下限穿出卡片＝F53 P1-1 破圖）。
**E2E 不要把門檻寫死**：F54／F55／F56 的腳本已改成從服役中的 `/css/app.css` 讀 `@media (max-height: N)`
再推算測試高度——否則每次改門檻都會讓舊腳本無故變紅。

## 上游 feature 改動讓下游測試失效（F53–F58 共五次，動任何 /body 的東西前先讀）

改一個 feature 常會讓**前一個 feature 的 E2E** 失去意義。五次分別是：
1. F54 讓清單變高 → F53 的捲動測試因資料不再溢出而 `before=0`（**靜默**，測不到但仍綠）
2. F57 每點加小圓 → F53/F57 的 `querySelector('circle')` 抓到小圓而非末點圓（要 `circle[r="3"]`）
3. F58 停用超範圍檔位 → F57 的「換長區間」點 1Y 沒反應（**正確變紅**，因為斷言依賴那個前提）
4. F58 改門檻／改 metric 判定 → F53 的「切 toggle 不整頁重繪」條目**與新實作衝突**（見下）
5. F58 把切 metric 改走 rerender → 暴露 `captureBodyScroll()` 把捲動位置記到錯 metric 的既有 bug

**處置原則**：先分辨「測試過期」還是「產品回歸」。若舊 acceptance 的**手段**被新 feature 推翻但**目的**仍成立
（例如 F53 ⑥「不整頁重繪」的目的是不清掉使用者輸入，而 F54 已把表單移進視窗），就在 feature_list 附註說明、
把該條 E2E 改驗目的而非手段——**不改寫凍結的原文**。

## 測試腳本自身的維護債（F53–F57 累積）

改實作時，舊 E2E 會以三種方式失效，**只有第三種會自己變紅**：
1. **斷言的前提失效**（測不到東西但仍綠）——F54 讓清單變高後，F53 的捲動測試因資料不再溢出而 `before=0`。
   解法：斷言裡放「前提條件成立」的檢查（`before > 0`）。
2. **選擇器要跟著實作變**——F57 每點加小圓後，`querySelector('circle')` 抓到的是第一個小圓而不是末點圓
   （末點圓要指定 `circle[r="3"]`）。改視覺元素時回頭看一次選擇器有沒有被「插隊」。
3. **寫死的數值**（門檻、版號、資料量）——已全部改成從來源推導：門檻讀 `/css/app.css`、版號只驗「兩處一致」、
   資料量在腳本內自己塞足夠跨度。

## 卡點

無。

**已查證結案**：F21 的 `tpl.itemsScrollTop`（與 F48 首版同樣的 `onscroll` 手法）**實測有效**——dispatchEvent
連續 6 次重繪 × 3 種 viewport 位置全保留（200/400/600 不變）。reviewer 報的「完全失效」是真實 click 的
auto-scroll artifact。**但機制仍是脆的**（靠事件時序而非 DOM 唯一來源），若日後這頁出現跳頂再回來看這裡。

**刻意未修的既有債（前一輪 review 的 P3）**：視窗缺 `role="dialog"`／focus trap／Escape 關閉；`.chip` 高約 35px
低於 44px 觸控建議；視窗內 chips 不隨搜尋結果重建，可能出現「亮著的空篩選」。都是 F21/F43 沿用至今、F49 沒惡化。
