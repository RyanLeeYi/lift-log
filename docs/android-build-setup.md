# Android 建置與簽章（Windows）

支援 F61–F64。裝完這份才有辦法產 APK。

**你機器上的現況（2026-07-27 實測）**：Android SDK **已經存在** `%LOCALAPPDATA%\Android\Sdk`
（platform android-35、build-tools 35.0.1 與 36.0.0、platform-tools 含 `adb`），是舊工具鏈留下的。
缺的只有 **JDK**、**cmdline-tools** 與**環境變數**。Node 已是 v22.17.0，符合 Capacitor 8 的要求。

---

## 1. Android Studio

Capacitor 8 最低要求 Android Studio 2025.2.1，裝最新版：<https://developer.android.com/studio>

- 安裝精靈選 **Standard**
- **不需要另外裝 JDK** —— Android Studio 自帶並設定好對應版本
- SDK 已存在，精靈可能直接沿用；若它要另外下載一份也無妨，以下步驟用哪一份都可以，
  只要 `ANDROID_HOME` 指向同一個

## 2. SDK 套件補齊

Android Studio → **Tools → SDK Manager** → **SDK Tools** 分頁，確認勾選：

- **Android SDK Command-line Tools (latest)** ← 目前**沒有**，一定要補
- Android SDK Build-Tools、Android SDK Platform-Tools（已有，確認即可）

**SDK Platforms** 分頁：已有 android-35，夠用。想同時測新版可再勾 Android 16（API 36）。

## 3. 環境變數

```powershell
[Environment]::SetEnvironmentVariable("ANDROID_HOME", "$env:LOCALAPPDATA\Android\Sdk", "User")
[Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", "$env:LOCALAPPDATA\Android\Sdk", "User")
```

**`JAVA_HOME` 也要設**。Android Studio 內含 JBR，但那是 IDE 內部用的——在外部 PowerShell 直接跑
`gradlew.bat` 找不到它，會停在 `JAVA_HOME is not set and no 'java' command could be found`：

```powershell
[Environment]::SetEnvironmentVariable("JAVA_HOME", "C:\Program Files\Android\Android Studio\jbr", "User")
```

（若 Studio 裝在別的位置，以實際的 `...\Android Studio\jbr` 為準。）

再把這幾個目錄加進使用者 PATH：

```
%LOCALAPPDATA%\Android\Sdk\platform-tools
%LOCALAPPDATA%\Android\Sdk\cmdline-tools\latest\bin
%JAVA_HOME%\bin
```

**改完必須開新的終端機**，舊視窗不會吃到新變數。

## 4. 接受授權條款

```powershell
sdkmanager --licenses
```

一路按 `y`。沒做的話 Gradle build 會在中途以 license 未接受失敗。

## 5. 手機開啟 USB 偵錯

設定 → 關於手機 → 連點「版本號碼」七次 → 開發人員選項 → 開啟 **USB 偵錯**，
USB 接上後在手機勾「一律允許」。驗證：`adb devices` 看到裝置且狀態是 `device`。

## 環境自我檢查

```powershell
node --version                 # v22 以上
adb --version                  # 有輸出
sdkmanager --list | Select-Object -First 5
echo $env:ANDROID_HOME         # 新終端機印得出路徑
echo $env:JAVA_HOME            # 指向 Android Studio 的 jbr
java -version                  # 有輸出（沒有的話 gradlew 會直接失敗）
```

---

## 6. 產生簽章金鑰（只做一次）

**金鑰遺失＝無法再對同一顆 app 發更新**（Android 用簽章判定 app 身分，換金鑰只能移除重裝）。
產完立刻備份到密碼管理器。

```powershell
keytool -genkey -v -keystore $env:USERPROFILE\.android-keys\lift-log-release.jks `
  -alias liftlog -keyalg RSA -keysize 2048 -validity 10000
```

- `keytool` 在 Android Studio 的 JDK 底下（`...\Android Studio\jbr\bin\keytool.exe`），
  或設好 `JAVA_HOME` 後直接可用
- 路徑**刻意放在 repo 外**（`~\.android-keys\`）。repo 內的 `.gitignore` 也擋了 `*.jks`／`*.keystore`／
  `keystore.properties`，兩道防線
- 密碼存進密碼管理器，**不要寫進任何筆記或 vault**

接著在 `android/keystore.properties` 寫入（此檔已被 .gitignore 排除）：

```properties
storeFile=C:/Users/user/.android-keys/lift-log-release.jks
storePassword=<你的 store 密碼>
keyAlias=liftlog
keyPassword=<你的 key 密碼>
```

`android/app/build.gradle` 會自動讀它；**檔案不存在時 release build 會產出未簽章 APK**（裝不上手機），
這是刻意設計，讓漏放金鑰在 build 當下就暴露。

## 7. 建置 APK

前端資產同步進原生專案（**每次改 `app/static/` 都要重跑**，否則 APK 裡還是舊畫面）：

```powershell
npx cap sync android
```

產出 release-signed APK（**在 repo 根目錄執行**，不用先 `cd`）：

```powershell
.\android\gradlew.bat -p android assembleRelease
```

APK 位置：`android\app\build\outputs\apk\release\app-release.apk`

裝到手機（同樣在 repo 根目錄）：

```powershell
adb install -r android\app\build\outputs\apk\release\app-release.apk
```

⚠ 若你習慣先 `cd android` 再跑 `.\gradlew assembleRelease`，安裝路徑要跟著少一層，
改成 `adb install -r app\build\outputs\apk\release\app-release.apk`——否則會解析成
`android\android\...` 而找不到檔案。上面用 `-p android` 就是為了避免這個目錄陷阱。

除錯用（不需金鑰、可搭配 Chrome DevTools 遠端偵錯）：`.\android\gradlew.bat -p android assembleDebug`。

## 8. 看 app 的 log

WebView 的 console 會進 logcat：

```powershell
adb logcat | Select-String "Capacitor|chromium|liftlog"
```

Chrome 開 `chrome://inspect` 也能直接對真機的 WebView 下中斷點（debug build 才行）。

---

## 改版流程

web 版靠 sw.js 換版自動到位（F13/F14/F24）。app 版沒有商店的更新鏈，改由 **F67 的自我更新**接手：

1. 改 `app/static/`
2. 升版號（`sw.js` 的 `CACHE_NAME` ＋ `state.js` 的 `APP_VERSION` 兩處）。
   **`versionCode` 會自動跟著 `APP_VERSION` 走**（v65 → 65），不要手動改 `build.gradle`——
   讀不到就直接讓 build 失敗，寧可現在爆，也不要產出一顆更新不了的 APK
3. `npx cap sync android`
4. `.\android\gradlew.bat -p android assembleRelease`
5. **放進發佈目錄**讓 app 自己抓得到：
   `Copy-Item android\app\build\outputs\apk\release\app-release.apk release\lift-log-v65.apk`
6. 手機上開 app → 首頁出現「⬆ 有新版 v65」→ 點它就會下載並喚起安裝器
   （第一次會要求允許「安裝未知應用程式」，app 會直接把你帶到那個設定頁）

`release/` 是自我更新的唯一來源：`GET /api/app/latest` 取目錄裡**版號最大**的 APK。
檔名不符 `lift-log-v<數字>.apk` 會被忽略；舊檔可以留著（取最大值而非最新 mtime，方便回退）。

接著線時 `adb install -r android\app\build\outputs\apk\release\app-release.apk` 仍然更快——
F67 是給不在電腦旁的時候用的。

App 只有 API 打向公開站，**後端改版不需要重出 APK**。

## 不需要的東西

- **Gradle**：專案自帶 wrapper（`gradlew`）
- **Play Store 開發者帳號**：US$25，本專案採 sideload

參考：[Capacitor Environment Setup](https://capacitorjs.com/docs/getting-started/environment-setup)
