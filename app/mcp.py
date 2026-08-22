"""MCP server（PRD R7/R7b、F147）：tools 一律重用 services，不重寫查詢邏輯。

auth：接受兩種 token 來源，都在同一個 verifier 判定——
legacy token（settings.token，`secrets.compare_digest`）維持既有單人共用 DB；
user MCP token（F147，`app/services/mcp_tokens.resolve_token`）驗證後只能開該 user
的 data DB，路徑完全由 user context 推導，tool 參數不得指定 user 或 DB。
/mcp 掛載走不到 APIRouter 的 require_token，由 verifier 把關。
"""

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date as date_type
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.dependencies import get_access_token
from mcp.server.auth.provider import AccessToken
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.control_models import User
from app.db import UserDataUnavailable, canonical_user_db_path, make_engine
from app.errors import (
    DomainError,
    NotFoundError,
    UnknownExerciseError,
    UnprocessableError,
    validation_message,
)
from app.models import BodyMetric, DailyStatus
from app.schemas import (
    BodyMetricIn,
    BodyMetricOut,
    DailyStatusIn,
    DailyStatusOut,
    LogSetIn,
    LogWorkoutIn,
)
from app.services import body_metrics as body_metrics_svc
from app.services import daily_status as daily_status_svc
from app.services import exercises as exercises_svc
from app.services import mcp_tokens as mcp_tokens_svc
from app.services import stats as stats_svc
from app.services import templates as templates_svc
from app.services import workouts as workouts_svc
from app.services.exercises import exercise_label

LEGACY_CLIENT_ID = "lift-log"

INTERVIEW_PROMPT = """\
你是健身紀錄助手。用逐題問答引導使用者口述今天的訓練，全部確認後才寫入：

1. 今天練了哪些動作？（一次列完）
2. 逐一動作追問：每組重量（kg）？次數？共幾組？各組 RPE（1-10，可略）？
   自體重動作（引體向上等）重量填「額外負重」，無負重填 0。
3. 問當日狀態：精力 1-5？睡眠品質 1-5？想補充的描述？
4. 把整理好的內容「全部」覆述給使用者確認：動作×組數×重量×次數＋當日狀態
   （精力／睡眠／描述）。任何一項使用者更正就更新後再覆述一次。
5. 確認無誤後「一次」呼叫 log_workout 寫入全部組數——不要邊問邊寫；
   動作名比對不到時，把 suggestions 唸給使用者選，或經同意後帶 create_missing=true；
   自產一個 client_uuid（≥8 字元），timeout 重試帶同值避免重複寫入。
6. 同樣在確認之後，才以 log_daily_status 寫入當日狀態（energy 必填、
   sleep_quality 與 note 選填）——未經覆述確認的狀態不寫。
7. 寫入成功後覆述摘要（總組數、總噸位、當日狀態）。
"""


_INPROCESS_USER_ID: ContextVar[str | None] = ContextVar("liftlog_inprocess_user_id", default=None)
"""F163：in-process 呼叫（`run_tool`）綁定的 user id。

`/mcp` 走 access token，in-process 沒有 token（`get_access_token()` 回 None），
少了這個綁定就會落回 legacy 共用 DB。tool 參數不得帶 user id 或 DB 路徑——身分
只從這裡來。
"""


class _DataUnavailable(Exception):
    """user 的 data DB 打不開（非 active、DB 不存在等）→ tool 回 {"error": "data unavailable"}。"""


def _metric_out(row: BodyMetric) -> dict:
    return BodyMetricOut.model_validate(row).model_dump(mode="json", exclude={"id"})


def _status_out(row: DailyStatus) -> dict:
    return DailyStatusOut.model_validate(row).model_dump(mode="json", exclude={"id"})


READ_SCOPE = "read"
WRITE_SCOPE = "write"
READ_ONLY_ERROR = {"error": "this MCP token is read-only; ask the owner for a writable token"}


def _write_denied() -> dict | None:
    """F158⑤：唯讀 token 呼叫寫入類 tool 時回可讀錯誤。in-process 測試與 legacy 路徑
    沒有 access token（None）或帶 WRITE_SCOPE，皆放行。"""
    access_token = get_access_token()
    if access_token is None or WRITE_SCOPE in access_token.scopes:
        return None
    return READ_ONLY_ERROR


class DomainTokenVerifier(TokenVerifier):
    """legacy 共用 token 或 F147 user MCP token 皆可通過；成功時 client_id 帶身分。

    自訂而不用 DebugTokenVerifier：後者預設 validate 全放行，升級或重構漏掉參數會
    靜默變成無認證。bytes 比較讓非 ASCII token 也走常數時間比對回 401，不會 TypeError。
    """

    def __init__(self, token: str, control_session_factory: sessionmaker[Session] | None) -> None:
        super().__init__()
        self._expected = token.encode()
        self._control_session_factory = control_session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        # F149：token 未設＝demo 模式關閉。少了這道，空字串會比中空的 _expected，
        # 送一顆空 token 就換到 LEGACY_CLIENT_ID 的全庫存取。
        if self._expected and secrets.compare_digest(token.encode(), self._expected):
            return AccessToken(
                token=token, client_id=LEGACY_CLIENT_ID, scopes=[READ_SCOPE, WRITE_SCOPE]
            )
        if self._control_session_factory is None:
            return None
        with self._control_session_factory() as control:
            row = mcp_tokens_svc.resolve_token(control, token)
            if row is None:
                return None
            user_id, read_only = row.user.id, row.read_only
        # F158⑤：權限跟著 token 走。scopes 是 AccessToken 現成的位置；唯讀 token 拿不到
        # WRITE_SCOPE，寫入類 tool 在入口就拒絕。legacy 共用 token 維持可寫（見上）。
        scopes = [READ_SCOPE] if read_only else [READ_SCOPE, WRITE_SCOPE]
        return AccessToken(token=token, client_id=user_id, scopes=scopes)


@contextmanager
def _user_session(
    control_session_factory: sessionmaker[Session],
    settings: Settings | None,
    user_id: str,
) -> Iterator[Session]:
    """開這個 user 專屬 data DB 的 session（F147 路徑推導，F163 共用）。

    user 不存在／非 active／DB 檔不在都收斂成 `_DataUnavailable`，由 tool 轉成
    `{"error": "data unavailable"}`，不外洩檔案路徑。
    """
    if settings is None:
        raise _DataUnavailable
    with control_session_factory() as control:
        user = control.get(User, user_id)
    if user is None or user.status != "active":
        raise _DataUnavailable
    try:
        path = canonical_user_db_path(settings.user_data_dir, user.id, user.data_db_name)
    except UserDataUnavailable as exc:
        raise _DataUnavailable from exc
    if not path.is_file():
        raise _DataUnavailable

    engine = make_engine(str(path))
    try:
        with sessionmaker(bind=engine)() as session:
            yield session
    finally:
        engine.dispose()


async def run_tool(mcp: FastMCP, user_id: str, name: str, arguments: dict) -> Any:
    """F163：以 user 身分在 server 內部呼叫與 /mcp 完全相同的那組 tool。

    刻意不另建 tool 表：名稱與 schema 就是 `/mcp` 暴露的那份，寫入也走同一段
    `app/services/`（因此同樣進 sync change log）。回傳 tool 的 structured 結果
    （dict），未知 tool 由 FastMCP 拋 NotFoundError。
    """
    token = _INPROCESS_USER_ID.set(user_id)
    try:
        result = await mcp.call_tool(name, arguments)
    finally:
        _INPROCESS_USER_ID.reset(token)
    return result.structured_content


def create_mcp(
    session_factory: sessionmaker,
    token: str,
    control_session_factory: sessionmaker[Session] | None = None,
    settings: Settings | None = None,
) -> FastMCP:
    mcp = FastMCP(name="lift-log", auth=DomainTokenVerifier(token, control_session_factory))

    @contextmanager
    def domain_session() -> Iterator[Session]:
        """本次請求要用哪個 DB（F147）：八個 tool 共用同一份身分解析。

        `control_session_factory is None` 時維持既有 legacy 單 token 行為（in-process
        測試靠這條路徑，且 in-memory Client 不走 auth 層，`get_access_token()` 一律
        回 None）。legacy client_id 沿用建 server 時傳入的共用 `session_factory`；
        user MCP token 才會依 access token 的 client_id（=user id）解析專屬 DB，
        用完 dispose 這顆臨時 engine。
        """
        # F163：in-process 綁定優先於 access token 與 legacy fallback——否則登入中的
        # web/app 使用者會讀寫到 legacy 共用 DB。
        inprocess_user_id = _INPROCESS_USER_ID.get()
        if inprocess_user_id is not None:
            if control_session_factory is None or settings is None:
                raise _DataUnavailable
            with _user_session(control_session_factory, settings, inprocess_user_id) as session:
                yield session
            return

        if control_session_factory is None:
            with session_factory() as session:
                yield session
            return

        access_token = get_access_token()
        if access_token is None or access_token.client_id == LEGACY_CLIENT_ID:
            with session_factory() as session:
                yield session
            return

        with _user_session(control_session_factory, settings, access_token.client_id) as session:
            yield session

    @mcp.tool
    def query_workouts(
        start_date: date_type, end_date: date_type, exercise: str | None = None
    ) -> dict:
        """查詢區間內的訓練紀錄（含每組明細）；exercise 可用中文或英文名過濾。"""
        try:
            with domain_session() as session:
                wanted_id: int | None = None
                if exercise is not None:
                    found = exercises_svc.find_by_name(session, exercise)
                    if found is None:
                        return {"error": "exercise not found"}
                    wanted_id = found.id

                names = {
                    e.id: exercise_label(e) for e in exercises_svc.search_exercises(session, None)
                }
                listed = workouts_svc.list_workouts(session, start_date, end_date)
                sets_by_workout = workouts_svc.get_active_sets_by_workout(
                    session, [w.id for w in listed]
                )
                workouts = []
                for workout in listed:
                    sets = sets_by_workout[workout.id]
                    if wanted_id is not None:
                        sets = [s for s in sets if s.exercise_id == wanted_id]
                        if not sets:
                            continue
                    workouts.append(
                        {
                            "id": workout.id,
                            "date": workout.date.isoformat(),
                            "note": workout.note,
                            "sets": [
                                {
                                    "exercise": names[s.exercise_id],
                                    "set_number": s.set_number,
                                    "weight_kg": s.weight_kg,
                                    # F105：次數型回 reps、時間型回 duration_seconds，
                                    # 另一個為 null——讀的人靠「哪個有值」就知道是哪種
                                    "reps": s.reps,
                                    "duration_seconds": s.duration_seconds,
                                    "rpe": s.rpe,
                                    "rest_seconds": s.rest_seconds,
                                }
                                for s in sets
                            ],
                        }
                    )
                return {"workouts": workouts}
        except _DataUnavailable:
            return {"error": "data unavailable"}

    @mcp.tool
    def get_progress(exercise: str) -> dict:
        """該動作的進步曲線（中文或英文名皆可）。

        次數型動作回每次訓練的最大重量與該重量的次數；
        時間型動作（棒式這類做幾秒）改回每次訓練**最長那組的秒數**（duration_seconds）。
        """
        try:
            with domain_session() as session:
                try:
                    return stats_svc.get_progress(session, exercise).model_dump(mode="json")
                except NotFoundError:
                    return {"error": "exercise not found"}
        except _DataUnavailable:
            return {"error": "data unavailable"}

    @mcp.tool
    def list_templates() -> dict:
        """列出所有課表（名稱、動作順序、預設組數）。"""
        try:
            with domain_session() as session:
                return {
                    "templates": [t.model_dump() for t in templates_svc.list_templates(session)]
                }
        except _DataUnavailable:
            return {"error": "data unavailable"}

    @mcp.tool
    def get_body_metrics(
        start_date: date_type | None = None, end_date: date_type | None = None
    ) -> dict:
        """查詢體重／體脂紀錄（區間可省略＝全部），依日期排序。"""
        try:
            with domain_session() as session:
                rows = body_metrics_svc.list_body_metrics(session, start_date, end_date)
                return {"metrics": [_metric_out(row) for row in rows]}
        except _DataUnavailable:
            return {"error": "data unavailable"}

    @mcp.tool
    def log_workout(
        sets: list[LogSetIn],
        date: date_type | None = None,
        template: str | None = None,
        note: str | None = None,
        create_missing: bool = False,
        client_uuid: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """代主人記錄一次訓練（整包寫入或整包拒絕）。

        每一組依動作的計量方式擇一填：次數型填 reps、時間型（棒式這類做幾秒）填
        duration_seconds。填錯或兩個都填會整包拒絕；時間型的 weight_kg 是負重，
        沒有負重就填 0。回傳的 tonnage_kg 只算次數型，時間型看 duration_seconds
        ——兩個數字並列，不要相加。

        動作名雙語比對；比對不到時整包拒絕並回相近建議，
        經主人同意後帶 create_missing=true 才自動建新動作。
        每次記錄請自產一個 client_uuid（≥8 字元）；timeout 重試帶同值
        即冪等，不會重複寫入。

        dry_run=true 只回「將新增／將略過／將衝突」摘要與前 5 筆預覽，
        零寫入、零 change log——寫入前先給主人確認用（F152）。
        """
        if denied := _write_denied():
            return denied
        try:
            with domain_session() as session:
                try:
                    payload = LogWorkoutIn(
                        sets=sets,
                        date=date,
                        template=template,
                        note=note,
                        create_missing=create_missing,
                        client_uuid=client_uuid,
                        dry_run=dry_run,
                    )
                    # dry_run 的分派與 app/api/workouts.py 同一套：service 的
                    # log_workout 簽名不動（共用契約），只是換一個入口函式。
                    summary = (
                        workouts_svc.dry_run_log_workout(session, payload)
                        if dry_run
                        else workouts_svc.log_workout(session, payload)
                    )
                except ValidationError as exc:
                    return {"error": validation_message(exc)}
                except UnknownExerciseError as exc:
                    return {
                        "error": "unknown exercise",
                        "unknown": exc.unknown,
                        "suggestions": exc.suggestions,
                    }
                except UnprocessableError as exc:
                    return {"error": exc.message}
                except DomainError as exc:
                    return {"error": exc.message}
                return summary.model_dump(mode="json")
        except _DataUnavailable:
            return {"error": "data unavailable"}

    @mcp.tool
    def log_body_metrics(
        weight_kg: float, body_fat_pct: float | None = None, date: date_type | None = None
    ) -> dict:
        """代主人記錄體重（kg）與體脂（%）；同日重送為覆蓋更新。"""
        if denied := _write_denied():
            return denied
        try:
            with domain_session() as session:
                try:
                    data = BodyMetricIn(date=date, weight_kg=weight_kg, body_fat_pct=body_fat_pct)
                except ValidationError as exc:
                    return {"error": validation_message(exc)}
                row, _created = body_metrics_svc.upsert_body_metric(session, data)
                return _metric_out(row)
        except _DataUnavailable:
            return {"error": "data unavailable"}

    @mcp.tool
    def get_daily_status(
        start_date: date_type | None = None, end_date: date_type | None = None
    ) -> dict:
        """查詢當日狀態紀錄（精力／睡眠評分＋描述；區間可省略＝全部），依日期排序。"""
        try:
            with domain_session() as session:
                rows = daily_status_svc.list_daily_status(session, start_date, end_date)
                return {"statuses": [_status_out(row) for row in rows]}
        except _DataUnavailable:
            return {"error": "data unavailable"}

    @mcp.tool
    def log_daily_status(
        energy: int,
        sleep_quality: int | None = None,
        note: str | None = None,
        date: date_type | None = None,
    ) -> dict:
        """代主人記錄當日狀態（energy 1–5 必填、sleep_quality 1–5 與 note 選填）。

        休息日也可記，不依附訓練；同日重送為覆蓋更新。
        """
        if denied := _write_denied():
            return denied
        try:
            with domain_session() as session:
                try:
                    data = DailyStatusIn(
                        date=date, energy=energy, sleep_quality=sleep_quality, note=note
                    )
                except ValidationError as exc:
                    return {"error": validation_message(exc)}
                row, _created = daily_status_svc.upsert_daily_status(session, data)
                return _status_out(row)
        except _DataUnavailable:
            return {"error": "data unavailable"}

    @mcp.prompt(name="log-workout-interview")
    def log_workout_interview() -> str:
        """引導式問答記錄一次訓練：逐題問完、覆述確認後才一次寫入。"""
        return INTERVIEW_PROMPT

    return mcp
