"""F80 排程：今天排到哪些課表、本週練了幾天。

「本週練了幾天」刻意**由 sets 推導**而不是另存欄位——存一份就會有兩個真相，
而補記、刪組、改日期都會讓存下來的那份悄悄過期。查詢成本是一個 group by，遠比對帳便宜。
"""

from datetime import date as date_type
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Template, Workout, WorkoutSet
from app.schemas import LastWorkout, ScheduledTemplate, ScheduleTodayOut
from app.services.settings import weekly_target_days
from app.services.templates import unpack_weekdays


def week_start(day: date_type) -> date_type:
    """本週的週一（ISO：週一是一週的第一天）。"""
    return day - timedelta(days=day.isoweekday() - 1)


def trained_days(session: Session, start: date_type, end: date_type) -> set[date_type]:
    """區間內「有未刪除的組」的日期集合。空 workout（開了沒記）不算練。"""
    rows = session.scalars(
        select(Workout.date)
        .join(WorkoutSet, WorkoutSet.workout_id == Workout.id)
        .where(
            Workout.date >= start,
            Workout.date <= end,
            WorkoutSet.deleted_at.is_(None),
        )
        .group_by(Workout.date)
    )
    return set(rows)


def templates_for_weekday(session: Session, weekday: int) -> list[ScheduledTemplate]:
    """該星期排到的課表，依課表既有順序（id）。一天可以有多份。"""
    templates = session.scalars(
        select(Template)
        .options(selectinload(Template.exercises))
        .order_by(Template.id)
    )
    out: list[ScheduledTemplate] = []
    for template in templates:
        if weekday not in unpack_weekdays(template.weekdays):
            continue
        out.append(
            ScheduledTemplate(
                id=template.id,
                name=template.name,
                exercise_count=len(template.exercises),
                set_count=sum(item.default_sets for item in template.exercises),
            )
        )
    return out


def last_workout(session: Session, before: date_type) -> LastWorkout | None:
    """最近一次「真的有記東西」的訓練（含當天稍早的）。

    以 workout 為單位而不是以日期：同一天練兩場時，卡片講的是最後那一場。
    課表名稱走 template_id 反查——課表可能已被刪除（workouts.template_id 無 FK），查不到就留 None。
    """
    row = session.execute(
        select(
            Workout.id,
            Workout.date,
            Workout.template_id,
            func.count(WorkoutSet.id),
            func.sum(WorkoutSet.weight_kg * WorkoutSet.reps),
        )
        .join(WorkoutSet, WorkoutSet.workout_id == Workout.id)
        .where(Workout.date <= before, WorkoutSet.deleted_at.is_(None))
        .group_by(Workout.id)
        .order_by(Workout.date.desc(), Workout.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    _, day, template_id, set_count, volume = row
    name = None
    if template_id is not None:
        name = session.scalar(select(Template.name).where(Template.id == template_id))
    return LastWorkout(
        date=day,
        template_name=name,
        set_count=set_count,
        volume_kg=round(volume or 0, 1),
    )


def today(session: Session, today_date: date_type | None = None) -> ScheduleTodayOut:
    day = today_date or date_type.today()
    start = week_start(day)
    done = trained_days(session, start, start + timedelta(days=6))
    return ScheduleTodayOut(
        date=day,
        weekday=day.isoweekday(),
        templates=templates_for_weekday(session, day.isoweekday()),
        weekly_target_days=weekly_target_days(session),
        week_done_days=len(done),
        week_days=[(start + timedelta(days=i)) in done for i in range(7)],
        last_workout=last_workout(session, day),
    )

