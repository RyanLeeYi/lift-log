# Session Handoff
> 最後更新：2026-07-20（**F11 體重補記過去日期 → passing**；F31 亦於本日真機確認 passing）。**feature_list 現 32/32 全 passing —— MVP 全數完成。** sw.js 現 **v34**、APP_VERSION v34。
>
> 🎯 **下一步（二選一）**：(a) **F33 日曆明細＋體重清單卡片化**（已進 feature_list 標 failing，見下方計畫，Ryan 已選方向 A）；(b) **MVP 收官**（vault PLAN 收官 checklist + `sop/after-action.md`：成功指標對答案、harness 消融檢討、README〔先讀 `identity/voice-and-tone.md`〕、成就故事、歸檔）。

## F33 日曆明細＋體重清單卡片化 → failing（待動工，2026-07-20 定方向 A）
> Ryan 覺得日曆／體重頁下方的堆疊顯示（`cal-detail-*`、`bm-row`）太「帳本感」。根因＝每列全寬 `border-bottom` hairline＋動作與其組沒有容器歸屬感。決定收斂到 **F26 課表已確立的「琥珀 accent 條＋卡片」語言**（一致性，非新風格）。**只動 markup 外層 wrapper＋CSS，互動邏輯零改動**（F16–F19 的每組編輯/刪除、多選批次、狀態行內編輯全部照舊）。
>
> **方向 A 實作重點**：
> - **日曆明細**（`calendar.js` `detailRows`／`app.css` `.cal-detail-*`）：同一動作的 `.cal-detail-ex` 標頭＋其下 `.cal-detail-row.set` 收進一個區塊容器，左緣 2px 琥珀脊（`--led-dim`）；**拿掉 `.cal-detail-row` 的 `border-bottom`**，組與組靠間距、動作與動作靠「新脊塊」分界。head／status 維持在最上（status 可再收成 chip 感但非必要）。
> - **體重清單**（`body.js` render 的 `.body-list`／`app.css`）：整個 `.body-list` 包進一張 `.body-card`（跟上方兩張圖表卡一致）、**拿掉 `.bm-row` 的 `border-bottom`**。
> - 數字維持 mono 主角（`--text`），脊/標頭暗色配角（`--text-dim`/`--led-dim`）；不新增字體/框架。
> - **鐵則**：改 static → `sw.js` CACHE_NAME 與 `state.js` APP_VERSION **v34→v35**。
> - **驗證**：新寫 `verify_f33.py`（可斷言 DOM 結構：動作區塊存在琥珀脊 wrapper、`.cal-detail-row` 無 border 帳本；或以視覺截圖為輔）；**重點是回歸**——logger（`verify_f19_logger`/`f20`/`f32`）、日曆刪除/編輯、體重（`verify_f11`/`f17`）全綠證明互動沒被 markup 改動打斷；`uv run pytest`＋`ruff` 綠；完成跑 `/codex-review`，改 passing 前跑 `/codex-verify`。
> - 純視覺，可先做一張 HTML mockup 給 Ryan 挑細節再落地（Ryan 未指定，動工時問一句）。
>
> ## F11 體重補記過去日期 → passing（2026-07-20，本場）
> - **需求（2026-07-18 真機回饋 #3）**：/body 表單原本只能記今天，要能補記過去日期的體重／體脂。
> - **實作（純前端，後端 `BodyMetricIn.date` 早支援）**：`body.js` 頂部表單加 `type=date` 選擇器（class `.bm-date-picker`、預設今天、`max=今天` picker 擋未來）；save 帶所選日期進 payload、`dateSel > todayIso()` 再驗一次擋手打未來；換日期時把該日既有紀錄帶進表單（同日覆蓋看得見）。`app.css` 加 `.bm-date-field/.bm-date-label/.bm-date-picker`（`color-scheme:dark` 讓原生日曆在深色可讀）。按鈕「✓ 記錄今天」→「✓ 記錄」。sw.js v33→v34、APP_VERSION v34。
> - **codex-review 兩輪、全修**：①**P1** 失敗重繪把日期重設今天→修正後重試會誤寫/覆蓋今天資料：改用 `body.form` 草稿跨重繪保留目標日期與輸入。②**P2a** onchange 只改 DOM、編輯清單列 rerender 丟日期：草稿在 date 變更/weight-fat `oninput` 都同步。③**P2b** 跨午夜 value/max 停在昨天：`body.form.date=null` 表「未明示選日」，提交時取當下 `todayIso()`（跨午夜正確落今天），只有明示選過日才鎖該日。
> - **驗證**：`verify_f11.py` **R1–R7 全 PASS**（預設今天+max、補記入清單+折線最早點=補記日、未來日擋下無新增、同日覆蓋不新增列值更新、選既有日回填、失敗重繪保留補記日、未選日只打體重落今天）；全套 **pytest 175 過**、ruff clean。
> - **⚠ 用量備註**：本場全程在 Session 5h 用量 90% guard 之上進行（Ryan 明示繼續）；**未跑 `/codex-verify` 跨模型驗收**——codex-review 已兩輪清乾淨＋E2E 逐條對應 acceptance，若要最終跨模型驗收簽章可下次補跑。

## F32 換動作後保留本次已做組數 → passing（2026-07-20，本場）
- **需求**：Ryan 反映「換動作在沒按收工/結束訓練時，原本訓練內組數都變成上次動作」。即同一次訓練換動作後回到該動作，先前做的組要留在 done-list，不能被誤標「上次」。
- **根因**：`pickExercise()` 每次 `state.doneSets=[]` 再打 `api.lastSets(id)`；`last-sets` 取「該動作最近一次 workout」＝今天這次，回傳本次的組卻被標成「上次」、done-list 空掉。
- **實作**：`state.js` 加 `doneByExercise:{exerciseId:[sets]}`（納入 save/restore/clearActiveWorkout，收工清空）。`app.js` `rememberDoneSets()` 在 logSet/deleteDoneSet/saveEditDoneSet 後鏡射；`pickExercise` 若鏡射有組→還原、weight/reps 取最後一組、hint 標「本次」並**跳過 lastSets**；無組維持原行為。sw.js v31→v32、APP_VERSION 同步 v32。
- **codex-review 1 P1＋1 P2 已修**：①**P1 離線佇列生命週期**——`syncQueue` 補傳成功換得 server id、`discardFailed` 捨棄失敗組，原本只改 `doneSets` 沒同步鏡射；新增 `reconcileDoneSets({replace,remove})` 掃**全部** doneByExercise 項目（離線組可能屬非當前動作）依 client_uuid 改寫並持久化，否則換動作復活無 id 舊 payload→刪除不刪 server、編輯撞冪等。②**P2 升級回填**——v31→v32 時舊 session 無鏡射，`pickExercise` 偵測 `setCounts[id]>0` 但鏡射空→`workoutDetail` 回填（既有鏡射優先，保留未上 server 的離線組）。
- **追加 refinement（Ryan 要求）**：換回已做過的動作時，「上次」提示**仍要顯示，但查前一次訓練**（不是把本次組誤標成上次）。作法：`last-sets` 端點加 `exclude_workout` 參數（service `last_sets(exclude_workout_id)` 過濾掉進行中 workout），`api.lastSets(id, workoutId)` 一律帶本次 workoutId；resume 分支 done-list 顯示本次組、hint 查 `exclude=本次` 顯示前一次值（查無前一次才退回「本次」摘要）。後端 TDD 2 條、sw.js v32→v33、APP_VERSION v33。refinement 再跑 codex-review、**2 P2 已修**：①resume 的 lastSets catch 只吞離線、401/5xx 重拋交 guard；②pickExercise 兩處 await 後加 `state.exercise!==exercise` 過期守衛（防 await 期間換動作/結束訓練後過期結果把畫面拉回 logger）。
- **驗證**：`verify_f32.py` **8/8**（A0 首選顯示上次 50、T1 換回保留 2 組 60kg、T2 上次顯示前一次 50 非本次 60、T3 續接第 3 組、T4 全新動作維持「第一次」、T5 升級回填 done-row 3＋上次 50、T6 離線記錄→補傳→換回→刪除真的刪到 server server_remaining=0）；全套 **pytest 175 過**、ruff clean、F31 logger 回歸 4/4。

## F31 休息結束 Web Push 通知 → passing（2026-07-20，本場）
- **需求**：Ryan 要休息倒數能離開網頁去別 app 操作、時間到通知。**真正浮動視窗手機網頁做不到**（原生專屬），改以 Web Push 達成「離開網頁也被通知」。Ryan 選 Android＋伺服器推播（可靠）。
- **後端**：`pywebpush` 依賴；`config.py` 加 VAPID 三欄（private=PKCS8 DER b64url、public=未壓縮點 b64url＝applicationServerKey、subject）；金鑰已產生寫進 **`.env`**（gitignore，不進 git）；`models.py` `PushSubscription`（endpoint 唯一，`create_all` 自動建表）；`services/push.py`（upsert 訂閱、`send_to_all` 用 pywebpush＋410/404 清失效、**in-process asyncio 排程器** schedule/cancel 單一 task）；`api/push.py`（GET /api/push/public-key、POST subscribe、POST rest-timer、POST rest-timer/cancel）；掛進 main。`tests/test_push.py` 11 條（webpush 全 mock）。
- **前端**：`sw.js` 加 push/notificationclick、SHELL 加 `/js/push.js`、CACHE_NAME v29→v30；`push.js`（enablePush 要權限+訂閱+送後端、pushEnabled 檢查旗標+權限、scheduleRestPush/cancelRestPush best-effort）；`api.js` 4 個方法；首頁「🔔 休息提醒」開關；`startRestTimer`→排程（restHintFor 秒數）、`stopRestTimer`→取消。APP_VERSION v30。
- **⚠ 限制**：①伺服器重啟會漏掉當下未觸發的通知（休息窗 60~180 秒，風險低）；②iPhone 需把 PWA 加到主畫面才有通知（本次以 Android 為主）；③排程器單人單 task（多裝置同時休息會互相覆蓋——單人 app 可接受）。
- **驗證**：`test_push.py` 11 條 + 全套 pytest 過、ruff clean。E2E `verify_f31.py` 4/4（記錄→排程、繼續→取消、開關顯示開、未開啟不排程；headless 用 init script 固定 Notification.permission=granted，因 headless grant 不生效）。logger 收工/F29 回歸 PASS。
- **codex-review 完成、1 P1（金鑰格式，真實送出全掛）＋2 P2（排程序列化、改秒數重排）全修，補格式回歸測試。**待 Ryan Android 真機確認送達**（headless 測不了）。

## F30 課表編輯草稿自動存與還原 → passing（2026-07-19，本場）
- **需求**：Ryan 選「自動存草稿＋還原」方向（比 F27 手機上不可靠的 beforeunload 更穩）。
- **實作**：`templates.js` `saveTemplateDraft/restoreTemplateDraft/clearTemplateDraft`（**localStorage** key `liftlog.templateDraft`，存 `{editing, savedSnapshot}`——比 workout 的 sessionStorage 多撐關閉分頁/OS 殺再開）。renderTemplateEdit 每次重繪存草稿；backToList 清草稿（存檔成功也走 backToList）。`app.js`：啟動 `restoreActiveWorkout` 後呼叫 `restoreTemplateDraft`（有草稿→靜默還原進編輯畫面，優先於 workout 的 home）；`visibilitychange(hidden)`＋`beforeunload` 補存即時輸入的名稱/休息。只在 `hasUnsavedTemplate` 才存、壞資料清掉不擋啟動。sw.js v27→v28、APP_VERSION v28。
- **與 F27 並存**：F27＝桌機 beforeunload 攔截＋app 內返回確認；F30＝手機還原（各平台皆有效）。
- **驗證**：`verify_f30.py` 4/4 PASS（改動→reload→還原；存檔/捨棄/乾淨→reload→不還原）；F27/F27b/F28/F26 回歸 PASS、pytest 161、ruff clean。codex-review 完成、2 P2 已修（撤銷回基準清草稿、嚴格驗證壞草稿）。sw v29。

## F29 選動作/今日菜單「結束訓練」鈕 → passing（2026-07-19，本場）
- **需求**：Ryan 要能直接從今日菜單結束訓練（原本得先挑動作進 logger 才有「收工」）。
- **實作**：`app.js` 把 `endWorkout` 從 renderLogger 閉包**抽到 module 級**（function 宣告 hoist；logger「收工」與 picker「結束訓練」共用同一動作＝清 client 狀態回首頁、已記錄組留 server）。renderPicker 底部改 `.picker-foot`（← 回首頁＋結束訓練 btn-danger 並排）。app.css 加 `.picker-foot`。sw.js v26→v27、APP_VERSION v27。
- **語意區分**：回首頁＝保留訓練可續（首頁顯示「繼續訓練」）；結束訓練＝清掉（首頁「開練」）。與 logger「收工」無確認一致（不破壞資料，已記錄組都在 server）。
- **驗證**：`verify_f29.py` 3/3 PASS＋logger 收工回歸 PASS、ruff clean。codex-review 完成：無問題。

## F28 刪除課表確認視窗 → passing（2026-07-19，本場）
- **需求**：Ryan 要刪除課表多一層確認（原兩段式紅鍵手機易誤觸連點刪掉）。
- **實作**：`templates.js` templateRow 刪除鍵改開 `deleteTemplateModal`（`tpl.confirmDeleteId` 記目標；顯示課表名稱＋無法復原提示；刪除/取消；防雙擊 `tpl.busy`；刪除後 `openTemplates` 重載並清旗標）。移除原 confirming 兩段式邏輯。沿用 `.confirm-modal`（F27）。sw.js v25→v26、APP_VERSION v26。
- **驗證**：`verify_f28.py` 3/3 PASS、F26 回歸 ALL PASS、ruff clean。codex-review 完成：**無問題**。

## F27 課表編輯未儲存離開警告 → passing（2026-07-19，本場）
- **需求**：Ryan 要在課表編輯有未儲存變更時、重整/離開視窗跳警告。
- **實作**：`templates.js` 匯出 `hasUnsavedTemplate()`（`state.screen==="templateEdit"` 且 `templateSnapshot(editing) !== tpl.savedSnapshot`；`startEditor` 設基準；快照只取 name＋items 的 exercise_id/default_sets/rest_hint_seconds）。`app.js` 加 `window beforeunload`：未儲存時 `preventDefault()+returnValue=""` 觸發原生確認。sw.js v23→v24、APP_VERSION v24。
- **驗證**：`verify_f27.py` 6/6 PASS（以派發 beforeunload 事件的 `defaultPrevented` 判定攔截與否）、F25/F26 回歸 ALL PASS、ruff clean。
- **追加：app 內返回確認（F27b）**：點「← 課表列表」若未儲存 → 自訂 `.confirm-modal`（捨棄並離開／繼續編輯），沿用 app 慣例不用瀏覽器 confirm；`tpl.confirmLeave` 狀態、startEditor 重置。**各平台皆有效**（不受 iOS beforeunload 限制）。E2E `verify_f27b.py` 4/4。
- **codex-review 2 P2 已修**：①休息 number input 加 `oninput` 即時寫草稿（Chrome 先 beforeunload 後 change，否則打字未失焦重整漏警告＋值遺失）；②`controllerchange` 設 `refreshing` 後加 `setTimeout(()=>refreshing=false,3000)`——beforeunload 取消重載後頁面存活時復原 latch，否則 F14 自動更新永久失效。
- **⚠ 已知限制**：window 級 beforeunload 在行動瀏覽器（尤其 **iOS Safari**）支援有限、可能不顯示；但 app 內返回確認不受此限。若要手機上「重整/關閉」也可靠，最穩是「草稿存 sessionStorage、返回時還原」（workout 的 restoreActiveWorkout 範式）——Ryan 待回是否要做。

## F26 課表列表顯示格式優化 → passing（2026-07-19，本場）
- **需求**：Ryan 覺得課表列表顯示太平（只有名字＋「·」串接動作名）。用 frontend-design skill 在既有深色/琥珀工業風內重做卡片（不引入新字體/框架）。
- **改動**：`templates.js` `templateRow` → 左側琥珀 accent 條、標題列右側份量摘要「N 動作·M 組」（M＝default_sets 總和，mono）、動作改 tag 帶琥珀「×組數」。`app.css` 加 `.tpl-head/.tpl-meta/.tpl-tags/.tpl-tag`。編輯/刪除與兩段確認不變。sw.js v21→v22、APP_VERSION v22。
- **驗證**：`verify_f26.py` 4/4 PASS、F25 回歸 ALL PASS、ruff clean。純顯示（markup+CSS 無邏輯），未跑 codex-review。
- **追加（同場，編輯頁）**：itemRow 同語言化——琥珀 accent、名稱獨立一行、控制列（組數靠左＋↑↓✕ 靠右，刪除拉開防誤觸）、自訂休息 number input 白底改深色（原本只有 `input[type=text]` 有深色樣式，`type=number` 漏掉）。sw.js v22→v23、APP_VERSION v23。
- **後續可選（Ryan 待回）**：①tag 多動作時收合「＋N」②份量摘要加預估時間。

## F25 自訂動作進課表「加動作」視窗 → passing（2026-07-19，本場）
- **需求**：Ryan 要自訂動作入口也放到課表編輯的「＋加動作」懸浮視窗（picker 現有的**保留**，兩處都有）。
- **重構**：把 picker 的自訂動作視窗抽成共用元件 **`app/static/js/custom-exercise.js`**（`customExerciseModal({groups,onCreated,onCancel,onFatal})`，自我包含：輸入讀 DOM、錯誤就地顯示、**不觸發父層重繪**——比原本 picker 版更簡潔，免了 syncFormFromDom）。picker（`app.js` `pickerCustomModal`）與課表編輯（`templates.js` `templateCustomModal`）共用它。
- **課表側**：`tpl.addingCustom` 狀態；`addModal` 內清單下方加 `.add-custom-ex`「＋自訂動作」→ 開自訂視窗**疊在加動作視窗上層**（兩層 modal-overlay，後者在上）。建立成功 → `loadPickable("")` 重載、`tpl.selectedAdd=created` 預選、清 muscleFilter/searchQ → 回加動作視窗可直接「確定加入」。
- **版本**：sw.js SHELL **加 `/js/custom-exercise.js`**（新模組務必進 SHELL 否則離線漏快取）、CACHE_NAME **v19→v20**、APP_VERSION 同步 **v20**。
- **驗證**：`verify_f25.py` R1–R5 全 PASS；`verify_f10.py`（picker 重構回歸）ALL PASS；`verify_f24.py`（v20）PASS；全套 **161 passed**、ruff clean。
- **共用元件維護**：改自訂動作表單邏輯只需改 `custom-exercise.js` 一處，picker 與課表兩邊同時生效。

## F24 畫面顯示版本號 → passing（2026-07-19，本場）
- **緣由**：Ryan 手機看不到 F10 新按鈕，排查後確認是**手機 service worker 舊快取**（正式站 public app.js/sw.js 已是新版，用無快取瀏覽器實測公開網址按鈕存在）。為了以後一眼判斷手機更到哪版，加版本號顯示。
- **實作**：`state.js` 匯出 `APP_VERSION` 常數（隨 shell 被 SW 快取 → 過期快取會顯示舊版號，正是偵測未更新的機制）；`app.js` `versionTag()` 顯示於 **setup 與 home** 頁角落（`.version-tag` 小字低調）；`app.css` 加樣式。**sw.js CACHE_NAME v18→v19，APP_VERSION 同步 v19**。
- **⚠ 維護鐵則**：改任何 static 資產 → sw.js `CACHE_NAME` 與 state.js `APP_VERSION` **兩處一起遞增**（兩邊都有註解釘住）。
- **驗證**：E2E `verify_f24.py` setup+home 皆顯示 v19（ALL PASS）；全套 **161 passed**、ruff clean；F10 E2E 回歸 ALL PASS。純顯示性小 feature，未另跑 codex-review/acceptance-verifier。
- **給 Ryan 的排查用途**：手機打開看角落版本號——若不是最新（現 v19）就是快取沒更新，照下面「強制更新」清一次即可。F14 之前裝的版本無自動重載，需手動清一次 bootstrap。

## F10 自訂動作 → passing（2026-07-19，本場）
- **後端缺口比 handoff 記載多**（原記「主戰場前端」，實際 schema 對不上 acceptance）：`ExerciseCreate` 原本 name_en/muscle_group 必填，改為選填（`app/schemas.py`：`str | None`；name_zh 加 field_validator 去空白+擋空）。`create_exercise`（`app/services/exercises.py`）：**英文名留空→鏡射中文名**（避開 name_en unique 非空欄位的 nullable 重建、EN 檢視不空白）、**部位留空→預設「其他」**（`DEFAULT_MUSCLE_GROUP`）、**正規化重複前置檢查**（對 zh/en 各跑 `find_by_name` 命中即 DomainError 400，擋大小寫/空白變體+防 log_workout 名稱解析歧義），DB unique 當後盾。POST /api/exercises 端點未改、仍經 services。
- **設計決策（Ryan 選）**：部位＝現有 chips＋可自訂「其他」；留空歸「其他」。
- **前端**（`app/static/js/app.js`）：picker 加 `.add-custom-ex` 鈕 → `openCustomForm` → `renderCustomExerciseModal`（共用 `.modal-overlay`）。中文名/英文名 input、部位既有 chips（就地切換不重繪）＋「其他」自訂文字（優先於 chip）、自體重 checkbox、建立/取消。`api.js` 加 `createExercise`。`app.css` 加 `.custom-ex-modal`/`.field-label`/`.checkbox-row`/`.add-custom-ex`。sw.js **v18**。
- **codex-review 3 P2 全修**：①POST 成功後才關窗，二次 GET 失敗用建立回傳值 fallback 補進清單（不再「已建立卻視窗消失+重試撞重複」）；②401 重拋交全域 guard（原本吞掉所有 ApiError，token 失效會卡 modal）；③`.custom-ex-modal` overflow-y auto（chips 多行/鍵盤縮高時建立鈕不落到可視外）。
- **驗證**：tests/test_exercises.py 9 條 + 全套 **161 passed**、ruff clean。E2E scratchpad `verify_f10.py` R1–R6 全 PASS（P2 修後重跑仍 ALL PASS）。acceptance-verifier **R1–R10 全 pass**（獨立重跑 pytest+E2E）。
- **驗收者非阻擋建議**：未來可補一條自體重噸位整合測試（記體重→建自訂自體重動作→記負重組→驗噸位=最新體重+負重）釘更死；本次靠「stats.py 零改動+既有回歸走同一 API 路徑仍綠」佐證。
- **E2E 教訓**：app_factory 起的 server **有 seed**（`app/seed.py` 36 個預設動作，含「保加利亞分腿蹲」「面拉」等）——E2E 自訂名要避開 seed 才不會誤判重複；conftest 的 `client` fixture 用 `create_app` 無 seed，後端單元測試不受影響。playwright 用 `uv run --with playwright python <script>`（uv env 沒裝 playwright，臨時環境+沿用 ms-playwright 快取瀏覽器）。
- **下一個：F11 體重補記過去日期**（/body 表單目前只記今天；API date 欄位已支援，純 UI 讓表單能新增過去日期）。改 static 記得 bump sw.js（現 v18）。

## F15 收尾紀錄（已完成）
- **組間休息按鈕兩態切換**（Ryan 真機回饋：倒數沒有停止鈕）。就緒態「✓ 完成這組」記錄該組＋開始倒數＋進休息態；休息態「繼續下一組」停倒數＋LED 回靜態參考秒數＋凍結本次休息秒數＋回就緒態。rest_seconds 定案點＝按「繼續下一組」當下 elapsed（Ryan 選的），寫進下一組、用掉即清；第一組不帶。換動作/收工清掉未用凍結值
- commits：`b581b3a`（實作）+ `11bfbdf`（codex-review P2 修正：凍結值改成「確認保住後才清」，非離線失敗/入列失敗重試不丟）+ `a6070d0`（passing）
- 驗收：acceptance-verifier R1–R7 PASS（自寫 Playwright 擷 POST /sets body、LED 回參考值比對）；R8 換動作分支（驗收者）＋收工分支（補測 `verify_f15_endworkout.py`）雙 PASS；R9 F12 迴歸 out-of-scope（未動 F12 碼）。E2E `verify_f15.py`（scratchpad）。139 tests、ruff clean
- **Ryan 手機更新**：若他先前已手動刷一次拿到 F14（v5，有自動重載 listener），這次 F15（v6）會**自動到位**、不用再手動；若還沒拿到 F14，手動刷一次會直接到 v6，之後每次部署都自動

## 課表編輯（F21、F22 ✅ 完成上線，sw v16）
- **F21 清單高度調整（2026-07-19）**：Ryan 看實際後幾次調整，定案「約 2 個動作高」（`.tpl-items.scrollable` max-height 310px、threshold `>2`）。屬已驗收 F21 的參數微調，E2E 重驗（2 個不捲、3 個捲），未另跑跨模型驗收。sw v16

- **F22 課表加動作視窗：部位篩選**：Ryan 回饋要跟 logger picker 一樣有部位。addModal 加 `.chips` 部位按鈕（groups 取自 tpl.exercises），`tpl.muscleFilter` 篩選、與搜尋並用、開窗重置。codex-review P2 已修（chip 改就地更新不整頁重繪，避免與進行中搜尋 callback 競態——同 F21 選取/搜尋的 in-place 原則）。acceptance-verifier 8/8 pass。E2E `verify_f22.py`

- **F21 課表編輯：動作清單捲動＋加動作懸浮視窗**：Ryan 回饋。編輯課表的 `.tpl-items` 固定約 1 動作高＋捲動（`>1` 時加 scrollable）；「＋加動作」改成 `.modal-overlay` 懸浮視窗（搜尋＋可捲動清單＋確定加入/取消），**單選、按確定加入才進課表**。codex-review 3 P2 已修（modal 選取就地更新不重繪防跳頂、搜尋排除選取即清＋停用確認、tpl-items 保存/還原 scrollTop——因 cap 只 1 動作高，不還原會每次編輯跳頂）＋開窗重置搜尋。acceptance-verifier 10/10 pass。E2E `verify_f21.py`。**新增共用樣式 `.modal-overlay`/`.modal` 可給未來其他 modal 用**

## 選動作畫面（F23 ✅ 完成上線，sw v17）
- **F23 臨時加動作清單固定高度捲動**：Ryan 回饋。picker 的一般動作庫清單加 `.pick-list` class、**固定 height 248px（約 4 個動作高）＋捲動**（用固定 height 非 max-height，篩選少項時不收縮、回首頁鈕不上移——Codex P2）；今日菜單 `.menu-list` 不受影響（CSS 選擇器保證）。E2E `verify_f23.py`（含篩選後高度不縮）＋codex-review；純 CSS cap 未另跑跨模型驗收

## 開練頁版面（F20 ✅ 完成上線，sw v12）
- **F20 done-list 新→舊排序＋固定高度可捲動**：Ryan 回饋記多組時版面被推走。done-list 改最新在最上（`[...doneSets].reverse()`）；組數 > 2 時加 `.scrollable`（max-height 88px overflow-y auto），下方 steppers/主按鈕位置穩住；編輯某列時解除限高（`!editDraft` 條件）。codex-review P2 已修（finish/endWorkout 清 editDraft）。acceptance-verifier 7/7 pass。E2E `verify_f20.py`。**注意：F16/F19 的舊 logger/calendar E2E 已因 F19 單擊刪除＋F20 反轉順序過時並刪除，現行 logger E2E 是 `verify_f19_logger.py` + `verify_f20.py`**

## 紀錄「編輯＋刪除」✅ 全部完成上線（F16 訓練組、F17 體重、F18 每日狀態、F19 刪除 UX）
- **F18 每日狀態 編輯＋刪除 → passing 並部署（sw v11）**：後端 `DELETE /api/daily-status/{date}` 硬刪/404；日曆狀態列可編輯（精力/睡眠 1–5 量表 + 備註 inline 控制項、POST 覆蓋）＋單擊即刪。codex-review P2 已修（`refreshMonthAndDay` 守衛切月競態 selectDay(null) → 400；此修正惠及 F16/F18/F19 所有日曆變更）。acceptance-verifier 全 pass。E2E scratchpad `verify_f18.py`
- **剩餘 feature：F10 自訂動作、F11 體重補記過去日期**（Ryan 早前真機回饋，與本刪除/編輯串無關）。注意：F11 的 /body 表單目前只記今天；F17 已為過去日期做了編輯清單，F11 是讓表單能「新增」過去日期

- **F17 體重 編輯＋刪除 → passing 並部署（sw v10）**：後端 `DELETE /api/body-metrics/{date}` 硬刪/404（`delete_body_metric` service）；/body 折線圖下體重紀錄清單，每列數字輸入編輯（POST 覆蓋、日期不可改）＋單擊即刪。codex-review P2 已修（編輯草稿存 `body.editDraft` 不丟輸入）。acceptance-verifier R1–R7 pass。E2E scratchpad `verify_f17.py`

- **F19 訓練組刪除 UX 改版 → passing 並部署（sw v9）**：Ryan 回饋兩段式確認多餘＋要多選。改為 logger 與日曆**單擊即刪**（拿掉兩段式）；**多選批次刪除只在日曆**（「選取」→勾選→「刪除選取 (N)」，`cal.selectMode`/`selectedIds`）。刪除 404 當成功（防連點）、批次 finally 重載（部分失敗一致性）。acceptance-verifier 12/12 pass。codex-review 2 P2 已修。**F17/F18 的刪除跟這個範式走（單擊即刪、不做多選、無確認）**，不要再做兩段式確認

- **F16 訓練組 編輯＋刪除 → passing 並部署（sw v8）**：後端 `PATCH /api/sets/{id}`（原位、set_number 不變、404/範圍驗證，`SetUpdate` schema + `update_set` service）；logger done-list 與日曆明細每組可**用 stepper +/- 編輯**（`stepper`/`rpePicker` 已抽到 `dom.js` 共用）＋兩段式刪除；離線 queued 組刪除移出佇列、`flushQueue` 同步後回填 server id 到 doneSets。acceptance-verifier R1–R14 全 pass。codex-review 3 條已修（P1 回填 id、P2 刪除更新 setCounts、R9 改用 steppers）。CLAUDE.md sets 規則已改。E2E：scratchpad `verify_f16_logger/calendar/p1.py`
- **F17 體重 編輯＋刪除**（下一個做）：後端 `DELETE /api/body-metrics/{date}` 硬刪、不存在 404；/body 頁折線圖下新增可編輯/刪除清單；編輯＝POST 覆蓋、日期不可改；兩段式刪除。body_metrics model 在 `app/models.py`、service `app/services/`（body/metrics 相關）、既有測試 `tests/test_body_metrics.py`
- **F18 每日狀態 編輯＋刪除**：後端 `DELETE /api/daily-status/{date}` 硬刪、404；日曆明細 statusRow 可編輯/刪除；編輯＝POST 覆蓋。既有測試 `tests/test_daily_status.py`、`calendar.js` `statusRow()`
- 通用：刪除確認一律兩段式（範式已在 `templates.js` 與本場 F16）；改 static 記得 bump `sw.js` CACHE_NAME（現 **v8**）

## （F16 開工前的原始設計筆記，供 F17/F18 參照）
Ryan 回饋：要能清掉/編輯特定筆紀錄，涵蓋 **訓練組 + 體重 + 每日狀態**，入口在 **logger 當場 + 日曆過去 +（體重）/body 頁**。

**已談定的設計決定（下場照這個寫驗收，不用重談）：**
- **訓練組 sets**：
  - 刪除＝**軟刪（後端已全做好）**：`deleted_at` 欄位、`DELETE /api/sets/{id}`→`svc.soft_delete_set`（`app/services/workouts.py:275`）、所有查詢（exercises/stats/workouts services）已濾 `deleted_at.is_(None)`。缺前端入口。
  - 編輯＝**原位修改，新增 `PATCH /api/sets/{id}`**（改 weight_kg/reps/rpe/rest_seconds），**set_number/位置不變**。**Ryan 拍板放寬 CLAUDE.md「sets 不做 update」原則**（單人 app、audit 需求低）——記得同步更新 CLAUDE.md 那條約束的措辭。
- **體重 body_metrics / 每日狀態 daily_status**（都是 date UNIQUE、一天一筆、POST 本來就覆蓋 upsert）：
  - 刪除＝**硬刪（Ryan 拍板）**：新增 `DELETE /api/body-metrics/{date}`、`DELETE /api/daily-status/{date}`（軟刪會撞 UNIQUE(date) 無法重記同日，故硬刪最乾淨）。
  - 編輯＝**沿用現有 POST upsert**（同日覆蓋，已支援過去日期），前端只要「把某天的值載進表單改一改再存」，後端不用動。
- **確認 UX**：一律沿用課表刪除的**兩段式**（第一下變確認、第二下才真刪；範式在 `app/static/js/templates.js` 的 `confirmDeleteId`），不用瀏覽器彈窗。
- **離線 sets**：done-list 裡尚未同步（queued、無 server id）的組，刪除/編輯＝改 IndexedDB 佇列那筆（`queue.js`），不打 API。

**入口位置：**
- logger「已完成的組」每列：編輯（把值帶回 steppers 改）＋刪除（兩段式）。注意線上組有 server `id`、離線 queued 組只有 client_uuid。
- 日曆某天明細（`calendar.js` `detailRows`/`statusRow`）：把分組文字「深蹲 80×8 80×8」改成**每組一列**可編輯/刪除；狀態列可編輯/刪除；**新增當日體重顯示**可編輯/刪除（目前明細只顯示噸位、沒顯示體重）。
- /body 頁（`body.js`，目前只有折線圖）：體重紀錄列成**可編輯/刪除的清單**。

**拆法（一次一個、TDD）**：F16 訓練組 編輯＋刪除（前端為主＋新 PATCH endpoint）→ F17 體重 編輯＋刪除（後端 DELETE + /body 清單 UI）→ F18 每日狀態 編輯＋刪除（後端 DELETE + 日曆 UI）。
**下場第一步**：把 F16–F18 完整驗收草擬好給 Ryan 簽核 → 凍結進 feature_list → 從 F16 TDD 開工（PATCH /sets 要後端測試；前端兩態切換/刪除用 Playwright E2E）。

## 下場開場動作
- **從 F10 自訂動作開始**（acceptance 已簽核：中文名必填、英文/部位選填、自體重勾選；POST /api/exercises 已存在，主戰場前端 picker/加動作面板）→ 再 F11 體重補記過去日期（API date 欄位已支援，純 UI）。一次一個 feature、TDD、改 static 記得 bump `sw.js` CACHE_NAME（現 v5）
- **提醒 Ryan（F14 部署後一次性動作）**：桌機/手機各**手動刷一次**（手機關掉 app 重開或下拉重整）才會拿到 F14 這版；**從此之後每次部署都自動到位、不用再手動**。這是引入自動更新功能的一次性 bootstrap 成本（舊版 app.js 沒有 listener），非 bug
- **F14 待 Ryan 確認的小事**：實作用一次性 `skippedInitialClaim` 取代 acceptance 原文的「hadController 條件」（可觀察行為相同＋修掉 P2① 首訪者不更新的邊界；驗收者判定符合）。若認可，acceptance 括號可更新措辭——不改也不影響
- **PRD 缺口（驗收者回饋，非阻擋）**：`docs/prd/mvp-lift-log.md` 標頭已補註「F9 起以 feature_list.json 為準」

## F14 收尾紀錄（已完成）
- **程式碼完成＋自我驗證充分**（commits 8820688 原始 + **8426a15** review 修正）：
  - sw.js install：`fetch(url?v=CACHE_NAME, {cache:"reload"})` + `cache.put(url)`（版本戳杜絕新 SW 裝舊資產混版）、CACHE_NAME **v5**、activate 清舊快取 + claim（與 8820688 一致）
  - app.js：controllerchange 自動 reload。**Codex P2① 修正**：原本 `hadController` 永久 false 會讓「首訪者頁面開著、之後部署」永遠不更新；改為一次性 `skippedInitialClaim`——只跳過首裝的**初次**接管，之後任何一次接管（部署新版）都 reload 一次（`refreshing` 旗標防循環）
  - 138 tests 全過、ruff 乾淨
- **驗證證據**（下場給驗收者/寫進 feature_list evidence）：
  - `/codex-review`（審 8820688）回 3 條：**P2① 已修**（見上）；**P1 已知一次性 bootstrap 限制**（見下，接受並揭露）；**P2② 已知**（記錄中途被 reload 丟失正填的那組輸入＋計時；訓練情境已持久化課表/動作，只丟正在填的一組，接受）
  - Playwright E2E 兩情境皆 PASS（scratchpad `verify_f14.py`＝暖升級 acceptance 情境；`verify_f14_p21.py`＝P2① 首訪者不導航自動更新）。E2E 教訓：(a) marker 要埋 `<head>`，埋 body 內會被 app.js render 洗掉；(b) 導航進行中 evaluate/content 會噴 "context destroyed"，要 try/except 重試；(c) http.server 用 `allow_reuse_address` 避免前輪殘留 socket 撞 port；跑前 `taskkill //F //IM headless_shell.exe` 清孤兒
- **⚠ 偏離凍結 acceptance 需 Ryan 確認**：acceptance 原文寫「首次安裝不 reload——以啟動時已有 controller 為條件」。實作改用一次性 skippedInitialClaim（可觀察行為相同＝首裝不 reload，且修掉 P2① 邊界）。若 Ryan 認可，把 acceptance 該括號更新為「首裝的初次接管不 reload、之後接管都 reload」
- **⚠ P1 一次性 bootstrap 限制（已揭露，非缺陷）**：F14 是第一個有自動重載的版本。Ryan 手機現在跑 F14 之前的 app.js（沒有這個 listener），**F14 部署當次它不會自動到位、仍需手動刷一次**才拿到 F14；從 F14 之後的每次部署才會自動更新。SW 端 `client.navigate()` 試過想根治 bootstrap，但對舊 SW 載入的既有 client 不觸發（實測 0 次自動導航），且偏離 acceptance，已放棄
- **未做（依序，下場額度重置後）**：1) acceptance-verifier agent 逐條驗收（uv 專案不走 codex-verify，見 memory）；2) F14 → passing（evidence 引本場 E2E＋codex-review）；3) mission-control 重啟 lift-log 部署；4) 告知 Ryan：這次部署後手機**要手動刷一次**（bootstrap），之後才自動；桌機同理一次
- **F13 已收**（4/4 PASS，commit 4d81661）：sw.js no-cache 生效，公開 URL REVALIDATED
- **用量**：本場切 Opus 4.8 續作（Fable 週限額兩帳號都 ~91%）。收工原因：現用帳號 ian4567x 的 **5h 窗到 93%**（Opus 真正燒的窗，破 90%），15:00 重置。下場開工前 `cswap list` 看額度

## 第十場最終快照
- **F12 完成上線**：規格（a50e019）→ 後端（0c01278）→ 前端（62bb947）→ codex-review 4 P2 全修（bed347d）→ acceptance-verifier 8/8 PASS → passing。mission-control 已重啟 lift-log，**正式 DB 遷移自動完成**（templates API 已帶 rest_hint_seconds），本機 sw.js v4
- **注意：Cloudflare 邊緣快取 sw.js 4 小時**（cf-cache-status HIT）——公開 URL 的新版最多延遲 ~4h 到手機；急件去 CF dashboard purge。通案已入列 **F13（sw.js no-cache 標頭）**
- **Codex 驗收限制（記憶已存）**：workspace-write sandbox 跑不了 uv（寫不了 cache、讀不了 managed Python）——uv 專案驗收直接派 acceptance-verifier fallback，別燒 Codex 額度
- **測試孤兒教訓**：`uv run uvicorn` 的 Popen 用 `terminate()` 只殺 uv 層，孤兒 uvicorn 佔 port 頂替下一輪（症狀：fresh DB 卻回 template name already exists）。一律 `taskkill /F /T /PID` 整樹殺＋隨機 port
- **F13 也完成了（同場加映）**：sw_no_edge_cache middleware（commit 0c2eb11）→ 驗收 4/4 PASS → passing。公開 URL 實測 CF 對 no-cache 的行為是「存但每次回源驗證」（REVALIDATED），部署即時生效；zone 會改寫瀏覽器側標頭為 max-age=14400 但不影響 SW 更新（瀏覽器對 SW 主腳本預設繞過 HTTP cache）。改版前的舊 /sw.js 快取條目一次性 HIT 至 TTL 過期或 Ryan purge
- **下場開場動作**：照順序做 **F10 自訂動作**（acceptance 已簽核；POST /api/exercises 已存在，主戰場前端 picker/加動作面板）→ F11 體重補記（body-metrics date 欄位已支援）。改 static 資產記得 bump sw.js CACHE_NAME（現為 v4）
- Ryan 手機實測 F12 倒數（等 CF 快取過期或 purge 後）：課表設參考秒數→倒數→超時變紅震動→點 chip 臨時調
- vault DEVLOG 本場已記（MVP 收官＋F12 全流程）

## 第十場（2026-07-18）
- 開場撞 Session 98% 用量門檻一次（帳號輪替後續作；usage-guard 已另案改版成以 cswap per-account 判定，見 `~/.claude/scripts/usage-guard.sh`）
- **F7 → passing**：Ryan 於 Cloudflare dashboard 加 public hostname `lift-log.my-super-dev-server.work` → 公開 HTTPS `/health` 200、首頁 200；Ryan 手機 4G 真機記錄（當日 workout 1–3 含實值 sets）；mission-control 收編（第八場實測＋services.toml＋存活旁證）。acceptance-verifier 逐條 3/3 PASS
- **MVP 全 passing**。收官事項（vault PLAN.md checklist）：連續自用 2 週對成功指標、README（先讀 vault `identity/voice-and-tone.md` 若存在）、after-action → 尚未動
- **Ryan 真機試用回饋 → 新 feature 入列（failing，acceptance 已含 Ryan 的設計選擇）**：F10 自訂動作（完整欄位、多數選填）、F11 體重補記過去日期（API 已支援 date，純 UI）、F12 組間休息目標倒數提醒（實際量測邏輯不變）。回饋 #2（課表編輯 ↑↓ 箭頭）確認是正常功能（調動作順序）非 bug，未入列；回饋 #5（收工按鈕語意）已口頭說明（收工只清 client 狀態，資料每組即時寫入），未入列
- **下場開場動作**：從 F10 開始（一次一個 feature、TDD）；F10/F11 的 API 面已存在（POST /api/exercises、body-metrics date 欄位），主戰場在前端 `app/static/js/`——記得改 static 資產要 bump `sw.js` CACHE_NAME

## 第九場（2026-07-18）

## 第九場（2026-07-18）
- 開場確認：repo 乾淨、8137 `/health` ok、F1–F6/F8/F9 passing 不變
- Ryan 決定：Cloudflare hostname **他自己去 dashboard 加**（建議值不變：`lift-log.my-super-dev-server.work` → `http://localhost:8137`）
- **下場開場動作**：先問 Ryan hostname 加了沒 → 加了就驗證公開 HTTPS（`curl https://<hostname>/health`）＋請 Ryan 手機 4G 記錄一組 → 兩者都過才把 F7 改 passing（附證據）。F7 過後進 MVP 收官（見 vault PLAN.md checklist）

## 進度總覽
F1–F6、F8、F9 全部 passing（各自附 acceptance-verifier 證據於 feature_list.json）。**F7 failing**，本機部分已完成，剩餘兩步只有 Ryan 能做：

1. **Cloudflare dashboard 加 public hostname**：Zero Trust → Tunnels →（現有 token 型 tunnel，ingress 只能 dashboard 管）→ 建議 hostname `lift-log.my-super-dev-server.work` → service `http://localhost:8137`（照 reels 的慣例；名稱最終由 Ryan 定）
2. **手機 4G 實測**：關 WiFi 開站台記錄一組（F7 acceptance）；順便真機確認 F2–F5（記錄＋課表＋飛航離線，歷次驗收都留了這條）

## 這個 session 做了
- **F6 收尾→passing**：acceptance-verifier live MCP 實呼叫 8/8 PASS
- **F7 本機部分**：`/health`（TDD，無 auth、實探 DB）；services.toml 收編 lift-log（port 8137、autostart）；mission-control 啟停監控實測。**注意孤兒教訓**：中台被 `taskkill /F` 硬殺會讓受管服務全變孤兒佔 port（詳見 mission-control session-handoff 2026-07-18 條目）
- **F8→passing**：GET/POST /api/body-metrics（同日覆蓋 201/200、IntegrityError 競賽復原）、/body SVG 折線頁（body.js，無圖表庫）、heatmap 自體重噸位接 latest_weight；Codex review 3 P2 全修（舊體脂預填、序列先篩後切、防雙擊）；驗收 5/5
- **F9→passing**：DailyStatus model/service（鏡射 body_metrics 含競賽復原）、GET/POST /api/daily-status、MCP log/get_daily_status、日曆明細顯示狀態（休息日也顯示）、interview prompt 改為覆述確認（含當日狀態）後才寫入；Codex review 2 P2 全修（prompt 確認缺口、cache bump v3）；驗收 6/6
- **正式環境**：mission-control 重啟 lift-log，8137 已跑最新 code（shell v3）

## 流程慣例（下場照做）
- feature 完成 → `codex exec review`（codex-review skill）→ verify findings → 修 → acceptance-verifier → 才改 passing
- **改任何 static 資產（js/css/html）→ sw.js CACHE_NAME 要遞增**（sw.js 內有註解釘住）
- Windows curl 發中文 JSON 會編碼壞掉——測試用 `uv run python` + httpx

## 做到一半 / 已知未修
- 無做到一半的程式碼；全部改動已 commit + push
- F7 之外的收官事項（MVP 全 passing 後）：連續自用 2 週對成功指標、README、after-action——見 vault PLAN.md 收官 checklist

## 驗證指令
- `uv run pytest`（121 passed，覆蓋率 98%）；`uv run ruff check .`
- 正式服務由 mission-control 管（`list_services` 應見 lift-log running）；`curl http://127.0.0.1:8137/health` → `{"status":"ok"}`
- MCP 快驗：`claude mcp list` 應顯示 lift-log ✔ Connected（需先 `claude mcp add`，上上場註冊在 local scope）
