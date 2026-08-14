# session handoff

最後更新：2026-08-14。現在 **142/155 passing、13 failing**；F148 已完成並通過獨立驗收。

## 接手第一件事

依 Harness preflight 進入下一個已簽核功能 **F149：既有資料遷移、營運與完整正式發布**。
先讀 `feature_list.json` F149 與 `docs/prd/local-first-cloud-sync.md` R8，再設定
`.harness/current_feature`；F149 是 strict risk，完成後需要獨立 review 與 acceptance。

## 本輪完成

- F148 匯出／登出／刪帳改為 `passing`；完整證據在 `docs/evidence/F148.md`。
- R1 漏掉 `push_subscriptions` 已修；同一 user access token 的 subscribe → export
  端對端測試通過。先前空陣列是測試混用 legacy bearer 與 user session DB。
- Strict review 修正兩個資料生命週期缺口：tombstone 現在守住 login／refresh／resolve；
  native 登出先 wipe 再撤銷 session，刪帳後 wipe 失敗會以 marker 在啟動／登入前重試。
- Gates：pytest 396、Node 22、ruff、Android unit、F148 E2E、F48 E2E 全綠；
  fresh-context 驗收 R1 與 lifecycle A/B 全部 ACCEPT。
- 本機 release：`release/lift-log-v154.apk`，解包確認 `APP_VERSION="v154"`；
  SHA-256 `181DAB537E375A46778D3B0031CAE22CC21EA8B55BFFE8D3D03F99C45AF3AE8B`。

## 尚未完成

1. `G:\我的雲端硬碟\lift-log-apk` 未掛載，v154 尚未複製到 Google Drive。
2. F149 後續還有 F153、F155 與既有 failing feature；以 `feature_list.json` 為準。
3. `docs/evidence/F146.md` 末段兩個規格裁決仍未處理：legacy token 是否收掉、Web
   IndexedDB 離線佇列與 envelope 字面差異；不阻擋 F148。
