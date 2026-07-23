from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DbSession, require_token
from app.schemas import ExerciseCreate, ExerciseHistoryOut, ExerciseOut, SetOut
from app.services import exercises as svc
from app.services.history import exercise_history

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.post("/exercises", status_code=status.HTTP_201_CREATED, response_model=ExerciseOut)
def create_exercise(data: ExerciseCreate, session: DbSession) -> ExerciseOut:
    return ExerciseOut.model_validate(svc.create_exercise(session, data))


@router.get("/exercises", response_model=list[ExerciseOut])
def search_exercises(session: DbSession, q: str | None = None) -> list[ExerciseOut]:
    return [ExerciseOut.model_validate(e) for e in svc.search_exercises(session, q)]


@router.get("/exercises/{exercise_id}/history", response_model=ExerciseHistoryOut)
def history(
    exercise_id: int,
    session: DbSession,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query(alias="to")] = None,
) -> ExerciseHistoryOut:
    # 省略 → 預設近 3 個月（to＝今天、from＝今天−3 個月）；固定檔位由前端換算成起訖日期
    to_date = to or date.today()
    from_date = from_ or (to_date - timedelta(days=90))
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="from > to")
    return exercise_history(session, exercise_id, from_date, to_date)


@router.get("/exercises/{exercise_id}/last-sets", response_model=list[SetOut])
def last_sets(
    exercise_id: int, session: DbSession, exclude_workout: int | None = None
) -> list[SetOut]:
    # exclude_workout：排除進行中的 workout → 「上次」看前一次訓練，不是本次（F32）
    return [
        SetOut.model_validate(s)
        for s in svc.last_sets(session, exercise_id, exclude_workout_id=exclude_workout)
    ]
