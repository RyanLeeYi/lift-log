# Capacitor 殼 vs 全原生 Kotlin：對 lift-log 的具體差別

- **日期**：2026-07-27
- **狀態**：**已決議 —— 維持 Capacitor，不改全原生**（Ryan 於 2026/07/27 拍板）。F61–F64 規格不變。若日後想學 Compose，依 §6 結論另開小專案，不重寫 lift-log
- **問題**：F61–F64 目前規格是 Capacitor（WebView ＋ 原生 plugin）。要不要改成 Kotlin + Compose 全原生？

---

## 0. 一句話差別

Capacitor 給你「**有原生能力的現有 app**」；全原生給你「**一個新 app，和一次 Kotlin 學習經驗**」。功能上兩者最終能做到的事幾乎一樣，差的是畫面怎麼畫、以及你要付多少重寫成本。

---

## 1. 使用者實際感受得到的差別

以 lift-log 的實際互動型態（單手快記：點按鈕、stepper 加減、開關視窗、看日曆與圖表）逐項對照：

| 面向 | Capacitor | 全原生 | 對 lift-log 的實際影響 |
|---|---|---|---|
| 冷啟動速度 | 慢一截；`server.url` 模式還要等網路 | 快 | **有感**。健身房要快速記一組時最明顯 |
| 捲動慣性／over-scroll 回彈 | 接近但不完全一致 | 系統原生 | 小。F50–F58 的清單多為 4–10 項，不是長列表快滑 |
| 鍵盤推擠版面 | WebView 常見痛點，需額外處理 | 系統處理 | **中**。你的輸入是 stepper 為主、鍵盤用得少，影響被稀釋 |
| 動畫與轉場 | 可做但不保證 60fps | 有保障 | 小。現行設計本來就沒什麼轉場 |
| heatmap／折線圖 | 現行 CSS grid 與 SVG 自繪，已完成且調過 | Compose Canvas，其實**更好寫也更快** | 原生在這項確實較優，但你已經付過一次成本了 |
| 系統整合（widget／Quick Settings tile／Wear） | 做不到 | 可做 | 現在不需要，但這是原生獨有的天花板 |
| 通知、前景服務、浮動視窗 | **和原生一樣**（F62–F64 本來就是原生程式碼） | 相同 | **零差別**——這是關鍵，你想要的三件事 Capacitor 都拿得到 |

**結論**：你最想要的浮動倒數與可靠通知，兩條路拿到的是同一個東西。真正差在冷啟動與少量手感細節。

---

## 2. 工作量：具體到行數

現況（實測）：

- 前端 **4,499 行 JS ＋ 861 行 CSS ＝ 約 5,360 行**（`app.js` 1,264／`calendar.js` 906／`templates.js` 682／`body.js` 664／`exercise-detail.js` 434 ＋ 六個小模組）
- 後端 2,181 行 Python、測試 2,535 行 —— **兩條路都不用動**

全原生要重寫的東西：

1. 八個畫面全部（setup／home／logger／calendar／templates 列表與編輯／body／exercise-detail）
2. 日曆 heatmap（CSS grid → Compose Canvas 或 Lazy grid）
3. 兩套自繪圖表（SVG → Canvas，含 F56–F59 的區間檔位邏輯與 F57 的時間軸）
4. 離線佇列（IndexedDB ＋ Service Worker → Room ＋ WorkManager）—— **這塊語意最難搬**，F5 那些冪等／重放／捨棄分支要重新想一遍
5. 整套 E2E（Playwright → Compose UI Test／Espresso），現有腳本全數作廢

**最被低估的一塊**：`session-handoff.md` 記錄 F50–F58 花了大量時間在版面門檻算式上，踩了**五次坑**才穩定（門檻 N 的算式、min-height 下限、chips 換行、自訂面板例外）。那些調校是「針對 WebView 與 CSS flex 的解」，換成 Compose **完全用不上**，但同一類問題（不同螢幕高度下清單怎麼填滿）會以新的形式重來一遍。

**估時**：Capacitor 階段 1–4 約 8–14 天；全原生保守估 **3–6 週**（含 Kotlin/Compose 學習曲線——你的既有棧是 .NET／Python／JS，Compose 是全新的）。

---

## 3. 維護成本

- **Capacitor**：一份前端同時服務 web 與 app。改一次兩邊都到。多的只是一個 Gradle 建置步驟
- **全原生**：web 版與 app 版**永久分家**。每加一個功能要做兩次，或者放棄 web 版

第二點值得想清楚：你的 MCP／PWA／self-host 這條線是靠 web 版撐起來的。若 app 版分家，web 版會慢慢腐化成「舊版」。

---

## 4. 作品集角度

`PLAN.md` 寫的定位是「AI 應用工程師轉軌」，看點是 remote MCP server 設計、PWA 離線佇列、self-host 部署。**Android 原生開發不在這條線上**，寫進履歷是另一個方向的證據。

但 `identity/about-me.md` 的價值排序第一位是**技術成長**——「能不能學到新東西」。全原生確實是新東西，Capacitor 幾乎不是（設定檔 ＋ 少量 Kotlin plugin）。

這兩件事互相拉扯，只有你能決定哪個權重高。誠實講：如果目標是投 AI 應用工程師職缺，多花三到六週學 Compose 的機會成本，可以拿去做 backlog 裡的高雄景點美食 MCP/RAG 或 Smart Food Advisor，那兩個直接加強主線。

---

## 5. 退出成本（這條常被忽略）

- **Capacitor → 之後改全原生**：後端與 API 完全沿用，等於今天多花的 8–14 天不會白費，只是 UI 那層被取代。門是開的
- **全原生 → 反悔回 web**：Kotlin 那幾週的產出無法回收

也就是說，**先做 Capacitor 是可逆的，先做全原生是不可逆的**。

---

## 6. 建議的判準

不用比較「哪個技術好」，問三個問題就夠：

1. **你要的是好用的工具，還是一次 Android 學習經驗？** —— 前者選 Capacitor，後者選原生。這是唯一真正的分水嶺
2. **web 版你還要嗎？** —— 要，就別分家
3. **接下來三到六週的時間，拿去學 Compose 和拿去做下一個 AI 主線專案，哪個你比較不會後悔？**

若三題答案指向「工具好用 ＋ 保留 web ＋ 時間留給 AI 主線」，現行 F61–F64 規格不用改。

若你其實想要的是**學 Android**，那更誠實的作法可能不是重寫 lift-log——而是把 lift-log 用 Capacitor 收掉，另外開一個小型原生專案專門練 Compose，兩件事都做得更乾淨。
