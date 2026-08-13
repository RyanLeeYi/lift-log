from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.deps import DbSession, require_domain_auth
from app.errors import DomainError, UnknownExerciseError
from app.schemas import (
    LogWorkoutIn,
    LogWorkoutSummary,
    SetCreate,
    SetOut,
    SetUpdate,
    WorkoutCreate,
    WorkoutDetailOut,
    WorkoutOut,
)
from app.services import workouts as svc

router = APIRouter(prefix="/api", dependencies=[Depends(require_domain_auth)])


def _batch_validation_errors(exc: ValidationError) -> list[dict[str, int | str | None]]:
    errors: list[dict[str, int | str | None]] = []
    for error in exc.errors():
        location = error["loc"]
        errors.append(
            {
                "index": next((part for part in location if isinstance(part, int)), None),
                "field": next(
                    (str(part) for part in reversed(location) if isinstance(part, str)), "body"
                ),
                "message": error["msg"],
            }
        )
    return errors


def _unknown_exercise_errors(
    data: LogWorkoutIn, unknown: list[str]
) -> list[dict[str, int | str | None]]:
    unknown_names = {name.lower() for name in unknown}
    return [
        {"index": index, "field": "exercise", "message": "unknown exercise"}
        for index, item in enumerate(data.sets)
        if item.exercise.lower() in unknown_names
    ]


def _batch_domain_error(exc: DomainError) -> dict[str, str | int | None]:
    return {
        "index": None,
        "field": "template" if exc.message.startswith("template") else "body",
        "message": exc.message,
    }


@router.post("/workouts", status_code=status.HTTP_201_CREATED, response_model=WorkoutOut)
def create_workout(data: WorkoutCreate, session: DbSession) -> WorkoutOut:
    return WorkoutOut.model_validate(svc.create_workout(session, data))


@router.post(
    "/workouts/batch", status_code=status.HTTP_201_CREATED, response_model=LogWorkoutSummary
)
def batch_log_workout(
    payload: dict[str, Any], session: DbSession
) -> LogWorkoutSummary | JSONResponse:
    try:
        data = LogWorkoutIn.model_validate(payload)
    except ValidationError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "validation failed", "errors": _batch_validation_errors(exc)},
        )
    try:
        return svc.log_workout(session, data)
    except UnknownExerciseError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "validation failed",
                "errors": _unknown_exercise_errors(data, exc.unknown),
                "suggestions": exc.suggestions,
            },
        )
    except DomainError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "validation failed", "errors": [_batch_domain_error(exc)]},
        )


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
        ended_at=workout.ended_at,  # F91：還原時據此拒絕續接已結束的訓練
        sets=[SetOut.model_validate(s) for s in svc.get_active_sets(session, workout_id)],
    )


@router.delete("/workouts/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workout(workout_id: int, session: DbSession) -> None:
    """F92 ⑤：清掉沒記任何組的空 workout；有組（含軟刪除）一律 409。"""
    svc.delete_workout(session, workout_id)


@router.post("/workouts/{workout_id}/end", response_model=WorkoutOut)
def end_workout(workout_id: int, session: DbSession) -> WorkoutOut:
    """F91：標記訓練結束。冪等；不影響 sets 寫入（離線佇列的組仍要補得進來）。"""
    return WorkoutOut.model_validate(svc.end_workout(session, workout_id))


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
