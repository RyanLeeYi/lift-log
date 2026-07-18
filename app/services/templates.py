from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import DomainError, NotFoundError
from app.models import Exercise, Template, TemplateExercise
from app.schemas import TemplateCreate, TemplateExerciseOut, TemplateOut


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


def _to_out(template: Template) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        name=template.name,
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
    template = Template(name=data.name, exercises=_build_items(data))
    session.add(template)
    session.commit()
    return _to_out(_get(session, template.id))


def list_templates(session: Session) -> list[TemplateOut]:
    templates = session.scalars(
        select(Template)
        .options(selectinload(Template.exercises).selectinload(TemplateExercise.exercise))
        .order_by(Template.id)
    )
    return [_to_out(t) for t in templates]


def get_template(session: Session, template_id: int) -> TemplateOut:
    return _to_out(_get(session, template_id))


def update_template(session: Session, template_id: int, data: TemplateCreate) -> TemplateOut:
    """整份取代（名稱＋動作清單）；驗證失敗不留半套（單一 commit）。"""
    template = _get(session, template_id)
    _ensure_unique_name(session, data.name, exclude_id=template_id)
    _validate_exercise_ids(session, data)
    template.name = data.name
    template.exercises = _build_items(data)
    session.commit()
    return _to_out(_get(session, template_id))


def delete_template(session: Session, template_id: int) -> None:
    """刪課表不影響歷史 workout（workouts.template_id 為純數值欄，無 FK）。

    只載 exercises 供 ORM cascade 用，不載 nested Exercise（這裡用不到）。
    """
    template = session.get(
        Template, template_id, options=[selectinload(Template.exercises)]
    )
    if template is None:
        raise NotFoundError()
    session.delete(template)
    session.commit()
