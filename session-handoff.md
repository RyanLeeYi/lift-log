# Session Handoff
> 最後更新：2026-07-17（第三場：F4 收官）

## 這個 session 做了
- **F4 課表選單：passing**（evidence 見 feature_list.json）
  - 補跑上場欠的 `/code-review medium`：8 finder + 2 verifier agents，7 findings 成立、2 REFUTED
  - 已修：儲存/刪除雙擊防重入（tpl.busy）、加動作面板排除已加入動作（進度以 exercise_id 計數，同動作兩列會共用計數器）、搜尋回應 race 防護（searchSeq）、TemplateExerciseOut 補 muscle_group（state.exercise 契約一致，TDD 先紅後綠）、delete_template 去掉無用 nested join、CSS input 三份重複合併
  - 已知未修（有意識接受）：create/update 後的 _get() 重載（單人系統代價可忽略；verifier 確認 expire_on_commit 下屬務實選擇）、templates service 回 DTO 與其他 service 回 ORM 的分層差異（verifier 判 REFUTED：扁平欄位無法 model_validate 重建）、搜尋面板模式與 picker 重複（F5 會動 picker，屆時再抽）
  - acceptance-verifier 以 live curl + 全套測試逐條覆核 R4 五項全 PASS
  - 回歸：58 tests 全綠、覆蓋率 99%、ruff 乾淨、Playwright 快速回歸（過濾/儲存/開練菜單/logger）console 0 errors

## 做到一半 / 已知未修
- 無半成品
- F5 已知範圍：setCounts 未隨 sessionStorage 恢復（重整後菜單進度歸零＋set_number 撞號，F2 遺留、F5 acceptance 已明列）
- F6 前置預警在 PRD 技術約束（原子 log_workout、/mcp auth）
- F8 接點已備好：services/stats.py set_tonnage(bodyweight_kg)
- F2/F3/F4 真機最終確認仍待 Ryan（手機實開一次流程）

## 下一步（具體到可直接動手）
- **F5 PWA 離線佇列**：manifest 已有、無 service worker。TDD 起手：先寫「client_uuid 冪等補傳不重複」已有後端保證（F1 測試涵蓋），F5 主戰場在前端——(1) service worker + IndexedDB 佇列（離線 POST 失敗入列、UI 標示待同步、上線自動重放、靠 client_uuid 冪等）；(2) setCounts 隨 sessionStorage 續接恢復（或從 GET /api/workouts/{id} 重建）；(3) workout 已刪時該筆標失敗留佇列。驗證：DevTools offline 記 3 組→恢復連線自動補傳不重複、標示消失
