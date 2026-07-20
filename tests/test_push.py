"""F31 Web Push：訂閱 upsert、送出/清除失效、排程器、endpoints。webpush 一律 mock，不打網路。"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pywebpush import WebPushException
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import PushSubscription
from app.schemas import PushKeys, PushSubscriptionIn
from app.services import push as svc

SUB_JSON = {
    "endpoint": "https://push.example/abc",
    "keys": {"p256dh": "p256", "auth": "authsecret"},
}


@pytest.fixture(autouse=True)
def _reset_scheduler() -> None:
    # 每個測試前後清掉模組級排程 task，避免跨測試/跨事件迴圈殘留
    svc._rest_task = None
    yield
    svc._rest_task = None


def _sub_in(endpoint: str = "https://push.example/abc", p256dh: str = "p256") -> PushSubscriptionIn:
    return PushSubscriptionIn(endpoint=endpoint, keys=PushKeys(p256dh=p256dh, auth="authsecret"))


def _settings_with_key(tmp_path) -> Settings:
    return Settings(
        token="t",
        db_path=str(tmp_path / "p.db"),
        vapid_private_key="dummy",
        vapid_public_key="pub",
        vapid_subject="mailto:a@b.c",
    )


def test_upsert_inserts_then_updates(db_session: Session) -> None:
    svc.upsert_subscription(db_session, _sub_in())
    rows = db_session.query(PushSubscription).all()
    assert len(rows) == 1 and rows[0].p256dh == "p256"
    svc.upsert_subscription(db_session, _sub_in(p256dh="new"))  # 同 endpoint → 更新不重複
    rows = db_session.query(PushSubscription).all()
    assert len(rows) == 1 and rows[0].p256dh == "new"


def test_send_to_all_no_key_is_noop(session_factory: sessionmaker, tmp_path) -> None:
    s = Settings(token="t", db_path=str(tmp_path / "x.db"))  # 無 vapid_private_key
    assert svc.send_to_all(session_factory, s, "t", "b") == 0


def test_send_to_all_sends_and_prunes_expired(
    session_factory: sessionmaker, tmp_path, monkeypatch
) -> None:
    with session_factory() as ss:
        ss.add(PushSubscription(endpoint="e1", p256dh="p", auth="a"))
        ss.add(PushSubscription(endpoint="e2", p256dh="p", auth="a"))
        ss.commit()

    def fake_send(settings, sub, payload) -> None:
        if sub.endpoint == "e2":  # 模擬訂閱失效
            resp = type("R", (), {"status_code": 410})()
            raise WebPushException("gone", response=resp)

    monkeypatch.setattr(svc, "_send_one", fake_send)
    sent = svc.send_to_all(session_factory, _settings_with_key(tmp_path), "休息結束", "b")
    assert sent == 1  # e1 成功、e2 失效不計
    with session_factory() as ss:
        remaining = [r.endpoint for r in ss.query(PushSubscription).all()]
    assert remaining == ["e1"]  # e2 已清除


def test_scheduler_fires() -> None:
    async def run() -> list:
        fired: list = []

        async def cb() -> None:
            fired.append(1)

        svc.schedule_rest(0.05, cb)
        await asyncio.sleep(0.12)
        return fired

    assert asyncio.run(run()) == [1]


def test_scheduler_cancel_prevents_fire() -> None:
    async def run() -> list:
        fired: list = []

        async def cb() -> None:
            fired.append(1)

        svc.schedule_rest(0.2, cb)
        svc.cancel_rest()
        await asyncio.sleep(0.05)
        return fired

    assert asyncio.run(run()) == []


def test_schedule_supersedes_previous() -> None:
    async def run() -> list:
        fired: list = []

        async def old() -> None:
            fired.append("old")

        async def new() -> None:
            fired.append("new")

        svc.schedule_rest(0.1, old)
        svc.schedule_rest(0.04, new)  # 覆蓋舊的
        await asyncio.sleep(0.2)
        return fired

    assert asyncio.run(run()) == ["new"]


def _client_with(settings: Settings) -> TestClient:
    from app.main import create_app

    c = TestClient(create_app(settings))
    c.headers["Authorization"] = f"Bearer {settings.token}"
    return c


def test_public_key_disabled_without_keys(tmp_path) -> None:
    # 明確傳空金鑰（覆蓋 .env），確保停用狀態可判定
    s = Settings(
        token="t", db_path=str(tmp_path / "d.db"), vapid_private_key="", vapid_public_key=""
    )
    body = _client_with(s).get("/api/push/public-key").json()
    assert body["enabled"] is False and body["key"] == ""


def test_public_key_enabled_with_keys(tmp_path) -> None:
    s = Settings(
        token="t",
        db_path=str(tmp_path / "e.db"),
        vapid_private_key="priv",
        vapid_public_key="PUBKEY",
    )
    body = _client_with(s).get("/api/push/public-key").json()
    assert body["enabled"] is True and body["key"] == "PUBKEY"


def test_subscribe_endpoint(client: TestClient) -> None:
    assert client.post("/api/push/subscribe", json=SUB_JSON).status_code == 204


def test_subscribe_requires_token(anon_client: TestClient) -> None:
    assert anon_client.post("/api/push/subscribe", json=SUB_JSON).status_code == 401


def test_rest_timer_and_cancel_endpoints(client: TestClient) -> None:
    assert client.post("/api/push/rest-timer", json={"seconds": 1}).status_code == 202
    assert client.post("/api/push/rest-timer/cancel").status_code == 204
