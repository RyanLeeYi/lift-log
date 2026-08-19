from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError, NotFoundError, UnprocessableError
from app.models import EXERCISE_MODE_TIME, Exercise, Workout, WorkoutSet
from app.schemas import ExerciseCreate
from app.services import projection

DEFAULT_MUSCLE_GROUP = "其他"  # F10：自訂動作未填部位時的歸類


def assert_set_matches_mode(
    exercise: Exercise, reps: int | None, duration_seconds: int | None
) -> None:
    """F105 ②：一組的量測欄位必須與動作的 mode 相符，否則 422。

    四種寫法都要擋，不是只擋「帶錯欄位」：
      次數型：reps 必填、duration_seconds 必須為空
      時間型：duration_seconds 必填、reps 必須為空
    兩個都帶或兩個都不帶同樣是 422——放行任一種都會產生「這筆到底算哪種」無解的列。

    共用給 REST（log_set／update_set）、MCP（log_workout）與同步 push 三條寫入路徑；
    三條各寫一份必然漂移，而漂移的那一份會把壞資料寫進最底層。
    """
    if exercise.mode == EXERCISE_MODE_TIME:
        if duration_seconds is None:
            raise UnprocessableError(
                f"「{exercise.name_zh}」是時間型動作，必須提供 duration_seconds"
            )
        if reps is not None:
            raise UnprocessableError(f"「{exercise.name_zh}」是時間型動作，不接受 reps")
        return
    if reps is None:
        raise UnprocessableError(f"「{exercise.name_zh}」是次數型動作，必須提供 reps")
    if duration_seconds is not None:
        raise UnprocessableError(
            f"「{exercise.name_zh}」是次數型動作，不接受 duration_seconds"
        )


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
        mode=data.mode,
    )
    session.add(exercise)
    try:
        projection.record_write(session, "exercise", exercise)
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


def search_exercises(
    session: Session, q: str | None, has_data: bool = False
) -> list[Exercise]:
    query = select(Exercise).order_by(Exercise.id)
    if q:
        pattern = f"%{_escape_like(q)}%"
        query = query.where(
            or_(
                Exercise.name_zh.ilike(pattern, escape="\\"),
                Exercise.name_en.ilike(pattern, escape="\\"),
            )
        )
    if has_data:
        # F39：只回有 ≥1 筆未軟刪組的動作（濾掉沒練過的預設動作）
        query = query.where(
            exists().where(
                WorkoutSet.exercise_id == Exercise.id,
                WorkoutSet.deleted_at.is_(None),
            )
        )
    return list(session.scalars(query))


def last_sets(
    session: Session, exercise_id: int, exclude_workout_id: int | None = None
) -> list[WorkoutSet]:
    """該動作最近一次 workout 的各組（帶入預設值用）；exercise 不存在 → 404。

    exclude_workout_id：排除進行中的 workout，讓「上次」看的是**前一次**訓練而非本次
    （F32——本次已做過同動作時，last-sets 原會回本次那筆並被誤標成上次）。
    """
    if session.get(Exercise, exercise_id) is None:
        raise NotFoundError()
    latest_filters = [WorkoutSet.exercise_id == exercise_id, WorkoutSet.deleted_at.is_(None)]
    if exclude_workout_id is not None:
        latest_filters.append(WorkoutSet.workout_id != exclude_workout_id)
    latest_workout_id = (
        select(WorkoutSet.workout_id)
        .join(Workout, Workout.id == WorkoutSet.workout_id)
        .where(*latest_filters)
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


def last_set_values(
    session: Session, exercise_ids: list[int], exclude_workout_id: int | None = None
) -> dict[int, tuple[float, int | None, int | None]]:
    """一次取多個動作「上次」的代表數值（該動作最近一次訓練的最後一組）。

    今日菜單一次列出整份課表，逐個動作打 last-sets 會是 N 次往返；這裡一次查完。
    回傳 {exercise_id: (weight_kg, reps, duration_seconds)}；查不到的動作不會出現在字典裡。
    F105：時間型動作的 reps 為 None、duration_seconds 有值，呼叫端依此分流顯示。
    """
    if not exercise_ids:
        return {}
    filters = [
        WorkoutSet.exercise_id.in_(exercise_ids),
        WorkoutSet.deleted_at.is_(None),
    ]
    if exclude_workout_id is not None:
        filters.append(WorkoutSet.workout_id != exclude_workout_id)
    rows = session.execute(
        select(
            WorkoutSet.exercise_id,
            WorkoutSet.weight_kg,
            WorkoutSet.reps,
            WorkoutSet.duration_seconds,
        )
        .join(Workout, Workout.id == WorkoutSet.workout_id)
        .where(*filters)
        # 由舊到新掃過去，後面的覆蓋前面的＝每個動作留下最新那次的最後一組
        .order_by(Workout.date, WorkoutSet.workout_id, WorkoutSet.set_number)
    ).all()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}
