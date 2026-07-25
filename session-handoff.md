# session handoff

最後更新：2026-07-25（F48 / F49 / F50 / F51 四個 feature 收工）

## 現況

**51/51 feature passing**，線上 **v52**，已 deploy（mission-control restart lift-log；本機與公開 `/health` 皆 200、
公開 sw.js 已是 v52）。本輪完成：

- **F48** 課表三處清單超過兩項改捲動（列表頁／挑課表／今日菜單）
- **F49** 有課表時「臨時加動作」收成一顆入口鈕＋懸浮視窗（自由訓練維持攤開、點動作即進 logger）
- **F50** 四處可捲清單高度改為「填滿剩餘空間」（純 CSS flex，隨螢幕高度自適應）
- **F51** 編輯課表頁動作清單也改填滿剩餘空間（F50 漏掉的第五處，Ryan 真機發現）＋三顆鈕貼底
  （`.tpl-edit-foot { margin-top: auto }`——清單跨門檻塌陷時按鈕不再上跳 156px 造成誤存）

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
- 版號斷言三支腳本都已改成「兩處一致」不釘死數字（同一個坑踩了三次才全改完）

## 下一步 / 待辦

0. **F52 已簽核待動工**（Ryan 選定三項，皆為 F51 review 的範圍外 findings）：
   ①編輯頁「＋ 加動作」視窗搜尋篩選時整窗縮短、搜尋框位移 84px（`templates.js` 自己的 addModal 沒吃到
   F50 P1 給 `.pick-modal` 的修法）②`.tpl-items` 缺 `scrollbar-width: thin` 那組共用樣式（它現在是全 app
   最高的捲動區，桌機/Android 上捲軸比別處粗）③CSS「哪些畫面釘視窗高」的選擇器清單重複兩份（正常規則＋
   矮螢幕 media query），每加一個畫面要改兩處——改成 JS 統一掛 marker class。
1. **手機實機掃 F44–F51**：F47 批次列在小螢幕的捲動與誤觸；F49 視窗「點即進」會不會誤觸；F50 四處清單的
   高度手感（min-height 下限與 `.pick-modal` 的 80dvh 是我定的，不合手就改那幾行）。
2. MVP 收官（預定 8/1）：對 PLAN 成功指標、跑 `/harness-retro` 檢討 `.harness/failures.jsonl`（**現 5 筆**，
   本輪新增 3 筆：測試載體邊界值、改參數前先查來歷、acceptance 描述不存在的元素）。
3. **F50 acceptance ⑥ 的規格 bug（待 Ryan 決定）**：⑥ 寫「⏳ 待同步提示出現時清單讓位」，但
   `syncStatusLine()` 只在 home／logger 呼叫，該提示在這三個畫面永遠不出現。已用 error-banner 驗到等效行為
   並判 PASS，但條文本身描述了不存在的現狀（同 F34 那類）。要更正就回簽核，不自己改寫。
4. Android app 方案未定（`docs/decisions/android-app-evaluation.md` 傾向 Capacitor，等 Ryan 拍板）。
5. 把關鍵回歸 E2E 從 scratchpad 收進 repo `tests/e2e/`（acceptance-verifier 建議，未列入 feature）——本輪
   確實出事：驗收者的腳本同名覆寫掉 `verify_f48.py`，得重寫一份。

## 卡點

無。

**已查證結案**：F21 的 `tpl.itemsScrollTop`（與 F48 首版同樣的 `onscroll` 手法）**實測有效**——dispatchEvent
連續 6 次重繪 × 3 種 viewport 位置全保留（200/400/600 不變）。reviewer 報的「完全失效」是真實 click 的
auto-scroll artifact。**但機制仍是脆的**（靠事件時序而非 DOM 唯一來源），若日後這頁出現跳頂再回來看這裡。

**刻意未修的既有債（前一輪 review 的 P3）**：視窗缺 `role="dialog"`／focus trap／Escape 關閉；`.chip` 高約 35px
低於 44px 觸控建議；視窗內 chips 不隨搜尋結果重建，可能出現「亮著的空篩選」。都是 F21/F43 沿用至今、F49 沒惡化。
