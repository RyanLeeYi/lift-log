from datetime import date as date_type

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DbSession, require_token
from app.schemas import (
    SetCreate,
    SetOut,
    SetUpdate,
    WorkoutCreate,
    WorkoutDetailOut,
    WorkoutOut,
)
from app.services import workouts as svc

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.post("/workouts", status_code=status.HTTP_201_CREATED, response_model=WorkoutOut)
def create_workout(data: WorkoutCreate, session: DbSession) -> WorkoutOut:
    return WorkoutOut.model_validate(svc.create_workout(session, data))


@router.get("/workouts", response_model=list[WorkoutOut])
def list_workouts(
    session: DbSession,
    start: date_type | None = None,
    end: date_type | None = None,
) -> list[WorkoutOut]:
    return [WorkoutOut.model_validate(w) for w in svc.list_workouts(session, start, end)]


@router.get("/workouts/{workout_id}", response_model=WorkoutDetailOut)
def get_workout(workout_id: int, session: DbSession) -> WorkoutDetailOut:
    workout = svc.get_workout(session, workout_id)
    return WorkoutDetailOut(
        id=workout.id,
        date=workout.date,
        template_id=workout.template_id,
        note=workout.note,
        created_at=workout.created_at,  # F83：今日菜單的「已練 N 分」
        sets=[SetOut.model_validate(s) for s in svc.get_active_sets(session, workout_id)],
    )


@router.post("/workouts/{workout_id}/sets", response_model=SetOut)
def log_set(
    workout_id: int,
    data: SetCreate,
    response: Response,
    session: DbSession,
) -> SetOut:
    workout_set, created = svc.log_set(session, workout_id, data)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return SetOut.model_validate(workout_set)


@router.patch("/sets/{set_id}", response_model=SetOut)
def update_set(set_id: int, data: SetUpdate, session: DbSession) -> SetOut:
    return SetOut.model_validate(svc.update_set(session, set_id, data))


@router.delete("/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_set(set_id: int, session: DbSession) -> None:
    svc.soft_delete_set(session, set_id)
