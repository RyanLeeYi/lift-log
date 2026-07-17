# Session Handoff
> 最後更新：2026-07-17（第六場：F6 實作完成＋connector 實連成功；code review finder 跑完但 verify/修復未做即觸用量門檻收工——**F6 維持 failing**）

## 這個 session 做了（全程 TDD，先紅後綠）
- **services.workouts.log_workout**：單一交易入口（整包寫入/整包拒絕、未知動作雙語比對回相近建議、create_missing 才建檔、template 名稱解析、噸位含自體重×最新體重）
- **body_metrics**：BodyMetric 模型（date UNIQUE）＋service（同日覆蓋 upsert、區間查詢、latest_weight）；schema 驗證 30–300／體脂 0–100
- **services.stats.get_progress**＋REST `GET /api/stats/progress?exercise=`（雙語解析 `exercises.find_by_name`）
- **app/mcp.py**：查詢 tools ×4＋記錄 tools ×2＋prompt `log-workout-interview`；DebugTokenVerifier+compare_digest 接 settings.token；掛載 `/mcp`（FastAPI 帶 `lifespan=mcp_app.lifespan`）
- **踩坑已修**：`/mcp`（無尾斜線）掉進靜態檔 mount 回 405 → main.py 加 middleware 改寫 path（有測試釘住）；Claude CLI 因此初連失敗，修後 ✔ Connected
- **connector 實連成功**：`claude mcp add` → `claude -p` 實呼叫 log_workout＋get_progress，證據 `docs/evidence-f6-mcp-connector.txt`（用 `LIFTLOG_DB=./liftlog_connector_demo.db` 隔離，主資料未污染）
- 92 tests 全過、覆蓋率 99%、ruff 乾淨

## 下一步（下場開場直接做）：處置 review findings → acceptance-verifier → 才能改 passing
8 個 finder agents 已跑完（verify 階段未跑）。findings 去重後如下，下場先 verify 再修：

**正確性（嚴重度排序）**
1. `log_workout` 冪等缺失：client_uuid 由 server 端 uuid4 產生——MCP 呼叫 timeout 後 LLM 重試會整包重複寫入（REST 路徑有冪等、MCP 路徑沒有）。方向：tool 加選填 client_uuid/idempotency key，或文件化風險
2. create_missing 大小寫變體重複建檔：unknown 去重用原字串、比對用 lower——`["Face Pull","face pull"]` 會建兩筆 Exercise 留一筆孤兒
3. mcp `log_workout` 沒接 ValidationError：`sets=[]` 時 LogWorkoutIn 炸 raw tool error，違反 {"error":...} 契約（log_body_metrics 有接，不一致）
4. auth：`secrets.compare_digest` 遇非 ASCII token 會 TypeError → 500 而非 401（guard `t.isascii()` 或比 bytes）
5. DebugTokenVerifier（debug 命名、預設 validate 全放行）當生產 auth——升級 fastmcp 或重構漏掉 validate 參數會靜默變成全放行；考慮改自訂 TokenVerifier 或 StaticTokenVerifier
6. 空白動作名：`" "` 過 min_length=1，strip 後空字串 → create_missing 建出空名動作；_suggest 對空字串 substring 全命中
7. log_workout 的 commit 沒接 IntegrityError（併發同名 create_missing 會漏 raw error；log_set/create_exercise 都有 rollback 處理）
8. template 以名稱解析但 Template.name 無 unique——同名課表隨機掛一個
9. `date.today()` 用 server 本地時區（F7 部署時若 UTC 會日期錯位——部署前確認）
10. 已知不一致（F8 範圍）：MCP 噸位含自體重、heatmap 還是 None——F8 接線時要對齊

**清理類**
- mcp `_validation_message` 抄自 errors.py 且已 drift（missing → "required" 沒帶過來）→ 公開共用
- `_metric_out` 手刻 dict、BodyMetricOut 變死碼 → model_validate().model_dump()
- `_exercise_index`（Python lower）vs `find_by_name`（SQL lower，ASCII-only）兩套解析語意不一致 → 抽共用 normalize
- mcp query_workouts 直接 `session.query(Exercise)` 違反 CLAUDE.md「MCP tools 重用 services」邊界；N+1（每 workout 一次 get_active_sets）→ 一次 in_ 查詢
- `_exercise_label` 與 _suggest 的「zh en」格式兩處硬編；「未分類」/0.9 magic number；UnknownExerciseError 未進 error registry（future REST 曝露會 500）
- log_body_metrics 可改 Annotated[float, Field(ge=30…)] 讓 fastmcp 統一驗證，刪手動 try/except
- tests/test_mcp.py session_factory 與 conftest db_session 重複 bootstrap → 併進 conftest
- main.py middleware 硬編 "/mcp" 字串與 mount path 耦合（改 mount 要同步改兩處——至少加註）

## 做到一半 / 已知未修
- review verify＋修復未做（上面全部）；acceptance-verifier 未跑；**feature_list F6 維持 failing**
- claude CLI 的 lift-log MCP 註冊在 local scope（`claude mcp remove lift-log` 可清）；port 8137 的背景 server 收工時已停
- F2–F5 真機最終確認仍留待 Ryan（手機實開：記錄＋課表＋飛航離線）

## 驗證指令
- `uv run pytest`（92 passed）；`uv run ruff check .`；server：`uv run uvicorn app.main:app_factory --factory --port 8137`（demo DB：先設 `LIFTLOG_DB=./liftlog_connector_demo.db`）
- connector 快驗：`claude mcp list` 應顯示 lift-log ✔ Connected（server 要先起）
