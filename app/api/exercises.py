from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, require_token
from app.schemas import ExerciseCreate, ExerciseOut, SetOut
from app.services import exercises as svc

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.post("/exercises", status_code=status.HTTP_201_CREATED, response_model=ExerciseOut)
def create_exercise(data: ExerciseCreate, session: DbSession) -> ExerciseOut:
    return ExerciseOut.model_validate(svc.create_exercise(session, data))


@router.get("/exercises", response_model=list[ExerciseOut])
def search_exercises(session: DbSession, q: str | None = None) -> list[ExerciseOut]:
    return [ExerciseOut.model_validate(e) for e in svc.search_exercises(session, q)]


@router.get("/exercises/{exercise_id}/last-sets", response_model=list[SetOut])
def last_sets(
    exercise_id: int, session: DbSession, exclude_workout: int | None = None
) -> list[SetOut]:
    # exclude_workout：排除進行中的 workout → 「上次」看前一次訓練，不是本次（F32）
    return [
        SetOut.model_validate(s)
        for s in svc.last_sets(session, exercise_id, exclude_workout_id=exclude_workout)
    ]
