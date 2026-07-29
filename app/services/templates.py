from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.errors import DomainError, NotFoundError
from app.models import Exercise, Template, TemplateExercise, Workout, WorkoutSet
from app.schemas import TemplateCreate, TemplateExerciseOut, TemplateOut


def _pack_weekdays(days: list[int] | None) -> str | None:
    """[1, 3, 5] → "1,3,5"；空／None → NULL（沒排程）。"""
    return ",".join(str(d) for d in days) if days else None


def unpack_weekdays(raw: str | None) -> list[int]:
    """"1,3,5" → [1, 3, 5]；NULL 或髒資料 → []（讀取端永遠拿得到一個清單）。"""
    if not raw:
        return []
    return sorted({int(part) for part in raw.split(",") if part.strip().isdigit()})


def _ensure_unique_name(session: Session, name: str, exclude_id: int | None = None) -> None:
    """MCP log_workout 以名稱解析課表——同名會歧義，寫入前就擋（DB 無 unique 約束，app 層把關）。"""
    query = select(Template.id).where(Template.name == name)
    if exclude_id is not None:
        query = query.where(Template.id != exclude_id)
    if session.scalar(query) is not None:
        raise DomainError("template name already exists")


def _validate_exercise_ids(session: Session, data: TemplateCreate) -> None:
    """課表引用的動作必須全部存在，否則整包拒絕不寫入。"""
    wanted = {item.exercise_id for item in data.exercises}
    found = set(
        session.scalars(select(Exercise.id).where(Exercise.id.in_(wanted)))
    )
    if wanted - found:
        raise DomainError("exercise not found")


def _build_items(data: TemplateCreate) -> list[TemplateExercise]:
    return [
        TemplateExercise(
            position=position,
            exercise_id=item.exercise_id,
            default_sets=item.default_sets,
            rest_hint_seconds=item.rest_hint_seconds,
        )
        for position, item in enumerate(data.exercises, start=1)
    ]


def last_used_by_template(session: Session) -> dict[int, tuple[object, float]]:
    """每份課表最後一次「真的有記東西」的日期與當次總量。

    一次 group by 拿全部，而不是每張卡各查一次——挑課表畫面會一次列出所有課表。
    以 workout 為單位取最後一次：同一天用同一份課表練兩場時，講的是最後那場。
    """
    rows = session.execute(
        select(
            Template.id,
            Workout.date,
            func.sum(WorkoutSet.weight_kg * WorkoutSet.reps),
        )
        # 只留仍然存在的課表（join 而非比數字）——course 刪除時已把歷史的 template_id 清成 NULL，
        # 所以這裡不會撿到孤兒；join 是第二道保險。
        .join(Template, Template.id == Workout.template_id)
        .join(WorkoutSet, WorkoutSet.workout_id == Workout.id)
        .where(WorkoutSet.deleted_at.is_(None))
        .group_by(Workout.id)
        .order_by(Workout.date, Workout.id)
    ).all()
    # 依日期由舊到新掃過去，後面的自然覆蓋前面的＝留下每份課表的最後一次
    latest: dict[int, tuple[object, float]] = {}
    for template_id, day, volume in rows:
        latest[template_id] = (day, round(volume or 0, 1))
    return latest


def _to_out(template: Template, last_used: dict[int, tuple[object, float]] | None = None
            ) -> TemplateOut:
    used = (last_used or {}).get(template.id)
    return TemplateOut(
        id=template.id,
        name=template.name,
        weekdays=unpack_weekdays(template.weekdays),
        last_used_date=used[0] if used else None,
        last_volume_kg=used[1] if used else None,
        exercises=[
            TemplateExerciseOut(
                exercise_id=item.exercise_id,
                position=item.position,
                default_sets=item.default_sets,
                rest_hint_seconds=item.rest_hint_seconds,
                name_zh=item.exercise.name_zh,
                name_en=item.exercise.name_en,
                muscle_group=item.exercise.muscle_group,
                is_bodyweight=item.exercise.is_bodyweight,
            )
            for item in template.exercises
        ],
    )


def _get(session: Session, template_id: int) -> Template:
    template = session.get(
        Template,
        template_id,
        options=[selectinload(Template.exercises).selectinload(TemplateExercise.exercise)],
    )
    if template is None:
        raise NotFoundError()
    return template


def create_template(session: Session, data: TemplateCreate) -> TemplateOut:
    _ensure_unique_name(session, data.name)
    _validate_exercise_ids(session, data)
    template = Template(
        name=data.name,
        weekdays=_pack_weekdays(data.weekdays),
        exercises=_build_items(data),
    )
    session.add(template)
    session.commit()
    return _to_out(_get(session, template.id))


def list_templates(session: Session) -> list[TemplateOut]:
    templates = session.scalars(
        select(Template)
        .options(selectinload(Template.exercises).selectinload(TemplateExercise.exercise))
        .order_by(Template.id)
    )
    last_used = last_used_by_template(session)
    return [_to_out(t, last_used) for t in templates]


def get_template(session: Session, template_id: int) -> TemplateOut:
    return _to_out(_get(session, template_id), last_used_by_template(session))


def update_template(session: Session, template_id: int, data: TemplateCreate) -> TemplateOut:
    """整份取代（名稱＋動作清單）；驗證失敗不留半套（單一 commit）。"""
    template = _get(session, template_id)
    _ensure_unique_name(session, data.name, exclude_id=template_id)
    _validate_exercise_ids(session, data)
    template.name = data.name
    # 「沒帶這個欄位」與「帶了空陣列」是兩件事：前者不動排程，後者才是清掉。
    # 差別在舊版前端（PWA 快取沒更新的那台）送出的 payload 不含 weekdays——
    # 若一律覆蓋，另一台裝置排好的星期會被它悄悄清空（Codex 2026-07-29 P1 指出的情境）。
    if "weekdays" in data.model_fields_set:
        template.weekdays = _pack_weekdays(data.weekdays)
    template.exercises = _build_items(data)
    session.commit()
    return _to_out(_get(session, template_id))


def delete_template(session: Session, template_id: int) -> None:
    """刪課表不影響歷史 workout 本身，但要解除關聯。

    workouts.template_id 是純數值欄（無 FK），而 SQLite 的 INTEGER PRIMARY KEY **會重用**
    被刪掉的最大 id——刪掉最後一份課表再建一份新的，新課表就會拿到同一個數字，
    舊訓練的歷史於是掛到新課表頭上（顯示成它的「上次訓練」，還冠上新名字）。
    比對建立時間擋不住「同一秒內刪了再建」，所以在這裡把關聯清乾淨：
    課表沒了，那個數字本來就已經解讀不出任何東西（Codex 2026-07-29 P2）。

    只載 exercises 供 ORM cascade 用，不載 nested Exercise（這裡用不到）。
    """
    template = session.get(
        Template, template_id, options=[selectinload(Template.exercises)]
    )
    if template is None:
        raise NotFoundError()
    session.execute(
        update(Workout).where(Workout.template_id == template_id).values(template_id=None)
    )
    session.delete(template)
    session.commit()


def set_weekdays(session: Session, template_id: int, days: list[int] | None) -> TemplateOut:
    """只改排程。動作清單不動——課表列表上排星期時不必先讀出整份課表再整包送回。"""
    template = _get(session, template_id)
    template.weekdays = _pack_weekdays(days)
    session.commit()
    return _to_out(_get(session, template_id))
