"""body_metrics：體重體脂 SSOT（PRD R6 的資料層；F6 先建模型與 service 供 MCP tools 用）。"""

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BodyMetric, Exercise
from app.schemas import BodyMetricIn, LogSetIn, LogWorkoutIn
from app.services.body_metrics import latest_weight, list_body_metrics, upsert_body_metric
from app.services.workouts import log_workout


def test_upsert_creates_row_with_default_today(db_session: Session) -> None:
    row = upsert_body_metric(db_session, BodyMetricIn(weight_kg=101.6))
    assert row.date == date.today()
    assert row.weight_kg == 101.6
    assert row.body_fat_pct is None


def test_upsert_same_day_overwrites_single_row(db_session: Session) -> None:
    day = date(2026, 7, 10)
    upsert_body_metric(db_session, BodyMetricIn(date=day, weight_kg=101.6))
    row = upsert_body_metric(db_session, BodyMetricIn(date=day, weight_kg=100.9, body_fat_pct=24.5))

    assert row.weight_kg == 100.9
    assert row.body_fat_pct == 24.5
    assert len(list(db_session.scalars(select(BodyMetric)))) == 1


def test_list_body_metrics_filters_range_sorted(db_session: Session) -> None:
    samples = [(date(2026, 7, 1), 102.0), (date(2026, 7, 8), 101.0), (date(2026, 7, 15), 100.5)]
    for day, weight in samples:
        upsert_body_metric(db_session, BodyMetricIn(date=day, weight_kg=weight))

    rows = list_body_metrics(db_session, start=date(2026, 7, 2), end=date(2026, 7, 15))
    assert [(r.date, r.weight_kg) for r in rows] == [
        (date(2026, 7, 8), 101.0),
        (date(2026, 7, 15), 100.5),
    ]


def test_latest_weight_returns_most_recent_or_none(db_session: Session) -> None:
    assert latest_weight(db_session) is None
    upsert_body_metric(db_session, BodyMetricIn(date=date(2026, 7, 1), weight_kg=102.0))
    upsert_body_metric(db_session, BodyMetricIn(date=date(2026, 7, 15), weight_kg=100.5))
    assert latest_weight(db_session) == 100.5


def test_schema_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        BodyMetricIn(weight_kg=29.9)
    with pytest.raises(ValidationError):
        BodyMetricIn(weight_kg=300.1)
    with pytest.raises(ValidationError):
        BodyMetricIn(weight_kg=100, body_fat_pct=0)
    with pytest.raises(ValidationError):
        BodyMetricIn(weight_kg=100, body_fat_pct=100)


def test_log_workout_bodyweight_tonnage_uses_latest_weight(db_session: Session) -> None:
    pullup = Exercise(name_zh="引體向上", name_en="Pull-up", muscle_group="背", is_bodyweight=True)
    db_session.add(pullup)
    db_session.commit()
    upsert_body_metric(db_session, BodyMetricIn(weight_kg=100.0))

    summary = log_workout(
        db_session,
        LogWorkoutIn(sets=[LogSetIn(exercise="引體向上", weight_kg=0, reps=6)]),
    )
    assert summary.tonnage_kg == 600.0
