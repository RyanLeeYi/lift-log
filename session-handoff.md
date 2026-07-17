# Session Handoff
> 最後更新：2026-07-17（第七場：F6 review findings 全數 verify＋修復完成、103 tests 綠；acceptance-verifier 未跑即觸用量門檻收工——**F6 維持 failing**）

## 這個 session 做了（TDD：11 個紅測試先行，修完全綠）

上場留下的 review findings 逐條 verify 後處置完畢：

**正確性（全修，各有測試釘住）**
1. ✅ MCP 冪等：`LogWorkoutIn` 加選填 `client_uuid`（≥8 字元）；每組落庫為 `client_uuid:序號`，重放（含 commit 撞 UNIQUE 的併發路徑）回既有 workout 摘要不重複寫入；tool docstring 指示 LLM 自產並於重試帶同值
2. ✅ create_missing 大小寫變體：unknown 以 lower 去重，只建一筆不留孤兒
3. ✅ `sets=[]`：mcp log_workout 接 ValidationError → `{"error": ...}` 契約
4. ✅ auth 重構為自訂 `SingleTokenVerifier`（bytes compare_digest）：非 ASCII token 乾淨 401（測試用 bytes header 模擬）；擺脫 DebugTokenVerifier「預設全放行」的升級風險
5. ✅ 空白動作名：LogSetIn validator strip＋非空（空名建檔、_suggest 全命中兩個病灶一起除掉）
6. ✅ log_workout commit 接 IntegrityError：rollback 後先試冪等復原、否則 DomainError（不裸拋）
7. ✅ Template 同名：app 層擋（create／update rename 撞名 400、保留自己名字 OK）；`_resolve_template_id` 遇歷史重名回明確 DomainError 不隨機掛（DB 不加 unique 免 migration）
8. ✅ `date.today()` 時區：自家機＝台灣時間可接受，code comment 標注「異地（UTC）部署前要重新確認」→ **F7 部署時要回頭看這條**

**清理類（全處置，除一項有意保留）**
- `validation_message` 公開共用（errors.py，REST/MCP 同一套，missing 分支不再 drift）；UnknownExerciseError 進 error registry
- `normalize_name`／`exercise_label` 抽到 exercises service 共用；`find_by_name` 改 Python 端比對（與 _exercise_index 同語意，除掉 SQLite lower ASCII-only 的兩套結果）
- mcp query_workouts 改走 services（search_exercises＋新增 `get_active_sets_by_workout` 一次 in_ 查詢，N+1 除掉）
- magic numbers 常數化（_SUBSTRING_BOOST、DEFAULT_MUSCLE_GROUP）；main.py `MCP_MOUNT` 常數統一 middleware 與 mount；test_mcp 的 session_factory fixture 併入 conftest
- **有意保留**：log_body_metrics 的手動 try/except（不改 Annotated Field）——改了會讓範圍錯誤走 fastmcp 原生錯誤格式，破壞 `{"error": ...}` 統一契約，現行測試也釘著這個行為

**數字**：103 tests 全過（+11）、覆蓋率 99%、ruff 乾淨

## 下一步（下場開場直接做）
1. **acceptance-verifier 逐條驗收 F6**（PRD R7/R7b × feature_list F6 acceptance；live server + 實際 MCP 呼叫）——過了才把 F6 改 passing 附 evidence
2. F6 passing 後接 F7（Cloudflare Tunnel 部署＋mission-control 收編）；記得 F7 有兩條伏筆：`date.today()` 時區確認、connector 證據已在 `docs/evidence-f6-mcp-connector.txt`
3. F2–F5 真機最終確認仍留待 Ryan（手機實開：記錄＋課表＋飛航離線）

## 做到一半 / 已知未修
- 無做到一半的程式碼——本場改動已完整驗證並 commit
- claude CLI 的 lift-log MCP 註冊在 local scope（`claude mcp remove lift-log` 可清）

## 驗證指令
- `uv run pytest`（103 passed）；`uv run ruff check .`；server：`uv run uvicorn app.main:app_factory --factory --port 8137`（demo DB：先設 `LIFTLOG_DB=./liftlog_connector_demo.db`）
- connector 快驗：`claude mcp list` 應顯示 lift-log ✔ Connected（server 要先起）
