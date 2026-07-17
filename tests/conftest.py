from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.models import Base

TEST_TOKEN = "test-token"


@pytest.fixture()
def db_session(tmp_path: Path) -> Iterator[Session]:
    """service 層測試用：獨立 SQLite，不經 HTTP。"""
    engine = make_engine(str(tmp_path / "svc.db"))
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


@pytest.fixture()
def anon_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(token=TEST_TOKEN, db_path=str(tmp_path / "test.db"))
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(anon_client: TestClient) -> TestClient:
    anon_client.headers["Authorization"] = f"Bearer {TEST_TOKEN}"
    return anon_client


@pytest.fixture()
def exercise_id(client: TestClient) -> int:
    resp = client.post(
        "/api/exercises",
        json={"name_zh": "深蹲", "name_en": "Squat", "muscle_group": "腿", "is_bodyweight": False},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def make_set_payload(exercise_id: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "client_uuid": "11111111-1111-1111-1111-111111111111",
        "exercise_id": exercise_id,
        "set_number": 1,
        "weight_kg": 80.0,
        "reps": 8,
    }
    return {**payload, **overrides}
