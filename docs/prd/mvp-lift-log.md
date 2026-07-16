---
updated: 2026-07-17
feature: F1–F8
---

# lift-log 健身紀錄系統 MVP — PRD

## 背景與目標

健身紀錄散落在筆記與記憶，看不到累積與重量進步；現有健身 app 資料封閉，AI 助理查不到訓練歷史。做一個自家部署的健身紀錄 web：健身房當下用手機單手快記，日曆 heatmap 視覺化堅持成果，並以 remote MCP server 讓 Claude／ChatGPT／Gemini 都能查詢資料。體重／體脂也搬進來成為唯一事實來源（SSOT）。

vault 對應：`projects/2026-07-健身紀錄系統/PLAN.md`。

## 非目標（本次不做）

- 不做多使用者帳號系統（單人使用，全站單一 Bearer token）
- 不做全站 UI 多語系（i18n framework）——只做動作名稱雙語（zh/en）＋顯示切換
- 不做 OAuth（token 夠用；connector 若強制 OAuth 再開）
- 不做訓練計畫生成／AI 教練建議（AI 只「查」，不「教」）
- 不做社群、分享、匯出報表
- 不改動既有 weight-tracker skill（Roam）——它之後自行改接本系統 API，不在本 repo 範圍

## 需求與驗收標準

### 使用者（Ryan，手機瀏覽器）

#### R1：作為使用者，我想用 API 記錄一次訓練的每一組，以便資料進入唯一事實來源

- Given 服務已啟動且請求帶正確 Bearer token
- When `POST /api/workouts`（開始訓練）後對其 `POST /api/workouts/{id}/sets`，body 含 `client_uuid, exercise_id, set_number, weight_kg, reps`，選填 `rpe, rest_seconds`
- Then 回 `201` 與該筆 set JSON；資料落入 SQLite 可由 `GET /api/workouts/{id}` 查回
- Given 相同 `client_uuid` 再送一次（重複提交／離線補傳重放）
- When `POST /api/workouts/{id}/sets`
- Then 回 `200` 與既有那筆，**不新增資料列**（冪等）

#### R2：作為使用者，我想在組間休息時單手快記，以便不中斷訓練節奏

- Given 手機瀏覽器開啟 `/` 並已完成 token 設定（首次輸入，存 localStorage）
- When 點「開練」→ 選動作 → 輸入 kg × reps → 送出
- Then 一組記錄完成的操作皆為大按鈕點擊與數字輸入；同一動作**上次訓練的重量與次數自動帶入**為預設值
- When 送出一組
- Then 組間計時器自動開始；下一組送出時，經過秒數寫入上一組的 `rest_seconds`；RPE 為選填快速鈕（1–10），不擋送出

#### R3：作為使用者，我想用日曆 heatmap 看到堅持成果，以便維持動力

- Given 已有訓練資料
- When 開啟 `/calendar` 月視圖
- Then 每日格子依**當日總噸位**上色（5 級深淺）；噸位 = Σ(重量×次數)，自體重動作以（最新 `body_metrics` 體重＋額外負重）計，無體重紀錄時只計額外負重
- When 點某一天
- Then 顯示當日明細：動作、每組 kg×reps、RPE

#### R4：作為使用者，我想把一串動作存成課表（練腿日／上半身日／混合日），以便開練一鍵帶出今日菜單

- Given 已建立課表（名稱＋動作清單＋順序＋預設組數）
- When 開練時選該課表
- Then 動作清單照課表順序帶出；訓練中可臨時加課表外的動作，不影響課表定義
- When 在課表管理頁新增／編輯／刪除課表
- Then 變更即時生效；刪除課表不影響歷史 workout 紀錄

#### R5：作為使用者，我想斷線時照樣記錄，以便健身房訊號差也不漏記

- Given PWA 已載入（manifest + service worker），目前離線
- When 記錄任意組數
- Then 記錄寫入 IndexedDB 佇列，UI 標示「待同步」；恢復連線後自動重放 POST，靠 `client_uuid` 冪等不重複；同步完成 UI 標示消失
- 原則：**本地是緩衝、server 是 SSOT**——不提供「只存本地」模式

#### R6：作為使用者，我想記錄體重與體脂並看趨勢，以便和訓練量交叉對照

- Given 帶 token
- When `POST /api/body-metrics`（`date, weight_kg, body_fat_pct?`）；或在 UI 輸入
- Then 同日重複送出為**覆蓋更新**（一天一筆）；`/body` 頁顯示體重／體脂折線趨勢；heatmap 的自體重噸位改用最新體重

### AI agent（Claude／ChatGPT／Gemini，經 connector）

#### R7：作為 AI agent，我想查詢訓練歷史與進步曲線，以便回答主人關於訓練的問題

- Given 以 Bearer token 連上 `/mcp`（Streamable HTTP）
- When 呼叫 `query_workouts(start_date, end_date, exercise?)`／`get_progress(exercise)`／`list_templates()`／`get_body_metrics(start_date, end_date)`
- Then 回傳結構化 JSON；`exercise` 參數同時匹配 `name_zh` 與 `name_en`（如「深蹲」「squat」皆命中）
- 同資料另有 REST `GET /api/*` 端點，OpenAPI schema 可供 Custom GPT Action 匯入

#### R8：作為使用者，我想服務公開可達且被監控，以便健身房手機與雲端 AI 都連得到

- Given 自家機以 Cloudflare Tunnel 發布公開 HTTPS
- When 手機關 WiFi 走 4G 開啟站台並記錄一組；AI connector 呼叫 MCP tool
- Then 兩者皆成功；服務收編進 mission-control（啟停＋監控）

## 介面契約

### 資料模型（SQLite，SQLAlchemy 2.0）

```
exercises      id, name_zh, name_en, muscle_group, is_bodyweight(bool), created_at
templates      id, name, created_at
template_exercises  template_id, exercise_id, position, default_sets
workouts       id, date, template_id?, note?, created_at
sets           id, client_uuid(UNIQUE), workout_id, exercise_id, set_number,
               weight_kg(REAL, 自體重動作=額外負重), reps, rpe?, rest_seconds?, created_at
body_metrics   id, date(UNIQUE), weight_kg, body_fat_pct?, created_at
```

- `sets` 為 append-only：API 不提供 update；記錯提供 `DELETE /api/sets/{id}`（軟刪除 `deleted_at`）
- 動作庫預載約 30 個台灣健身房常見動作（雙語），可自由新增

### API（全部要求 `Authorization: Bearer <token>`，錯誤格式 `{"error": "<訊息>"}`）

```
POST   /api/workouts                    開始訓練 → 201
GET    /api/workouts?start=&end=        區間查詢
GET    /api/workouts/{id}               單次明細（含 sets）
POST   /api/workouts/{id}/sets          記一組（client_uuid 冪等）→ 201/200
DELETE /api/sets/{id}                   軟刪除 → 204
GET    /api/exercises?q=                動作庫（q 同時匹配雙語名）
POST   /api/exercises                   新增動作
GET/POST/PUT/DELETE /api/templates…    課表 CRUD
GET    /api/exercises/{id}/last-sets    該動作上次訓練的各組（帶入預設用）
GET    /api/stats/calendar?year=&month= heatmap 資料（每日噸位）
GET/POST /api/body-metrics              體重體脂（同日覆蓋）
GET    /api/stats/progress?exercise=    進步曲線（每次訓練該動作最大重量×次數）
/mcp                                    MCP endpoint（fastmcp，Streamable HTTP）
/                                       靜態 PWA
```

## 介面示意

```
┌─ 記錄頁（手機） ─────────┐   ┌─ 日曆頁 ────────────────┐
│ 今天 7/17 · 練腿日        │   │ ◀ 2026年7月 ▶           │
│ ─────────────────────    │   │ 一 二 三 四 五 六 日      │
│ ▶ 深蹲 Squat             │   │  ░  ▓  ░  █  ░  ░  ▒    │
│   上次: 80kg × 8         │   │  ░  ░  ▒  ░  █  ░  ░    │
│   [ 80 ]kg × [ 8 ]次     │   │ （深淺=當日總噸位5級）    │
│   RPE ①…⑩ (選填)         │   │ ─────────────────────   │
│   ┌─────────────────┐    │   │ 7/16 練腿日 噸位 4,320kg │
│   │   ✓ 完成這組     │    │   │ 深蹲 80×8 80×8 85×6     │
│   └─────────────────┘    │   │ 硬舉 100×5 ...           │
│ 休息 01:24 ⏱             │   └─────────────────────────┘
│ 已完成 3 組 · 待同步 1    │
└──────────────────────────┘
```

## 具體範例（輸入 → 輸出）

1. 記一組：

```json
POST /api/workouts/12/sets
{"client_uuid":"a1b2-…","exercise_id":3,"set_number":2,"weight_kg":80,"reps":8,"rpe":8}
→ 201 {"id":57,"workout_id":12,"exercise_id":3,"set_number":2,"weight_kg":80,"reps":8,"rpe":8,"rest_seconds":null}
（同 client_uuid 重送 → 200，回同一筆 id=57）
```

2. heatmap 噸位（自體重）：最新體重 101.6kg，引體向上（is_bodyweight=true）額外負重 0、做 6 下 → 該組噸位 = 101.6×6 = 609.6；無任何 body_metrics 時 = 0×6 = 0

3. MCP 查進步：`get_progress(exercise="squat")` → `{"exercise":{"name_zh":"深蹲","name_en":"Squat"},"points":[{"date":"2026-07-10","top_weight_kg":80,"reps":8},{"date":"2026-07-16","top_weight_kg":85,"reps":6}]}`

## 邊界情況與錯誤行為

- 缺必填欄位／型別錯：`400 {"error":"<欄位> required"}`（Pydantic 驗證）
- token 缺或錯：`401 {"error":"unauthorized"}`（所有 `/api/*` 與 `/mcp`；靜態頁不擋，資料靠 API token 保護）
- 不存在的 id：`404`
- `weight_kg < 0`、`reps <= 0`、`rpe` 超出 1–10、體重超出 30–300：`400`
- 離線補傳時 workout 已不存在（被刪）：該筆標記失敗留在佇列供手動捨棄，不無限重試
- SQLite 寫入衝突：FastAPI 單 worker，寫入序列化，不做額外鎖

## 技術約束（本專案特有）

- Python 3.12+，套件管理用 **uv**；FastAPI + SQLAlchemy 2.0 + SQLite；MCP 用 **fastmcp** 掛載
- 前端：原生 JS（ES modules）＋ CSS，**無打包器、無框架**；heatmap 用 CSS grid 自繪，不引入圖表庫
- 深色主題優先（健身房環境）；動作名稱顯示語言切換存 localStorage
- token 存 `.env`（`LIFTLOG_TOKEN`），啟動時驗證存在，缺少即拒絕啟動

## 分階段任務清單

- [ ] F1 資料層＋記錄 API（驗證：pytest——CRUD、冪等、401/400 邊界全過）
- [ ] F2 手機記錄 UI（驗證：手機瀏覽器完成一次真實記錄流程；上次重量帶入；組間計時器）
- [ ] F3 日曆 heatmap（驗證：pytest 噸位計算含自體重規則；月視圖與日明細顯示正確）
- [ ] F4 課表選單（驗證：建課表→開練帶出清單→臨時加動作；刪課表不影響歷史）
- [ ] F5 PWA 離線佇列（驗證：DevTools offline 記 3 組→恢復連線自動補傳不重複）
- [ ] F6 MCP＋AI connector（驗證：4 個 tools 回正確資料；至少一家 connector 實連成功）
- [ ] F7 Cloudflare Tunnel 部署＋mission-control 收編（驗證：4G 手機實測記錄成功）
- [ ] F8 體重體脂（驗證：同日覆蓋、趨勢頁、heatmap 改用最新體重、MCP get_body_metrics）

## 完成定義（必過的指令）

- `uv run pytest` 全過，覆蓋率 ≥ 80%
- `uv run ruff check .` 無錯誤

## 開放問題

- [ ] 全站 UI 多語系要不要做（MVP 只做動作名雙語；決策人：Ryan，收官時再議）
- [ ] Cloudflare Tunnel 網域名稱（決策人：Ryan，F7 動工時定）
- [ ] ChatGPT／Gemini connector 對 Bearer token 的實際支援細節（F6 動工時實測，若強制 OAuth 停下來問）
