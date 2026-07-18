"""MCP server（PRD R7/R7b）：tools 重用 services；/mcp 掛載與 auth 走 HTTP 驗證。"""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from sqlalchemy.orm import sessionmaker

from app.mcp import create_mcp
from app.models import BodyMetric, Exercise, Workout, WorkoutSet
from app.schemas import BodyMetricIn, LogSetIn, LogWorkoutIn, TemplateCreate, TemplateExerciseIn
from app.services.body_metrics import upsert_body_metric
from app.services.templates import create_template
from app.services.workouts import log_workout

EXPECTED_TOOLS = {
    "query_workouts",
    "get_progress",
    "list_templates",
    "get_body_metrics",
    "log_workout",
    "log_body_metrics",
}


@pytest.fixture()
def mcp_server(session_factory: sessionmaker) -> FastMCP:
    with session_factory() as session:
        session.add(Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿"))
        session.commit()
    return create_mcp(session_factory, token="test-token")


def _structured(result) -> dict:
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_mcp_lists_expected_tools_and_prompt(mcp_server: FastMCP) -> None:
    async with Client(mcp_server) as client:
        tool_names = {tool.name for tool in await client.list_tools()}
        prompt_names = {prompt.name for prompt in await client.list_prompts()}
    assert EXPECTED_TOOLS <= tool_names
    assert "log-workout-interview" in prompt_names


@pytest.mark.asyncio
async def test_mcp_log_workout_writes_and_returns_summary(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "log_workout",
            {
                "sets": [
                    {"exercise": "深蹲", "weight_kg": 80, "reps": 8},
                    {"exercise": "squat", "weight_kg": 80, "reps": 8},
                ]
            },
        )
    payload = _structured(result)
    assert payload["sets_count"] == 2
    assert payload["tonnage_kg"] == 1280
    with session_factory() as session:
        assert session.query(WorkoutSet).count() == 2


@pytest.mark.asyncio
async def test_mcp_log_workout_unknown_exercise_rejects_with_suggestions(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "log_workout",
            {"sets": [{"exercise": "深躦", "weight_kg": 80, "reps": 8}]},
        )
    payload = _structured(result)
    assert payload["error"] == "unknown exercise"
    assert payload["unknown"] == ["深躦"]
    assert "深蹲 Squat" in payload["suggestions"]
    with session_factory() as session:
        assert session.query(Workout).count() == 0


@pytest.mark.asyncio
async def test_mcp_log_body_metrics_and_get_body_metrics(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        logged = await client.call_tool(
            "log_body_metrics", {"weight_kg": 101.6, "date": "2026-07-10"}
        )
        fetched = await client.call_tool(
            "get_body_metrics", {"start_date": "2026-07-01", "end_date": "2026-07-31"}
        )
    assert _structured(logged)["weight_kg"] == 101.6
    metrics = _structured(fetched)["metrics"]
    assert [(m["date"], m["weight_kg"]) for m in metrics] == [("2026-07-10", 101.6)]
    with session_factory() as session:
        assert session.query(BodyMetric).count() == 1


@pytest.mark.asyncio
async def test_mcp_log_body_metrics_out_of_range_rejected(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        result = await client.call_tool("log_body_metrics", {"weight_kg": 500})
    assert "error" in _structured(result)
    with session_factory() as session:
        assert session.query(BodyMetric).count() == 0


@pytest.mark.asyncio
async def test_mcp_query_workouts_and_progress(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    with session_factory() as session:
        upsert_body_metric(session, BodyMetricIn(date=date(2026, 7, 9), weight_kg=100))
        log_workout(
            session,
            LogWorkoutIn(
                sets=[
                    LogSetIn(exercise="深蹲", weight_kg=80, reps=8),
                    LogSetIn(exercise="深蹲", weight_kg=85, reps=6),
                ],
                date=date(2026, 7, 10),
            ),
        )

    async with Client(mcp_server) as client:
        workouts = await client.call_tool(
            "query_workouts",
            {"start_date": "2026-07-01", "end_date": "2026-07-31", "exercise": "squat"},
        )
        progress = await client.call_tool("get_progress", {"exercise": "深蹲"})

    listed = _structured(workouts)["workouts"]
    assert len(listed) == 1
    assert listed[0]["date"] == "2026-07-10"
    assert [(s["exercise"], s["weight_kg"], s["reps"]) for s in listed[0]["sets"]] == [
        ("深蹲 Squat", 80.0, 8),
        ("深蹲 Squat", 85.0, 6),
    ]

    points = _structured(progress)["points"]
    assert points == [{"date": "2026-07-10", "top_weight_kg": 85.0, "reps": 6}]


@pytest.mark.asyncio
async def test_mcp_log_workout_empty_sets_returns_error_contract(
    mcp_server: FastMCP,
) -> None:
    """sets=[] 要回 {"error": ...}，不得裸拋 ValidationError 違反工具契約。"""
    async with Client(mcp_server) as client:
        result = await client.call_tool("log_workout", {"sets": []})
    assert "error" in _structured(result)


@pytest.mark.asyncio
async def test_mcp_log_workout_client_uuid_replay_idempotent(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    """LLM timeout 重試帶同 client_uuid：不得重複寫入。"""
    args = {
        "sets": [{"exercise": "深蹲", "weight_kg": 80, "reps": 8}],
        "client_uuid": "llm-retry-01",
    }
    async with Client(mcp_server) as client:
        first = _structured(await client.call_tool("log_workout", args))
        second = _structured(await client.call_tool("log_workout", args))
    assert second["workout_id"] == first["workout_id"]
    with session_factory() as session:
        assert session.query(WorkoutSet).count() == 1


@pytest.mark.asyncio
async def test_mcp_get_progress_unknown_exercise(mcp_server: FastMCP) -> None:
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_progress", {"exercise": "nope"})
    assert _structured(result)["error"] == "exercise not found"


@pytest.mark.asyncio
async def test_mcp_list_templates(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    with session_factory() as session:
        exercise_id = session.query(Exercise).one().id
        items = [TemplateExerciseIn(exercise_id=exercise_id, default_sets=3)]
        create_template(session, TemplateCreate(name="練腿日", exercises=items))
    async with Client(mcp_server) as client:
        result = await client.call_tool("list_templates", {})
    templates = _structured(result)["templates"]
    assert [t["name"] for t in templates] == ["練腿日"]
    assert templates[0]["exercises"][0]["name_zh"] == "深蹲"


@pytest.mark.asyncio
async def test_mcp_list_templates_includes_rest_hint(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    """F12（PRD R10）：MCP 課表輸出帶 rest_hint_seconds，agent 才能討論休息配置。"""
    with session_factory() as session:
        exercise_id = session.query(Exercise).one().id
        items = [
            TemplateExerciseIn(exercise_id=exercise_id, default_sets=3, rest_hint_seconds=90)
        ]
        create_template(session, TemplateCreate(name="背日", exercises=items))
    async with Client(mcp_server) as client:
        result = await client.call_tool("list_templates", {})
    templates = _structured(result)["templates"]
    assert templates[0]["exercises"][0]["rest_hint_seconds"] == 90


def test_http_mcp_requires_token(anon_client: TestClient) -> None:
    resp = anon_client.post("/mcp/", json={})
    assert resp.status_code == 401
    resp = anon_client.post(
        "/mcp/", json={}, headers={"Authorization": "Bearer wrong-token"}
    )
    assert resp.status_code == 401


def test_http_mcp_non_ascii_token_rejected_as_401(anon_client: TestClient) -> None:
    """非 ASCII token 必須乾淨回 401，不得因 compare_digest TypeError 變 500。"""
    resp = anon_client.post(
        "/mcp/", json={}, headers={b"Authorization": "Bearer 密碼token".encode()}
    )
    assert resp.status_code == 401


def test_http_mcp_correct_token_passes_auth(client: TestClient) -> None:
    # 不驗完整 MCP 握手（in-memory client 已覆蓋工具行為），只驗 token 通過 auth 層
    resp = client.post("/mcp/", json={})
    assert resp.status_code != 401


def test_http_mcp_without_trailing_slash_reaches_mcp(client: TestClient) -> None:
    """connector 給的 URL 是 /mcp（無斜線），不得掉進靜態檔 mount 變 405。"""
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "1.0"},
        },
    }
    resp = client.post(
        "/mcp", json=init, headers={"Accept": "application/json, text/event-stream"}
    )
    assert resp.status_code == 200

    bad_token = client.post(
        "/mcp",
        json=init,
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer wrong-token",
        },
    )
    assert bad_token.status_code == 401
