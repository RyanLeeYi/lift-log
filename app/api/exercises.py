from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DbSession, require_token
from app.schemas import (
    ExerciseCreate,
    ExerciseHistoryOut,
    ExerciseLastSet,
    ExerciseOut,
    LastSetOut,
    SetOut,
)
from app.services import exercises as svc
from app.services.history import exercise_history, months_ago

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


def _parse_date(value: str) -> date:
    # 自解析而非讓 FastAPI 轉型：格式錯要走本端點契約的 422，而非全域 handler 的 400
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid date: {value}") from exc


@router.post("/exercises", status_code=status.HTTP_201_CREATED, response_model=ExerciseOut)
def create_exercise(data: ExerciseCreate, session: DbSession) -> ExerciseOut:
    return ExerciseOut.model_validate(svc.create_exercise(session, data))


@router.get("/exercises", response_model=list[ExerciseOut])
def search_exercises(
    session: DbSession, q: str | None = None, has_data: bool = False
) -> list[ExerciseOut]:
    # F39：has_data=true 只回有紀錄的動作（首頁動作表現瀏覽用）
    return [ExerciseOut.model_validate(e) for e in svc.search_exercises(session, q, has_data)]


@router.get("/exercises/{exercise_id}/history", response_model=ExerciseHistoryOut)
def history(
    exercise_id: int,
    session: DbSession,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query(alias="to")] = None,
) -> ExerciseHistoryOut:
    # 省略 → 預設近 3 個日曆月（to＝今天、from＝今天回推 3 個月）；固定檔位由前端換算成起訖日期
    to_date = _parse_date(to) if to else date.today()
    from_date = _parse_date(from_) if from_ else months_ago(to_date, 3)
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="from > to")
    return exercise_history(session, exercise_id, from_date, to_date)


@router.get("/exercises/last-set-values", response_model=list[ExerciseLastSet])
def last_set_values(
    session: DbSession,
    ids: str = Query(description="逗號分隔的 exercise id"),
    exclude_workout: int | None = None,
) -> list[ExerciseLastSet]:
    """F83 今日菜單：一次取多個動作的「上次」代表值（逐個打 last-sets 會是 N 次往返）。"""
    wanted = [int(part) for part in ids.split(",") if part.strip().isdigit()]
    found = svc.last_set_values(session, wanted, exclude_workout_id=exclude_workout)
    return [
        ExerciseLastSet(exercise_id=key, weight_kg=value[0], reps=value[1])
        for key, value in found.items()
    ]


@router.get("/exercises/{exercise_id}/last-sets", response_model=list[LastSetOut])
def last_sets(
    exercise_id: int, session: DbSession, exclude_workout: int | None = None
) -> list[LastSetOut]:
    # exclude_workout：排除進行中的 workout → 「上次」看前一次訓練，不是本次（F32）
    return [
        # F84：帶上 workout 日期給 logger 的「上次提示卡」——同一批組本來就同一天，
        # 從關聯取比再打一次 workouts 便宜
        LastSetOut(**SetOut.model_validate(s).model_dump(), workout_date=s.workout.date)
        for s in svc.last_sets(session, exercise_id, exclude_workout_id=exclude_workout)
    ]
