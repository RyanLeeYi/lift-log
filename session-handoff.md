# session handoff

最後更新：2026-07-28（**F61＋F62 完成並驗收通過**，app 版休息提醒改為手機端本機通知）

## 現況（7/28 收工）

**62/66 passing**，剩 F63、F64（通知階段 3/4）與 F65、F66（F62 review 長出來的），
**四條的 acceptance 都還沒簽核凍結**。線上 web 版 **v62**，原始碼已到 **v64**（F62 動了 `app/static/`，
web 行為不變但版號升了兩版，下次部署要一起上）。

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
