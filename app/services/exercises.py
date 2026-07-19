from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError, NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.schemas import ExerciseCreate

DEFAULT_MUSCLE_GROUP = "其他"  # F10：自訂動作未填部位時的歸類


def create_exercise(session: Session, data: ExerciseCreate) -> Exercise:
    # F10 選填欄位補齊：英文名留空 → 鏡射中文名（避開 name_en unique 非空欄位的 nullable 重建、
    # 且 EN 檢視不會顯示空白）；部位留空 → 預設「其他」
    name_en = data.name_en or data.name_zh
    muscle_group = data.muscle_group or DEFAULT_MUSCLE_GROUP

    # 正規化重複前置檢查（zh 或 en 任一衝突擋下），與 find_by_name/log_workout 名稱解析同語意——
    # 純靠 DB unique 只擋精確字串，會放行大小寫/空白變體並造成之後名稱解析歧義
    for candidate in (data.name_zh, name_en):
        if find_by_name(session, candidate) is not None:
            raise DomainError("exercise name already exists")

    exercise = Exercise(
        name_zh=data.name_zh,
        name_en=name_en,
        muscle_group=muscle_group,
        is_bodyweight=data.is_bodyweight,
    )
    session.add(exercise)
    try:
        session.commit()
    except IntegrityError as exc:  # DB unique 當後盾（並發或非正規化漏網）
        session.rollback()
        raise DomainError("exercise name already exists") from exc
    session.refresh(exercise)
    return exercise


def normalize_name(name: str) -> str:
    """雙語動作名的統一正規化——所有名稱解析（find_by_name、log_workout index）共用同一語意。"""
    return name.strip().lower()


def exercise_label(exercise: Exercise) -> str:
    """對外顯示的雙語標籤（MCP 輸出與建議清單共用同一格式）。"""
    return f"{exercise.name_zh} {exercise.name_en}"


def find_by_name(session: Session, name: str) -> Exercise | None:
    """雙語名稱精確比對；MCP 與 progress 的動作解析入口。

    Python 端比對而非 SQL lower()（SQLite 的 lower 只處理 ASCII）——與 log_workout
    的 _exercise_index 同語意，非 ASCII 大小寫不會兩套結果。動作表量級小，全載無妨。
    """
    target = normalize_name(name)
    for exercise in session.scalars(select(Exercise)):
        if target in (normalize_name(exercise.name_zh), normalize_name(exercise.name_en)):
            return exercise
    return None


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_exercises(session: Session, q: str | None) -> list[Exercise]:
    query = select(Exercise).order_by(Exercise.id)
    if q:
        pattern = f"%{_escape_like(q)}%"
        query = query.where(
            or_(
                Exercise.name_zh.ilike(pattern, escape="\\"),
                Exercise.name_en.ilike(pattern, escape="\\"),
            )
        )
    return list(session.scalars(query))


def last_sets(session: Session, exercise_id: int) -> list[WorkoutSet]:
    """該動作最近一次 workout 的各組（帶入預設值用）；exercise 不存在 → 404。"""
    if session.get(Exercise, exercise_id) is None:
        raise NotFoundError()
    latest_workout_id = (
        select(WorkoutSet.workout_id)
        .join(Workout, Workout.id == WorkoutSet.workout_id)
        .where(WorkoutSet.exercise_id == exercise_id, WorkoutSet.deleted_at.is_(None))
        .order_by(Workout.date.desc(), Workout.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return list(
        session.scalars(
            select(WorkoutSet)
            .where(
                WorkoutSet.workout_id == latest_workout_id,
                WorkoutSet.exercise_id == exercise_id,
                WorkoutSet.deleted_at.is_(None),
            )
            .order_by(WorkoutSet.set_number)
        )
    )
