# session handoff

最後更新：2026-07-25（本輪因 Claude 用量達 90% 門檻收工）

## 現況

47/47 feature passing，線上版本 **v48**（sw.js CACHE_NAME 與 state.js APP_VERSION 同步）。
本輪完成並已 deploy（mission-control restart lift-log）：

- **F44** 補記 modal 取消鍵改「退一步」：記錄態取消＝回選動作（丟棄 draft），選動作態取消＝關 modal。
- **F45** 日曆明細編輯既有組改懸浮 modal（`.cal-edit-modal`），取代行內編輯列。
- **F46** 補記 modal 加部位 chips（與搜尋 AND、就地更新不失焦）。
- **F47** 補記可「用課表」批次新增：課表→逐列確認（勾選／KG／REPS／組數）→「全部記錄」；
  預設值取該動作上次最重組，累度一律 6（輕鬆）。

## 驗證

E2E 腳本在 scratchpad（非 repo）：verify_f43–f47.py，跑法 `PYTHONUTF8=1 uv run python <script>`。
本輪 F43/F44/F45 迴歸全綠、F46 6/6、F47 7/7、pytest 189 passed、ruff 全過。
codex review 已修：F45 P2、F47 P1（重試重建 workout 撞 409）與 P2（課表快取過期）。

## 下一步 / 待辦

1. 手機實機掃一次 F44–F47 的手感（尤其 F47 批次列在小螢幕的捲動與誤觸）。
2. MVP 收官（預定 8/1）：對 PLAN 成功指標、跑 `/harness-retro` 檢討 `.harness/failures.jsonl`。
3. Android app 方案未定（`docs/decisions/android-app-evaluation.md` 傾向 Capacitor，等 Ryan 拍板）。

## 卡點

無。E2E 腳本只在 scratchpad，換機器要重寫——若要長期保留，考慮收進 repo 的 tests/e2e/。
