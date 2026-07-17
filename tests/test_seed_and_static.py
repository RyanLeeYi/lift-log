"""F2 後端驗收：動作庫 seed（冪等）與靜態 PWA 掛載。"""

from fastapi.testclient import TestClient


class TestSeed:
    def test_seed_populates_about_30_bilingual_exercises(self, client: TestClient) -> None:
        from app.seed import seed_exercises

        factory = client.app.state.session_factory  # type: ignore[attr-defined]
        with factory() as session:
            created = seed_exercises(session)
        assert created >= 25

        resp = client.get("/api/exercises")
        exercises = resp.json()
        assert len(exercises) >= 25
        assert all(e["name_zh"] and e["name_en"] and e["muscle_group"] for e in exercises)
        names_en = {e["name_en"].lower() for e in exercises}
        assert {"squat", "bench press", "deadlift"} <= names_en
        assert any(e["is_bodyweight"] for e in exercises)  # 引體向上等自體重動作

    def test_seed_is_idempotent(self, client: TestClient) -> None:
        from app.seed import seed_exercises

        factory = client.app.state.session_factory  # type: ignore[attr-defined]
        with factory() as session:
            first = seed_exercises(session)
        with factory() as session:
            second = seed_exercises(session)
        assert first >= 25
        assert second == 0  # 重跑不新增

        count = len(client.get("/api/exercises").json())
        assert count == first


class TestStatic:
    def test_root_serves_pwa_index_without_token(self, anon_client: TestClient) -> None:
        resp = anon_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "lift-log" in resp.text

    def test_manifest_served(self, anon_client: TestClient) -> None:
        resp = anon_client.get("/manifest.webmanifest")
        assert resp.status_code == 200
