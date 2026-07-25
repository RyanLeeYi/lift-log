# session handoff

最後更新：2026-07-25（F48 / F49 / F50 三個 feature 收工）

## 現況

**50/50 feature passing**，線上 **v51**，已 deploy（mission-control restart lift-log；本機與公開 `/health` 皆 200、
公開 sw.js 已是 v51）。本輪完成：

- **F48** 課表三處清單超過兩項改捲動（列表頁／挑課表／今日菜單）
- **F49** 有課表時「臨時加動作」收成一顆入口鈕＋懸浮視窗（自由訓練維持攤開、點動作即進 logger）
- **F50** 四處可捲清單高度改為「填滿剩餘空間」（純 CSS flex，隨螢幕高度自適應）

## ⚠ Codex 額度用盡 → 本輪 review 改由 Claude 執行

`codex exec review` 回報額度用盡（**7/29 07:26 恢復**），`/code-review` 是 user-triggered、agent 叫不動。
Ryan 指示「就直接由 claude 審」，故 F49／F50 的 review 都是 **Claude fresh-context subagent**（同模型跨 context，
獨立性弱於 Codex，已知並接受）。**7/29 之後若想補一次跨模型審，範圍是 commit c67c89d 之後的前端 diff。**

規則缺口（收官時值得寫進全域 memory）：`agents.md` 的額度 fallback 假設兩邊不會同時見底，但這次 Codex 先掛、
Claude 側唯一退路又只能使用者手動觸發，等於檢查側開天窗。需要一條「兩邊都不可用時怎麼辦」。

## 驗證

E2E 腳本在 scratchpad：`verify_f48_own.py`（11 條）／`verify_f49_own.py`（17 條）／`verify_f50_own.py`（14 條），
跑法 `PYTHONUTF8=1 uv run python <script>`。本輪三支全綠、pytest 189、ruff clean、verify_f42 19/19。

**測試慣例（三次踩過才定下來，寫 UI E2E 前先讀）**：
- 驗「狀態保留」類行為，捲動一律用真實滾輪且**刻意用非邊界值**——設成最大值會與失敗態結果重合，測試永遠綠（F48）
- Playwright 真實 `click()` 對捲出視野的元素會先 auto-scroll，在重繪前污染 scrollTop → 用
  `locator.evaluate("e => e.dispatchEvent(new MouseEvent('click',{bubbles:true}))")` 或只點可見元素
- 版號斷言不要釘死數字，只驗「sw.js 與 APP_VERSION 兩處一致」，否則每次 bump 都要改腳本
- F50 之後清單會填滿螢幕，要測「真的在捲」得備足資料量（844 高度下 4 份課表根本塞得下）
- 視窗開著時 `.picker-foot` 的按鈕被遮罩蓋住、點不到（先關窗）

## 下一步 / 待辦

1. **手機實機掃 F44–F50**：F47 批次列在小螢幕的捲動與誤觸；F49 視窗「點即進」會不會誤觸；F50 四處清單的
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

**待確認的既有疑點（不在任何 feature 範圍內）**：F21 的課表編輯動作清單（`tpl.itemsScrollTop`）用的是與 F48
首版相同的 `onscroll` 記錄手法，可能同樣一直沒生效（節點被拆時瀏覽器補送 scrollTop=0 會污染記錄）。
要處理先加進 `feature_list.json` 標 failing 再動工（工作規則 3）。

**刻意未修的既有債（前一輪 review 的 P3）**：視窗缺 `role="dialog"`／focus trap／Escape 關閉；`.chip` 高約 35px
低於 44px 觸控建議；視窗內 chips 不隨搜尋結果重建，可能出現「亮著的空篩選」。都是 F21/F43 沿用至今、F49 沒惡化。
