"""MCP server（PRD R7/R7b）：tools 一律重用 services，不重寫查詢邏輯。

auth：與 REST 同一個 token 來源（settings.token），常數時間比較；
/mcp 掛載走不到 APIRouter 的 require_token，由 SingleTokenVerifier 把關。
"""

import secrets
from datetime import date as date_type

from fastmcp import FastMCP
from fastmcp.server.auth import TokenVerifier
from mcp.server.auth.provider import AccessToken
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app.errors import DomainError, NotFoundError, UnknownExerciseError, validation_message
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
from app.services import stats as stats_svc
from app.services import templates as templates_svc
from app.services import workouts as workouts_svc
from app.services.exercises import exercise_label

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


def _metric_out(row: BodyMetric) -> dict:
    return BodyMetricOut.model_validate(row).model_dump(mode="json", exclude={"id"})


def _status_out(row: DailyStatus) -> dict:
    return DailyStatusOut.model_validate(row).model_dump(mode="json", exclude={"id"})


class SingleTokenVerifier(TokenVerifier):
    """單人系統唯一 token 的 verifier。

    自訂而不用 DebugTokenVerifier：後者預設 validate 全放行，升級或重構漏掉參數會
    靜默變成無認證。bytes 比較讓非 ASCII token 也走常數時間比對回 401，不會 TypeError。
    """

    def __init__(self, token: str) -> None:
        super().__init__()
        self._expected = token.encode()

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token.encode(), self._expected):
            return None
        return AccessToken(token=token, client_id="lift-log", scopes=[])


def create_mcp(session_factory: sessionmaker, token: str) -> FastMCP:
    mcp = FastMCP(name="lift-log", auth=SingleTokenVerifier(token))

    @mcp.tool
    def query_workouts(
        start_date: date_type, end_date: date_type, exercise: str | None = None
    ) -> dict:
        """查詢區間內的訓練紀錄（含每組明細）；exercise 可用中文或英文名過濾。"""
        with session_factory() as session:
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
                                "reps": s.reps,
                                "rpe": s.rpe,
                                "rest_seconds": s.rest_seconds,
                            }
                            for s in sets
                        ],
                    }
                )
            return {"workouts": workouts}

    @mcp.tool
    def get_progress(exercise: str) -> dict:
        """該動作的進步曲線：每次訓練的最大重量與次數（中文或英文名皆可）。"""
        with session_factory() as session:
            try:
                return stats_svc.get_progress(session, exercise).model_dump(mode="json")
            except NotFoundError:
                return {"error": "exercise not found"}

    @mcp.tool
    def list_templates() -> dict:
        """列出所有課表（名稱、動作順序、預設組數）。"""
        with session_factory() as session:
            return {
                "templates": [t.model_dump() for t in templates_svc.list_templates(session)]
            }

    @mcp.tool
    def get_body_metrics(
        start_date: date_type | None = None, end_date: date_type | None = None
    ) -> dict:
        """查詢體重／體脂紀錄（區間可省略＝全部），依日期排序。"""
        with session_factory() as session:
            rows = body_metrics_svc.list_body_metrics(session, start_date, end_date)
            return {"metrics": [_metric_out(row) for row in rows]}

    @mcp.tool
    def log_workout(
        sets: list[LogSetIn],
        date: date_type | None = None,
        template: str | None = None,
        note: str | None = None,
        create_missing: bool = False,
        client_uuid: str | None = None,
    ) -> dict:
        """代主人記錄一次訓練（整包寫入或整包拒絕）。

        動作名雙語比對；比對不到時整包拒絕並回相近建議，
        經主人同意後帶 create_missing=true 才自動建新動作。
        每次記錄請自產一個 client_uuid（≥8 字元）；timeout 重試帶同值
        即冪等，不會重複寫入。
        """
        with session_factory() as session:
            try:
                summary = workouts_svc.log_workout(
                    session,
                    LogWorkoutIn(
                        sets=sets,
                        date=date,
                        template=template,
                        note=note,
                        create_missing=create_missing,
                        client_uuid=client_uuid,
                    ),
                )
            except ValidationError as exc:
                return {"error": validation_message(exc)}
            except UnknownExerciseError as exc:
                return {
                    "error": "unknown exercise",
                    "unknown": exc.unknown,
                    "suggestions": exc.suggestions,
                }
            except DomainError as exc:
                return {"error": exc.message}
            return summary.model_dump(mode="json")

    @mcp.tool
    def log_body_metrics(
        weight_kg: float, body_fat_pct: float | None = None, date: date_type | None = None
    ) -> dict:
        """代主人記錄體重（kg）與體脂（%）；同日重送為覆蓋更新。"""
        with session_factory() as session:
            try:
                data = BodyMetricIn(date=date, weight_kg=weight_kg, body_fat_pct=body_fat_pct)
            except ValidationError as exc:
                return {"error": validation_message(exc)}
            row, _created = body_metrics_svc.upsert_body_metric(session, data)
            return _metric_out(row)

    @mcp.tool
    def get_daily_status(
        start_date: date_type | None = None, end_date: date_type | None = None
    ) -> dict:
        """查詢當日狀態紀錄（精力／睡眠評分＋描述；區間可省略＝全部），依日期排序。"""
        with session_factory() as session:
            rows = daily_status_svc.list_daily_status(session, start_date, end_date)
            return {"statuses": [_status_out(row) for row in rows]}

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
        with session_factory() as session:
            try:
                data = DailyStatusIn(
                    date=date, energy=energy, sleep_quality=sleep_quality, note=note
                )
            except ValidationError as exc:
                return {"error": validation_message(exc)}
            row, _created = daily_status_svc.upsert_daily_status(session, data)
            return _status_out(row)

    @mcp.prompt(name="log-workout-interview")
    def log_workout_interview() -> str:
        """引導式問答記錄一次訓練：逐題問完、覆述確認後才一次寫入。"""
        return INTERVIEW_PROMPT

    return mcp
