"""body_metrics：體重體脂 SSOT（PRD R6；F6 建模型與 service，F8 補 REST 與 heatmap 接線）。"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BodyMetric, Exercise
from app.schemas import BodyMetricIn, LogSetIn, LogWorkoutIn
from app.services.body_metrics import latest_weight, list_body_metrics, upsert_body_metric
from app.services.workouts import log_workout


def test_upsert_creates_row_with_default_today(db_session: Session) -> None:
    row, created = upsert_body_metric(db_session, BodyMetricIn(weight_kg=101.6))
    assert created is True
    assert row.date == date.today()
    assert row.weight_kg == 101.6
    assert row.body_fat_pct is None


def test_upsert_same_day_overwrites_single_row(db_session: Session) -> None:
    day = date(2026, 7, 10)
    upsert_body_metric(db_session, BodyMetricIn(date=day, weight_kg=101.6))
    row, created = upsert_body_metric(
        db_session, BodyMetricIn(date=day, weight_kg=100.9, body_fat_pct=24.5)
    )

    assert created is False
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


def test_upsert_race_on_first_insert_recovers_to_overwrite(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """併發同日首寫撞 date UNIQUE：不得裸拋 500，要復原為「同日覆蓋」語意。"""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as SASession

    day = date(2026, 7, 10)
    real_commit = db_session.commit
    raced = {"done": False}

    def racing_commit() -> None:
        if not raced["done"]:
            raced["done"] = True
            # 模擬輸掉競賽：另一請求先寫入同日列，自己的 INSERT 撞 UNIQUE
            other = SASession(bind=db_session.get_bind())
            other.add(BodyMetric(date=day, weight_kg=99.0))
            other.commit()
            other.close()
            db_session.rollback()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        real_commit()

    monkeypatch.setattr(db_session, "commit", racing_commit)
    row, created = upsert_body_metric(
        db_session, BodyMetricIn(date=day, weight_kg=100.0, body_fat_pct=24.0)
    )

    assert created is False
    assert row.weight_kg == 100.0
    assert row.body_fat_pct == 24.0
    monkeypatch.undo()
    assert len(list(db_session.scalars(select(BodyMetric)))) == 1  # 一天一筆不變量保住


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


class TestBodyMetricsApi:
    """F8：REST GET/POST /api/body-metrics（同日覆蓋）。"""

    def test_requires_token(self, anon_client: TestClient) -> None:
        assert anon_client.get("/api/body-metrics").status_code == 401
        assert anon_client.post("/api/body-metrics", json={"weight_kg": 100}).status_code == 401

    def test_post_creates_201_then_same_day_overwrites_200(self, client: TestClient) -> None:
        first = client.post(
            "/api/body-metrics", json={"date": "2026-07-10", "weight_kg": 101.6}
        )
        assert first.status_code == 201
        assert first.json()["weight_kg"] == 101.6

        second = client.post(
            "/api/body-metrics",
            json={"date": "2026-07-10", "weight_kg": 100.9, "body_fat_pct": 24.5},
        )
        assert second.status_code == 200
        assert second.json()["weight_kg"] == 100.9
        assert second.json()["body_fat_pct"] == 24.5

        rows = client.get("/api/body-metrics").json()
        assert [(r["date"], r["weight_kg"]) for r in rows] == [("2026-07-10", 100.9)]

    def test_get_filters_range_sorted(self, client: TestClient) -> None:
        for day, weight in [("2026-07-01", 102.0), ("2026-07-08", 101.0), ("2026-07-15", 100.5)]:
            client.post("/api/body-metrics", json={"date": day, "weight_kg": weight})
        rows = client.get("/api/body-metrics?start=2026-07-02&end=2026-07-15").json()
        assert [(r["date"], r["weight_kg"]) for r in rows] == [
            ("2026-07-08", 101.0),
            ("2026-07-15", 100.5),
        ]

    def test_post_out_of_range_returns_400(self, client: TestClient) -> None:
        assert client.post("/api/body-metrics", json={"weight_kg": 29.9}).status_code == 400
        assert client.post("/api/body-metrics", json={}).status_code == 400

    def test_delete_removes_the_day_hard(self, client: TestClient) -> None:
        """F17：DELETE 某日體重＝硬刪，之後 GET 不再有那天。"""
        client.post("/api/body-metrics", json={"date": "2026-07-10", "weight_kg": 100.0})
        client.post("/api/body-metrics", json={"date": "2026-07-11", "weight_kg": 99.0})
        resp = client.delete("/api/body-metrics/2026-07-10")
        assert resp.status_code == 204
        dates = [r["date"] for r in client.get("/api/body-metrics").json()]
        assert dates == ["2026-07-11"]  # 只刪那天，其餘不動

    def test_delete_then_re_add_same_date_ok(self, client: TestClient) -> None:
        """F17：硬刪後可重記同一天（硬刪不會像軟刪撞 UNIQUE(date)）。"""
        client.post("/api/body-metrics", json={"date": "2026-07-10", "weight_kg": 100.0})
        assert client.delete("/api/body-metrics/2026-07-10").status_code == 204
        again = client.post("/api/body-metrics", json={"date": "2026-07-10", "weight_kg": 88.0})
        assert again.status_code == 201  # 視為全新一筆
        assert client.get("/api/body-metrics").json()[0]["weight_kg"] == 88.0

    def test_delete_nonexistent_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/api/body-metrics/2099-01-01")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}

    def test_calendar_bodyweight_tonnage_uses_latest_weight(self, client: TestClient) -> None:
        """F8 接線：heatmap 的自體重噸位改用最新體重（F3 只計負重的行為在此升級）。"""
        exercise = client.post(
            "/api/exercises",
            json={
                "name_zh": "引體向上",
                "name_en": "Pull-up",
                "muscle_group": "背",
                "is_bodyweight": True,
            },
        ).json()
        workout = client.post("/api/workouts", json={"date": "2026-07-10"}).json()
        client.post(
            f"/api/workouts/{workout['id']}/sets",
            json={
                "client_uuid": "cal-bw-0001",
                "exercise_id": exercise["id"],
                "set_number": 1,
                "weight_kg": 0,
                "reps": 6,
            },
        )
        client.post("/api/body-metrics", json={"date": "2026-07-12", "weight_kg": 100.0})

        days = client.get("/api/stats/calendar?year=2026&month=7").json()["days"]
        assert days["2026-07-10"] == 600.0


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


class TestBodyMetricBounds:
    """F58：資料起訖端點——前端用它判斷哪些區間檔位有意義。"""

    def test_empty_db_returns_nulls(self, client: TestClient) -> None:
        body = client.get("/api/body-metrics/range").json()
        assert body == {"weight_first": None, "fat_first": None, "last": None}

    def test_weight_only_leaves_fat_first_null(self, client: TestClient) -> None:
        client.post("/api/body-metrics", json={"date": "2026-05-01", "weight_kg": 100.0})
        client.post("/api/body-metrics", json={"date": "2026-07-01", "weight_kg": 99.0})

        body = client.get("/api/body-metrics/range").json()
        assert body == {"weight_first": "2026-05-01", "fat_first": None, "last": "2026-07-01"}

    def test_fat_first_is_earliest_row_with_fat(self, client: TestClient) -> None:
        client.post("/api/body-metrics", json={"date": "2026-05-01", "weight_kg": 100.0})
        client.post(
            "/api/body-metrics",
            json={"date": "2026-06-15", "weight_kg": 99.5, "body_fat_pct": 24.0},
        )
        client.post("/api/body-metrics", json={"date": "2026-07-01", "weight_kg": 99.0})

        body = client.get("/api/body-metrics/range").json()
        assert body == {
            "weight_first": "2026-05-01",
            "fat_first": "2026-06-15",
            "last": "2026-07-01",
        }
