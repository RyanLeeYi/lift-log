# session handoff

最後更新：2026-08-25 00:30（互動場，第十二場）。**161/167 passing、5 failing ＋ 1 closed**
（F89、F104、F149、F153、F166 failing；F128 closed=superseded by F131；F167 本場收官）。
收工原因：usage-guard 5h 額度 94%。

## 接手第一件事：F89 只差一輪補測就能轉 passing

主場景已修好並在真機確認（兩輪修復都在 main）：
- `c0e3528`：超時中暫停→繼續不再把超時秒數當新倒數（Robolectric 釘住，突變驗證過）
- `19a7fd1`：pause/resume 事件帶正負號權威秒數（負＝超時），前端對表——真機誤差從 ~50 秒降到 1 秒

**缺口只是「未跑」不是「跑了壞」**（第三輪驗收者撞 usage-guard 壓縮範圍）：
1. 未超時的 pause/resume 回歸
2. app 內計時頁按暫停/繼續 → overlay 反向同步
3. REST 卡片與通知列兩條停止路徑（overlay 停止鈕已有證據）
4. 「靜默停止」疑點用完整原序列再重現一次（pause→resume→±15s→二次背景切換；
   第三輪單次壓縮版未重現；halted=true 唯一入口是 overlay 停止鈕，第二輪疑似驗收誤觸）

補測全過 → F89 轉 passing 並歸檔（整條原文進 docs/archive/features.jsonl）→ 接著派 F104
真機驗收（順帶補拍 F128 佐證：背景按「完成這組」→ 當場新倒數＋回 app 只有一輪）。

## 環境（真機驗收前必讀）

- **機上 dev app（com.ryanleeyi.liftlog.dev）現在是真 dev 站**（v161-F89fix，
  `scripts/build-apk.ps1 -Site dev` 建的，env.js 已驗證指向 lift-log-dev），Ryan 已登入。
  寫測試資料安全，但收尾照樣刪測試組＋結束訓練。
- **重大教訓（本場最貴的發現）**：機上舊的 dev APK 一直指向正式站——`npx cap sync`＋
  gradle 直建不會 patch env.js。**建 APK 一律走 `scripts/build-apk.ps1`**，且要用
  **pwsh（PowerShell 7）**跑（5.1 會把 UTF-8 無 BOM 腳本按 Big5 誤讀而語法錯誤）。
- **正式站測試殘留待 Ryan 清**：user DB `68ea7b49…` 在 8/24 有 4 個 workout、
  5 組「臥推 50kg×11」（21:26–22:14，deleted_at 空）——第一輪驗收寫進去的。
  請 Ryan 在 prod app 內刪（軟刪＋sync 才安全），不要直接改表。

## 其他 failing 的狀態

- **F166**：程式與 E2E 已完成（(b) 只看 rest-alarm，`1fc590e`），只差 ⑥ 真機重現一次
  （關「休息時間到」channel → 開關顯示「關」）。注意：改了 app/static/，收官出 APK 要包進去。
- **F153**：`.env` 的 `LIFTLOG_LLM_API_KEY` 是**空的**（等 Ryan 補 key）。對照腳本已備好：
  `scratchpad/f153_compare2.py`（in-process，外部 MCP 路徑已驗通、寫入 60kg×8 成功），
  key 一到跑一次即可完成對照證據。
- **F149**：⑨ 已完成大半——LICENSE/雙語 README/docker 已上 main（`b12ab57`），
  `docker compose build`＋`up`＋API 記錄一組實測通過（Ryan 拍板容器實測即可）。
  剩 ①–⑧：遷移、帳號綁定（要 Ryan 身分，不可外包）、release APK 全流程、測試矩陣。
  注意本機 127.0.0.1:8000 被 offer-radar 占用，compose 測試用 override 換埠。
- **F128**：closed（Ryan 拍板 superseded by F131），佐證併入 F104 驗收場。

## 本場收掉的

- **F167**（e2e 假 plugin 共用 helper）：passing 已歸檔。18＋1 支（含補的 verify_f144）
  全遷移，逐支與遷移前行為一致；獨立驗收兩輪（P2 修復後 R3 CLOSED）。
- F128 裁決、F166 ⑤ 裁決、F167 簽核、F149 ⑨ 判準——四項都是 Ryan 8/24 當場拍板。

## failures.jsonl 備註

F89 有多筆 open：22:03（原 P1，已由 c0e3528 修復）、22:50（環境：dev APK 指向 prod
＋登入被清，皆已解決）、23:33（分岔 ~50s，已由 19a7fd1 修復並真機反駁）。
補測全過後可在 retro 時標 resolved。F167 那筆已 CLOSED。
