# session handoff

最後更新：2026-07-26（F48–F59 十二個 feature 收工；**F60 實作已落地但未驗證**，Claude 額度撞 90% 線收工）

## 現況

**59/59 feature passing**，線上 **v60**，已 deploy（mission-control restart lift-log；本機與公開 `/health` 皆 200、
公開 sw.js 已是 v60）。本輪完成：

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

## 🚧 F60 進行中（下一個 session 從這裡接手）

**狀態：`failing`，程式碼已寫完、E2E 腳本已寫好但一次都沒跑過。** 別把它當完成品，也別重寫——
先跑驗證，紅了再修。中斷原因：Claude Session 額度 91%（usage-guard 收工線），不是卡點。

**F60 是什麼**：用課表批次新增的每列預設**摺疊成一行摘要**（勾選＋動作名＋「20kg × 8 × 3 組」＋▸），
點標頭才展開既有的 KG／REPS steppers ＋組數控制。動機是實測資料：4 個動作的課表每列高 **259px**、
390×844 下清單可視 439px、內容 1065px → **一屏只看得到 1 列**，要捲三屏才確認得完，
違背 F47「先展開讓人逐列確認」的本意。設計由 Ryan 從四個選項中選定（摺疊摘要＋點開微調）。

**已改的檔案**（未 review、未驗收）：
- `feature_list.json` F60 條目（acceptance ①–⑦ 已簽核＝**凍結**，不得改寫）
- `app/static/js/calendar.js`：新增 `batchRowNode(row, onCheckChange)`（整列**就地重畫** paint，
  不呼叫整頁 rerender——否則清單捲動位置與其他列的展開態會被沖掉）；`openBatch` 每列加 `open: false`；
  `addModal` 的批次態改用它，並把「全部記錄」的 disabled 改成 `syncLogBtn()` 就地 setAttribute
  （順手修掉 handoff 待辦第 3 條那類「disabled 沒反映到 DOM」的問題，只限這顆按鈕）
- `app/static/css/app.css`：`.batch-head` / `.batch-summary` / `.batch-caret`，`.ex-name` 從
  `.batch-pick` 底下移出（動作名現在點了會展開，不再切勾選）並加 ellipsis
- v60 → **v61**（sw.js CACHE_NAME ＋ state.js APP_VERSION 兩處都已改）

**已跑過的**：`ruff` clean、`node --check calendar.js` 通過。**沒跑的**：E2E、pytest 子集、review、驗收、deploy。

**接手步驟**：
1. `PYTHONUTF8=1 uv run python <scratchpad>/verify_f60_own.py`（腳本在 scratchpad，涵蓋 ①–⑦；
   捲動相關斷言刻意用 dispatchEvent 而非真 click，理由見腳本註解）
2. 回歸 `verify_f49_own.py`（同一個補記 modal）
3. Claude fresh-context review（Codex 額度到 **7/29 07:26** 才回來）→ acceptance-verifier → 改 passing → deploy → commit

**實作時已想過、留給驗證去證實的三個風險**：
- ③ 的「點勾選不展開」靠 `e.target.closest('.batch-pick')` 擋冒泡；label 與 input 各發一次 click，
  兩者都在 `.batch-pick` 內所以都被擋——要驗「勾選態真的變了」而不只是「沒展開」
- `paint()` 每次 `replaceChildren` 重建整列（含正在被按的 stepper 按鈕）。click 已派發完才重建，
  理論上無害，但連點與 caret 同步要實測
- ⑤ 的收合列高度預估 ~42px（padding 8×2 ＋ 單行 24 ＋ border 2），4 列含 gap ~198px
  遠低於 360×640 的 52dvh＝333px。若動作名在窄螢幕換行，這條會直接破——ellipsis 就是為此加的

## ⚠ Codex 額度用盡 → 本輪 review 改由 Claude 執行

`codex exec review` 回報額度用盡（**7/29 07:26 恢復**），`/code-review` 是 user-triggered、agent 叫不動。
Ryan 指示「就直接由 claude 審」，故 F49／F50 的 review 都是 **Claude fresh-context subagent**（同模型跨 context，
獨立性弱於 Codex，已知並接受）。**7/29 之後若想補一次跨模型審，範圍是 commit c67c89d 之後的前端 diff。**

規則缺口（收官時值得寫進全域 memory）：`agents.md` 的額度 fallback 假設兩邊不會同時見底，但這次 Codex 先掛、
Claude 側唯一退路又只能使用者手動觸發，等於檢查側開天窗。需要一條「兩邊都不可用時怎麼辦」。

## 驗證

E2E 腳本在 scratchpad：`verify_f48_own.py`（11 條）／`verify_f49_own.py`（17 條）／`verify_f50_own.py`（14 條）／
`verify_f51_own.py`（7 條），
跑法 `PYTHONUTF8=1 uv run python <script>`。本輪三支全綠、pytest 189、ruff clean、verify_f42 19/19。

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
4. Android app 方案未定（`docs/decisions/android-app-evaluation.md` 傾向 Capacitor，等 Ryan 拍板）。
5. 把關鍵回歸 E2E 從 scratchpad 收進 repo `tests/e2e/`（acceptance-verifier 建議，未列入 feature）——本輪
   確實出事：驗收者的腳本同名覆寫掉 `verify_f48.py`，得重寫一份。

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
