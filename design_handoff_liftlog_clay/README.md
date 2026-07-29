# Handoff: lift-log 行動版改版（陶土夜色 Soft Clay）

## Overview

`lift-log` 現行前端是 `app/static/`（原生 JS，無打包器，橡膠黑 × 琥珀 LED）。
這份 handoff 是**整個 app 的視覺與互動改版提案**，方向代號 **陶土夜色 Soft Clay**（原型中的 `4a`），
外加**浮動休息計時視窗**（F64）的完整設計（原型中的 `5a` / `5b`）。

涵蓋八個畫面：首頁、挑課表、今日菜單、記錄一組（含休息倒數）、訓練日曆、動作表現、體重體脂、編輯課表。

功能語意**完全沿用現有實作**（`app/static/js/state.js`、`app.js`、`templates.js`、`calendar.js`、
`body.js`、`exercise-detail.js`）——這是換皮＋少數流程優化，不是改資料模型。

## About the Design Files

Bundle 裡的 HTML 是**設計參考**，不是要直接上線的程式碼。它是用來表達「長什麼樣、怎麼動」的原型。

實作方式：**在 lift-log 既有的 `app/static/` 環境裡重做這些畫面**——原生 JS、`el()` helper（`js/dom.js`）、
`css/app.css` 的 class 命名慣例、`js/icons.js` 的 Lucide 內嵌圖示。**不要**把原型的 inline style 搬過去；
原型全用 inline style 只是為了讓它能單檔開啟，正式實作應改寫成 `app.css` 的 CSS 變數 + class。

## Fidelity

**High-fidelity。** 顏色、字級、圓角、間距都是最終值，可以直接照抄數值。
唯一例外：所有數據（重量、組數、日期、體重）都是示意資料，實作時接真 API。

## Design Tokens

替換 `app/static/css/app.css` 的 `:root`：

```css
:root {
  --bg:        #221E1A;  /* 頁面底 */
  --card:      #2E2822;  /* 卡片 */
  --card-hi:   #3B342C;  /* 強調卡片 / chip 底 / 次要按鈕 */
  --line:      #544A3D;  /* 分隔線、外框、未填滿的進度段 */
  --text:      #F0E9DF;
  --text-mid:  #C9BFB1;  /* 次要文字（未進行中的動作名） */
  --text-dim:  #A99C8C;  /* 說明文字 */
  --text-mute: #8F8375;  /* 標籤、單位、日期 */
  --text-faint:#6E6357;  /* 組號、星期表頭 */
  --accent:    #D9B25F;  /* 沙金：主要動作、進行中、PR、倒數 */
  --on-accent: #241E14;  /* 沙金上的文字 */
  --over:      #C96A4E;  /* 赤陶：休息超時、刪除 */
  --good:      #8FA37A;  /* 苔綠：體重下降 / 進步（僅此用途） */
  --mono: "IBM Plex Mono", "SF Mono", "Roboto Mono", Consolas, monospace;
  --sans: Archivo, "Noto Sans TC", -apple-system, "Segoe UI", Roboto, sans-serif;
}
```

日曆 heatmap 5 階（0 → 當月最大）：
`#2E2822` · `#4A3E2A` · `#6B5730` · `#A88742` · `#D9B25F`
（第 3、4 階的文字改用 `--on-accent` 才有對比；未來日期底 `#262119`、字 `#544A3D`）

### 字體

- 顯示 / UI：**Archivo**（400 / 500 / 600 / 700）＋ **Noto Sans TC** 接中文
- 數據 / 標籤 / 日期：**IBM Plex Mono**（400 / 500 / 600）

app 版離線可用，字型必須**打包進 APK**（`app/static/fonts/` + `@font-face`），不要走 Google Fonts CDN。
若不想加字型檔，回退：顯示字用系統 sans（`--sans` 現值），數據字用現有的 `--mono`；
但字重對比會變弱，建議至少內嵌 Archivo 的 500/700 兩個字重。

### 字級（實測值）

| 用途 | 字體 / 字重 / 大小 | 其他 |
|---|---|---|
| 畫面標題（推胸日、槓鈴臥推） | Archivo 700 · 19–20px | line-height 1 |
| 首頁大數字（本週 3） | Archivo 700 · 52px | letter-spacing −.03em |
| 卡片標題（動作名） | Archivo 700 · 16–17px | |
| 次要動作名（未開始） | Archivo 600 · 17px | color `--text-mid` |
| 步進器數值（KG / REPS） | Plex Mono 600 · 40px | letter-spacing −.03em |
| 體重最新值 | Plex Mono 600 · 52px | line-height .9 |
| 倒數（app 內圓環） | Plex Mono 600 · 34px | |
| 組列 / 歷史 chip | Plex Mono 500 · 12–14px | |
| 區塊標籤（本週進度、今天的安排） | Plex Mono 500 · 11px | letter-spacing .14em |
| 單位 / 日期 / 說明 | Plex Mono 400 · 10–12px | color `--text-mute` |

### 圓角 / 間距 / 陰影

- 卡片 `22px`；大卡片（休息、體重）`26px`；輸入框 `18px`；日曆格 `10px`
- **所有按鈕與 chip 一律 `border-radius: 99px`**（藥丸形）——這是本方向的識別特徵
- 畫面左右 padding `14px`；卡片內 padding `18–22px`；卡片間距 `10–12px`
- 頭部區塊 padding `18px 6px 16px`
- **不使用邊框做分隔**，靠底色差（`--bg` vs `--card` vs `--card-hi`）；
  僅卡片內部分隔用 `1px solid var(--line)`
- 陰影只用在浮動視窗（見下）；app 內卡片無陰影

## Screens / Views

所有畫面共用結構：
```
.screen { display:flex; flex-direction:column; min-height:100%; padding:0 14px; background:var(--bg) }
.screen-head { display:flex; align-items:center; gap:12px; padding:18px 6px 16px }
.back-btn { width:40px; height:40px; border-radius:99px; background:var(--card); color:var(--text-mid) }
.screen-head .t  { font: 700 19px/1 var(--sans) }
.screen-head .st { font: 400 11px/1 var(--mono); color:var(--text-mute); margin-top:6px }
```
底部主按鈕一律 `margin-top:auto` + `padding-bottom:16px`。

---

### 1. 首頁 home

**目的**：一眼看到本週進度與今天要練什麼，一鍵開練。

- **問候列**：`早安，Ryan`（Archivo 700 17px）／ 右側日期 `7月29日 週三`（Mono 400 12px, `--text-mute`）
- **本週進度卡**（`--card`, r22, padding 22/20/24）
  - 標籤 `本週進度`
  - `3`（Archivo 700 52px, `--accent`）＋ `/ 4 天`（Archivo 400 15px, `--text-mute`, 對齊底線 padding-bottom 5px）
  - 七段進度條：`flex:1; height:8px; border-radius:99px`，gap 6px
    已練 `--accent`／今天 `--line`／未練 `--card-hi`
- **今日課表卡**（`--card`, r22）
  - 標籤 `今天的安排` → `推胸日`（Archivo 700 26px）＋ `Push Day`（Mono 400 12px）
  - 動作 chips：`--card-hi` 底、r99、padding 8/14、Archivo 500 13px；
    組數用 `--accent` 的 Mono 11px 接在名字後
  - 主按鈕 `開始訓練`：`--accent` 底、`--on-accent` 字、r99、padding 18、Archivo 700 17px
  - 次要 `換一份課表`：透明、`--text-mute`、Archivo 500 13px
- **上次訓練卡**：左側「上次 · 拉背日 / 7/27 · 18 組」，右側 `4,820 kg`（Mono 600 17px, `--accent`）
- **底部四格導覽**：`flex:1` 等分、`--card` 底、r16、padding 15/4、Archivo 500 12px、`--text-mid`
  → 課表 / 日曆 / 表現 / 體重

### 2. 挑課表 templateSelect

- 每份課表一張卡（r22, padding 20）。**選中／推薦的那份用 `--card-hi`**，其餘 `--card`
- 卡內：課表名（Archivo 700 19px）＋ 右側 `4 動作 · 13 組`（Mono 400 12px）
- 展開的那張列出動作 chips（`--card` 底、r99、padding 6/12、Archivo 400 12px）；
  其餘只顯示 `上次 7/27 · 4,820 kg`
- 最後一顆 `自由訓練`：透明底 + `1px solid var(--line)`、r99、padding 16

### 3. 今日菜單 picker（引導式訓練）

- 標題列右側加**環形進度**：44px 圓、`3px solid var(--accent)`、內填百分比（Mono 600 12px）
- 每個動作一張卡：
  - **進行中** → `--card-hi` 底、右上 `進行中`（Mono 500 11px, `--accent`）
  - 其餘 → `--card` 底、動作名 `--text-mid`
  - 右側組數指示：每組一段 `20×6px` r99；已完成 `--accent`、未完成 `--line`（進行中卡）／`--card-hi`（未開始卡）
  - 第二行 `60 kg × 8`（Mono 400 12px, `--text-dim` / `--text-mute`）
- **底部「接著做」**（本次改版新增的流程優化）：
  - 小標 `接著做`（Mono 400 11px, `--text-mute`）
  - 藥丸大按鈕：`--accent` 底、padding 17/24、左側兩行（`槓鈴臥推 · 第 3 組` Archivo 700 17px ／
    `60 kg × 8` Mono 500 11px opacity .7），右側 `→` 20px
  - 一按直接進 logger 並帶入該動作與 set_number（對應現有 `state.setCounts` 續號邏輯）
- `結束訓練`：純文字、`--text-mute`、置中

### 4. 記錄一組 logger ★ 核心畫面

兩態切換（沿用現有 `state.restStartedAt` 的語意）：

**就緒態（未在休息）**
1. **上次提示卡**（`--card`, r22, padding 18/20）
   - `上次 7/22 · 57.5 kg × 8`（Mono 400 12px, `--text-mute`）＋ 右側 `＋2.5`（Mono 500 12px, `--good`）
   - **快調列**（新增）：三顆藥丸等寬 —— `同上`（`--accent` 底）／`+2.5kg`／`減量`（`--card-hi` 底）
     一按即填入 weight/reps，不必戳步進器
2. **已完成組列表**（`--card`, r22, padding 10/8）
   每列：組號（Mono 500 14px, `--text-faint`）／`60.0 kg × 8`（flex 1）／RPE 詞（11px, `--text-mute`）

**休息態**：上方的「上次提示卡＋快調列」**整塊換成休息卡**，其餘不動。

**休息卡**（`--card`, r26, padding 16/20/18, 置中）
- 狀態字 `休息一下` / `已暫停` / `超時了`（Mono 500 11px, letter-spacing .18em, `--text-mute`）
- **圓環**：142×142 容器，SVG `viewBox 0 0 100 100`、`transform: rotate(-90deg)`
  - 底環 `circle r=44 stroke=var(--line) stroke-width=7`
  - 進度環 同參數但 `stroke=var(--accent)`、`stroke-linecap=round`、
    `stroke-dasharray=276.5`、`stroke-dashoffset = 276.5 * (1 - 剩餘/目標)`
  - 環中央：`1:12`（Mono 600 34px, `--accent`）＋ `/ 90s`（Mono 400 10px, `--text-mute`）
- 控制列：`暫停|繼續` ／ `−15s` ／ `+15s`，三顆等寬藥丸、`--card-hi` 底、padding 13/0
  （現行的 60/90/120/180 循環 chip 被這組取代；若要保留循環，改成長按 `+15s` 叫出選單）
- **超時**：`剩餘 < 0` 時圓環、數字、底部主按鈕**同時**轉 `--over`，數字顯示 `+0:08`

**底部固定區（兩態共用）**
- **步進器**兩格（`--card`, r22, padding 16/12/18, 置中）
  - 標籤 `KG` / `REPS`（Mono 500 10px, letter-spacing .2em, `--text-mute`）
  - 數值 Mono 600 40px
  - `−` `＋` 兩顆藥丸，`--card-hi` 底、padding 10/0、Mono 500 17px
- **累度軸**：`這組多累？`（Archivo 500 12px, `--text-mute`）＋ 右側形容詞（Archivo 600 13px, `--accent`）
  下方五顆等寬藥丸 `輕鬆 / 有餘力 / 吃力 / 很吃力 / 力竭`（對應 rpe 6–10，同現行 `dom.js` 的 `rpePicker`）
  選中 `--accent` 底 + `--on-accent` 字；未選 `--card-hi` 底 + `--text-dim` 字
- **主按鈕**：就緒態 `完成這組`（`--accent`）／休息態 `繼續下一組`（超時時 `--over`）
  r99、padding 19、Archivo 700 17px

> ⚠ **版面高度**：休息態的內容高度必須 ≤ 可視高度，主按鈕不得被推到摺線下。
> 上面的圓環 142px、休息卡 padding 16/18 就是為此調過的值；加東西前先量。

### 5. 訓練日曆 calendar

- 日曆卡（`--card`, r22, padding 18/16）
  - 星期表頭 `日一二三四五六`（Mono 400 10px, `--text-faint`）
  - 7 欄 grid、gap 6px、`aspect-ratio: 1`、`border-radius: 10px`、Mono 400 11px
  - 底色走 heatmap 5 階；**選中日加 `2px solid var(--text)`**（未選中 `2px solid transparent`，避免尺寸跳動）
- 當日明細卡（`--card`, r22, padding 20）
  - 標題 `7月24日 · 腿日`（Archivo 700 16px）＋ 右側總量（Mono 600 13px, `--accent`）
  - 狀態 chips：`睡眠 4/5`、`狀態 3/5`、自由備註 —— `--card-hi` 底、r99、padding 6/12
  - 每個動作：標題列（Archivo 600 15px ＋ 組數 Mono 400 11px），下方組 chips
    `--card-hi` 底、r99、padding 7/13、Mono 500 12px；
    **當日最佳組**改 `--accent` 底 + `--on-accent` 字 + 尾綴 `★`
  - 第二個動作起收合，只留 `4 組 ▾`（點擊展開，沿用現有 F34 行為）
- 底部 `補記這一天`：透明 + `1px solid var(--line)`、r99、`--accent` 字

### 6. 動作表現 exercise-detail

- **三張 PR 卡**橫排（`flex:1`, r20, padding 16/14）
  第一張 `推估 1RM` 用 `--card-hi` 底 + `--accent` 數字；其餘 `--card` 底
  標籤 Mono 400 10px ／數值 Mono 600 26px
- **時間窗**五顆藥丸等寬（`1M / 3M / 6M / 1Y / 全部`），選中 `--accent` 底
- **最佳組長條圖**（`--card`, r22, padding 20/18/16）
  - 標題列：`每次最佳組` ＋ 右側最大值（Mono 600 16px, `--accent`）
  - 長條：`flex:1`、`border-radius:99px`、高度 = 值 / 最大值
    一般 `--line`；**PR 那次 `--accent` 且上方加 `★`（9px, `--accent`）**
  - 圖表高 130px；底部 `4月 / ★ 個人紀錄 / 7月`
- **歷來紀錄卡**：日期（Mono 600 13px）＋ 相對天數 ＋ 右側總量；下方組 chips（同日曆規則，PR 用 `--accent`）

### 7. 體重體脂 body

- 體重 / 體脂兩顆藥丸 toggle（選中 `--accent`）
- 主卡（`--card`, r26, padding 24/20/18）
  - 左：`78.4`（Mono 600 52px, line-height .9, `--accent`）＋ 單位（Mono 400 15px）
  - 右：`−3.5 kg`（Mono 600 13px, `--good`）＋ `近三個月`
  - 長條圖：24 根、`flex:1`、r99、高度 = `14% + 正規化 * 82%`；最新一根 `--accent`，其餘 `--line`
  - 底部日期範圍（Mono 400 10px）
- `記錄今天`：`--accent` 藥丸大按鈕
- 歷史清單卡（`--card`, r22, padding 10/8）：日期 / `78.4 kg · 16.2 %` / 差值（下降 `--good`、上升 `--text-mute`）

### 8. 編輯課表 templateEdit

- 課表名 input：`--card` 底、r18、padding 16/20、Archivo 700 17px、無邊框
- 每個動作一張卡；**第一張（或選中的）用 `--card-hi`**
  - 名稱（Archivo 700 16px）＋ 英文別名（Mono 400 11px）
  - 控制列：左「− `4 組` ＋」（38px 圓鈕）／右「↑ ↓ ✕」（✕ 用 `--over`，與 ↑↓ 間距 6px）
  - 分隔線後：`參考休息` ＋ `90 s` 藥丸（`--accent` 字）
- `＋ 加入動作`：透明 + `1px solid var(--line)` 藥丸
- 底部：`儲存課表`（`--accent`）／`取消`（純文字）

---

## 浮動休息計時視窗（F64）

系統層 overlay（`SYSTEM_ALERT_WINDOW`），兩態。**唯一使用陰影的元件**：
`box-shadow: 0 18px 44px rgba(0,0,0,.42)`（展開）／`0 14px 32px rgba(0,0,0,.42)`（收合）。

### 收合態
- **76 × 76 圓形**，`--card` 底
- 內嵌小圓環：`circle r=26 stroke-width=7`、`stroke-dasharray=163.4`、
  `stroke-dashoffset = 163.4 * (1 - 剩餘/目標)`
- 中央倒數 Mono 600 17px（`--accent`；超時 `--over`，顯示 `+0:08`）
- 整顆可拖曳（`cursor: grab`），點一下 → 展開

### 展開態
- 寬 **214px**、`--card` 底、`border-radius: 24px`
- 頂部把手列（padding 12/16/10）：`22×3px` 拖曳條（`--line`）＋ `LIFT·LOG`
  （Mono 500 10px, letter-spacing .18em, `--text-mute`）＋ 右側 `▾`
- 圓環 **126px**（`r=44 stroke-width=8`，`dasharray 276.5`），中央倒數 Mono 600 30px ＋ 狀態字 Mono 400 9px
- 動作提示 `槓鈴臥推 · 第 3 組`（Archivo 500 11px, `--text-dim`）
- 控制：`暫停|繼續` ／ `+15s` 兩顆等寬藥丸（`--card-hi`）
- 主按鈕 `回 app 記下一組`：`--accent` 藥丸（超時轉 `--over`）→ 拉起 app 到 logger

### 權限未授權時
依 README 既有立場**誠實標示**，不假裝功能存在：
設定列開關維持 OFF（軌道 `--card-hi`、鈕 `--text-faint`），副標寫
`需系統授權 · 點此前往設定`，點擊送到系統的「顯示在其他應用程式上層」頁。
未授權時倒數仍走通知列（F63），功能不消失。

## Interactions & Behavior

| 觸發 | 行為 |
|---|---|
| 首頁「開始訓練」 | 建立 workout → 今日菜單 |
| 菜單「接著做」大按鈕 | 直接進 logger，帶入下一個未完成動作與 set_number |
| logger「完成這組」 | 送出該組 → 休息卡取代快調列、倒數從課表 `rest_hint_seconds` 起算（預設 90） |
| 倒數歸零 | 圓環 / 數字 / 主按鈕同時轉 `--over`，開始往上數（顯示 `+m:ss`），震動 + 通知 |
| 「繼續下一組」 | 凍結本次休息秒數寫入下一組（沿用現有 `pendingRestSeconds`）、停倒數、回就緒態 |
| `±15s` | 同時改剩餘與目標（環的分母跟著變），並重排已排定的本機通知 |
| 快調 `同上 / +2.5kg / 減量` | 就地改 weight/reps，不送出 |
| 日曆點日期 | 只換下方明細，不整頁重繪 |
| 浮動視窗點本體 | 收合 ⇄ 展開；長按拖曳移動位置（位置需持久化） |

**動效**：全部 `160ms ease-out`。休息卡出現用高度 + 透明度；圓環 `stroke-dashoffset` 每秒線性更新
（`transition: stroke-dashoffset 1s linear`）。`prefers-reduced-motion` 時取消所有 transition。

## State Management

沿用 `app/static/js/state.js`，**不需新增欄位**。改版只動渲染層。
唯一新增的是快調列，它只是既有 `state.weightKg` / `state.reps` 的三顆預設值捷徑。

浮動視窗需要新的持久化：視窗座標（`localStorage`），以便下次出現在原位。

## Assets

- **圖示**：沿用 `app/static/js/icons.js`（Lucide 內嵌路徑、`stroke=currentColor`、線寬 2、視框 24）。
  原型裡的 `◪ ← ★ ▾` 等字元是佔位，實作請換成 icons.js 的對應圖示；
  `★` 建議新增一個 Lucide `trophy` 或 `award` 路徑進 icons.js。
- **App icon**：`app/static/icon.svg` 的槓鈴改用新色（底 `#221E1A`、槓片 `#D9B25F`、握把 `#F0E9DF`）。
- **字型**：Archivo（OFL）、IBM Plex Mono（OFL）、Noto Sans TC（OFL）——自行下載內嵌，勿用 CDN。
- 原型未使用任何點陣圖或第三方元件庫。

## Files

- `Lift Log 行動版設計.dc.html` — 全部設計。用瀏覽器直接開，可點擊操作。
  - **turn 4 / `4a`** = 本次採用的方向，八畫面完整可點原型（右側有畫面跳轉列）
  - **turn 5 / `5a` `5b`** = 浮動計時視窗，`5a` 可互動、`5b` 是三態 1:1 規格
  - turn 1–3 是被否決的其他方向（骨紙、粗獷塊面、藍圖夜視），保留供對照，實作時忽略
- `android-frame.jsx` — 只是展示用的 Android 外框，**不是設計的一部分**
- `support.js` — 原型 runtime，實作不需要
- `screenshots/` — 陶土夜色（`4a` / `5a` / `5b`）各畫面截圖，2× 解析度：

  | 檔案 | 畫面 |
  |---|---|
  | `01-home.png` | 首頁 |
  | `02-session-menu.png` | 今日菜單（引導式訓練） |
  | `03-logger-ready.png` | 記錄一組 · 就緒態（含快調列） |
  | `04-logger-rest.png` | 記錄一組 · 休息態（圓環倒數） |
  | `05-calendar.png` | 訓練日曆 + 當日明細 |
  | `06-exercise-trends.png` | 動作表現 · PR 與長條圖 |
  | `07-body.png` | 體重體脂 |
  | `08-template-edit.png` | 編輯課表 |
  | `09-plan-select.png` | 挑課表 |
  | `10-floating-timer-expanded.png` | 浮動計時視窗 · 展開態 |
  | `11-floating-timer-collapsed.png` | 浮動計時視窗 · 收合態 |
  | `12-floating-timer-spec.png` | 浮動計時視窗 · 三態 1:1 規格 + 權限開關 |

  截圖含手機外框（412×892 內容區），量測時請扣掉外框與系統列。

## 給實作者的提醒

1. 這是**換皮**，不是重寫。先讀 `app/static/js/*.js` 弄清現有流程，再改 `css/app.css` 與各畫面的 DOM 組法。
2. 專案規則見 repo 的 `CLAUDE.md`：一次一個 feature、必須附測試與 lint 輸出、
   動到 `app/static/` 就要重出 APK（`npx cap sync android` → `assembleRelease`）。
3. 現行 CSS 裡有大量「矮螢幕退讓」的 media query 與門檻算式（`.screen.fills`、`.body-list` 那段）。
   換皮會改變固定區塊高度，**那些門檻數字全部要重算**，註解裡有算式來源。
4. 觸控目標維持 44px 下限（現行 F77 已處理過一輪，別退回去）。
