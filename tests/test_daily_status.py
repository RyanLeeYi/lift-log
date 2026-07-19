"""daily_status：當日狀態（PRD R9）——精力／睡眠評分＋描述，同日覆蓋、休息日可記。"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.mcp import create_mcp
from app.models import DailyStatus
from app.schemas import DailyStatusIn
from app.services.daily_status import list_daily_status, upsert_daily_status

# ---------- service ----------


def test_upsert_creates_with_default_today(db_session: Session) -> None:
    row, created = upsert_daily_status(db_session, DailyStatusIn(energy=4))
    assert created is True
    assert row.date == date.today()
    assert row.energy == 4
    assert row.sleep_quality is None
    assert row.note is None


def test_upsert_same_day_overwrites_single_row(db_session: Session) -> None:
    day = date(2026, 7, 10)
    upsert_daily_status(db_session, DailyStatusIn(date=day, energy=2))
    row, created = upsert_daily_status(
        db_session, DailyStatusIn(date=day, energy=4, sleep_quality=3, note="睡得不錯")
    )
    assert created is False
    assert (row.energy, row.sleep_quality, row.note) == (4, 3, "睡得不錯")
    assert len(list(db_session.scalars(select(DailyStatus)))) == 1


def test_list_filters_range_sorted(db_session: Session) -> None:
    for day, energy in [(date(2026, 7, 1), 3), (date(2026, 7, 8), 5), (date(2026, 7, 15), 2)]:
        upsert_daily_status(db_session, DailyStatusIn(date=day, energy=energy))
    rows = list_daily_status(db_session, start=date(2026, 7, 2), end=date(2026, 7, 15))
    assert [(r.date, r.energy) for r in rows] == [(date(2026, 7, 8), 5), (date(2026, 7, 15), 2)]


def test_schema_rejects_out_of_range_scores() -> None:
    with pytest.raises(ValidationError):
        DailyStatusIn(energy=0)
    with pytest.raises(ValidationError):
        DailyStatusIn(energy=6)
    with pytest.raises(ValidationError):
        DailyStatusIn(energy=3, sleep_quality=0)
    with pytest.raises(ValidationError):
        DailyStatusIn(energy=3, sleep_quality=6)


# ---------- REST ----------


class TestDailyStatusApi:
    def test_requires_token(self, anon_client: TestClient) -> None:
        assert anon_client.get("/api/daily-status").status_code == 401
        assert anon_client.post("/api/daily-status", json={"energy": 3}).status_code == 401

    def test_post_creates_201_then_same_day_overwrites_200(self, client: TestClient) -> None:
        """休息日可記：不需要任何 workout 存在。"""
        first = client.post("/api/daily-status", json={"date": "2026-07-10", "energy": 3})
        assert first.status_code == 201

        second = client.post(
            "/api/daily-status",
            json={"date": "2026-07-10", "energy": 5, "sleep_quality": 4, "note": "精神好"},
        )
        assert second.status_code == 200
        rows = client.get("/api/daily-status").json()
        assert [(r["date"], r["energy"], r["sleep_quality"], r["note"]) for r in rows] == [
            ("2026-07-10", 5, 4, "精神好")
        ]

    def test_get_filters_range(self, client: TestClient) -> None:
        for day, energy in [("2026-07-01", 3), ("2026-07-08", 5)]:
            client.post("/api/daily-status", json={"date": day, "energy": energy})
        rows = client.get("/api/daily-status?start=2026-07-05&end=2026-07-31").json()
        assert [(r["date"], r["energy"]) for r in rows] == [("2026-07-08", 5)]

    def test_post_out_of_range_returns_400(self, client: TestClient) -> None:
        assert client.post("/api/daily-status", json={"energy": 0}).status_code == 400
        assert client.post("/api/daily-status", json={"energy": 6}).status_code == 400
        assert (
            client.post("/api/daily-status", json={"energy": 3, "sleep_quality": 9}).status_code
            == 400
        )
        assert client.post("/api/daily-status", json={}).status_code == 400

    def test_delete_removes_the_day_hard(self, client: TestClient) -> None:
        """F18：DELETE 某日狀態＝硬刪，之後 GET 不再有那天。"""
        client.post("/api/daily-status", json={"date": "2026-07-10", "energy": 3})
        client.post("/api/daily-status", json={"date": "2026-07-11", "energy": 4})
        resp = client.delete("/api/daily-status/2026-07-10")
        assert resp.status_code == 204
        dates = [r["date"] for r in client.get("/api/daily-status").json()]
        assert dates == ["2026-07-11"]  # 只刪那天

    def test_delete_then_re_add_same_date_ok(self, client: TestClient) -> None:
        """F18：硬刪後可重記同一天（硬刪不會像軟刪撞 UNIQUE(date)）。"""
        client.post("/api/daily-status", json={"date": "2026-07-10", "energy": 3})
        assert client.delete("/api/daily-status/2026-07-10").status_code == 204
        again = client.post("/api/daily-status", json={"date": "2026-07-10", "energy": 5})
        assert again.status_code == 201
        assert client.get("/api/daily-status").json()[0]["energy"] == 5

    def test_delete_nonexistent_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/api/daily-status/2099-01-01")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}


# ---------- MCP ----------


@pytest.fixture()
def mcp_server(session_factory: sessionmaker) -> FastMCP:
    return create_mcp(session_factory, token="test-token")


def _structured(result) -> dict:
    import json

    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_mcp_log_and_get_daily_status(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        logged = _structured(
            await client.call_tool(
                "log_daily_status",
                {"energy": 4, "sleep_quality": 3, "note": "腿有點痠", "date": "2026-07-10"},
            )
        )
        fetched = _structured(
            await client.call_tool(
                "get_daily_status", {"start_date": "2026-07-01", "end_date": "2026-07-31"}
            )
        )
    assert logged["energy"] == 4
    statuses = fetched["statuses"]
    assert [(s["date"], s["energy"], s["sleep_quality"], s["note"]) for s in statuses] == [
        ("2026-07-10", 4, 3, "腿有點痠")
    ]
    with session_factory() as session:
        assert session.query(DailyStatus).count() == 1


@pytest.mark.asyncio
async def test_mcp_log_daily_status_out_of_range_error_contract(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        result = _structured(await client.call_tool("log_daily_status", {"energy": 9}))
    assert "error" in result
    with session_factory() as session:
        assert session.query(DailyStatus).count() == 0


@pytest.mark.asyncio
async def test_interview_prompt_mentions_daily_status_tool(mcp_server: FastMCP) -> None:
    """R9：引導式問答問完當日狀態後要用 log_daily_status 寫入（不再以 note 附註替代）。"""
    async with Client(mcp_server) as client:
        prompt = await client.get_prompt("log-workout-interview", {})
    text = prompt.messages[0].content.text
    assert "log_daily_status" in text
