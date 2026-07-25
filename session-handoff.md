# session handoff

最後更新：2026-07-25（F48 收工 → F49 實作完成待 review 決策）

## ⚠ 先看這裡：F49 卡在「缺跨模型 review」

**F49 實作與驗收都完成了，但 status 刻意維持 failing**：`codex exec review` 回報**額度用盡，7/29 07:26 才恢復**，
而規則的退路 `/code-review` 是 user-triggered 指令、agent 叫不動。等 Ryan 三選一後再改 status：
①自己跑一次 `/code-review`（medium 以上 effort）②等 7/29 Codex 回來補審這段 diff ③接受現狀直接翻 passing。

**F49 也還沒部署**（線上仍是 v49），要在手機上摸新的「＋ 臨時加動作」視窗需先 `mission-control restart lift-log`。

已有的證據：實作者 E2E `verify_f49_own.py` 14/14、pytest 189、ruff clean、acceptance-verifier 獨立 ①–⑨ 全 PASS。
自審抓到並修掉一條真 bug（離線時開窗前的動作庫刷新失敗會讓視窗開不起來＝有課表＋離線無法臨時加動作）。
另一條自審 finding 經 E2E 證實不可達（視窗開著時 `.picker-foot` 被遮罩蓋住、那顆鈕點不到），歸零那行留作防禦。

**順帶暴露的規則缺口**：全域 `agents.md` 的「額度 fallback」假設兩邊不會同時見底——Claude 撞 90% 換 Codex、
Codex 撞額度換 Claude，但這次是 Codex 先掛而 `/code-review` 又不能由 agent 觸發，等於檢查側直接開天窗。
收官時值得把這條寫進全域 memory。

## 現況

48/49 feature passing（F49 見上），線上版本 **v49**（sw.js CACHE_NAME 與 state.js APP_VERSION 同步），已 deploy
（mission-control restart lift-log；本機與公開 `/health` 皆 200、公開 sw.js 已是 v49）。

本輪完成：

- **F48** 課表三處清單「超過兩項改固定高度捲動」：①課表列表頁卡片清單（>2 份）②開練挑課表
  （>2 份，「自由訓練」留在捲動區外）③今日菜單 `.menu-list`（>2 動作，標頭與「臨時加動作」不被捲入）。
  容器高度（290px／118px）是真機手感參數，不在 acceptance 內，改起來不用重簽核。

## 驗證

E2E 腳本在 scratchpad（非 repo）：`verify_f48_own.py`，跑法 `PYTHONUTF8=1 uv run python <script>`。
本輪 11/11 PASS、pytest 189、ruff clean、回歸 verify_f42（19/19）與 verify_f43 全綠。
codex-review 兩輪（第一輪 1 P2 已修、第二輪無 findings）；acceptance-verifier 獨立重驗 ①–⑦ 全 PASS。

**⚠ 這個 feature 的教訓（下次寫 UI 狀態保留類 E2E 前先讀）**：

- 首版靠 `onscroll` 記錄捲動位置 → **節點被重繪拆掉時瀏覽器會補送一次 `scrollTop=0` 的 scroll 事件**，
  記錄被覆寫成 0，「還原」等於還原到頂端。根治＝不維護鏡射，改在 `render()` 開頭從 DOM 讀舊節點位置
  （`app.js` 的 `captureScrollPositions()`＋`templates.js` 的 `captureTemplateListScroll()`）。
- 首版實作者 E2E **假 PASS**：用 `e.scrollTop = e.scrollHeight`（最大值）→ 與「還原失效後被 Playwright
  auto-scroll 捲到底」同值。驗這類行為要用**真實滾輪＋非邊界值**。
- Playwright 真實 `click()` 對捲出視野的元素會先 auto-scroll，在重繪前污染 scrollTop：
  改用 `locator.evaluate("e => e.dispatchEvent(new MouseEvent('click',{bubbles:true}))")` 或只點可見元素。
- 已記入 `.harness/failures.jsonl`（status: open）供 `/harness-retro`。

## 下一步 / 待辦

0. **F49 的 review 決策（見開頭）＋決定後部署**。
1. 手機實機掃一次 F44–F49 的手感（F47 批次列在小螢幕的捲動與誤觸；F48 三處捲動區高度合不合手）。
2. MVP 收官（預定 8/1）：對 PLAN 成功指標、跑 `/harness-retro` 檢討 `.harness/failures.jsonl`（現 3 筆）。
3. Android app 方案未定（`docs/decisions/android-app-evaluation.md` 傾向 Capacitor，等 Ryan 拍板）。
4. acceptance-verifier 的建議（未列入 feature）：把關鍵回歸 E2E 從 scratchpad 收進 repo `tests/e2e/`——
   每輪驗收者都得重造等效場景，且 scratchpad 會被清掉（本輪 F48 腳本就被驗收者同名檔覆寫過一次）。

## 卡點

無。

**待確認的既有疑點（尚未查證，不在任何 feature 範圍內）**：F21 的課表編輯動作清單（`tpl.itemsScrollTop`）
用的是與 F48 首版相同的 `onscroll` 記錄手法，可能同樣一直沒生效。若要處理，先加進 `feature_list.json`
標 failing 再動工（工作規則 3）。
