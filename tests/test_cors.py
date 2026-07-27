"""F61 ⑧：CORS 只開給 Capacitor 原生殼的 origin。

打包版 app 的 WebView origin 是 `https://localhost`（Capacitor 8 Android 預設）
或舊版的 `capacitor://localhost`，與公開站不同源，因此需要 CORS。
白名單以外的 origin 一律不得放行——`allow_origins=["*"]` 會讓任何網頁帶著
使用者的瀏覽器打這個 API。
"""

from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN

CAPACITOR_ORIGINS = ["https://localhost", "capacitor://localhost"]


def test_capacitor_origin_gets_cors_header(client: TestClient) -> None:
    for origin in CAPACITOR_ORIGINS:
        resp = client.get("/api/exercises", headers={"Origin": origin})
        assert resp.status_code == 200, origin
        assert resp.headers.get("access-control-allow-origin") == origin, origin


def test_unknown_origin_is_not_allowed(client: TestClient) -> None:
    resp = client.get("/api/exercises", headers={"Origin": "https://evil.example"})
    # 請求本身仍會被處理（CORS 是瀏覽器端的強制），但不得回放行標頭
    assert "access-control-allow-origin" not in resp.headers


def test_no_wildcard_origin(client: TestClient) -> None:
    resp = client.get("/api/exercises", headers={"Origin": "https://localhost"})
    assert resp.headers.get("access-control-allow-origin") != "*"


def test_preflight_allows_authorization_and_write_methods(anon_client: TestClient) -> None:
    """PATCH/DELETE + Authorization 會觸發預檢，預檢本身不帶 token。"""
    for method in ("POST", "PATCH", "DELETE"):
        resp = anon_client.options(
            "/api/exercises",
            headers={
                "Origin": "https://localhost",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert resp.status_code == 200, method
        assert resp.headers.get("access-control-allow-origin") == "https://localhost"
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert method in allowed, (method, allowed)
        allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
        assert "authorization" in allow_headers


def test_health_still_open_without_origin(client: TestClient) -> None:
    """回歸：沒有 Origin 標頭的一般請求（web 版同源）行為不變。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers
    assert client.get("/api/exercises").status_code == 200
    assert TEST_TOKEN  # token fixture 仍然是必要的
