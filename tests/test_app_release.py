"""F67 ②：app 版自我更新用的版本查詢與 APK 供檔。

兩個端點都要 legacy token 或已驗證 Android access token；未登入者不可公開下載。
下載器是我們自己寫的，帶 Authorization header 的成本為零。
"""

from pathlib import Path

from fastapi.testclient import TestClient

APK_BYTES = b"PK\x03\x04fake-apk-content-for-tests"


def _write_release(tmp_path: Path, version: int = 64) -> Path:
    """建一個假的發佈目錄：APK ＋ 版本資訊。"""
    release_dir = tmp_path / "release"
    release_dir.mkdir(exist_ok=True)
    (release_dir / f"lift-log-v{version}.apk").write_bytes(APK_BYTES)
    return release_dir


def test_latest_returns_version_and_url(client: TestClient, tmp_path: Path) -> None:
    release_dir = _write_release(tmp_path)
    client.app.state.settings.release_dir = str(release_dir)

    resp = client.get("/api/app/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version_code"] == 64
    assert data["version_name"] == "64"
    assert data["size_bytes"] == len(APK_BYTES)
    assert data["url"].endswith("/api/app/apk")


def test_latest_picks_the_highest_version(client: TestClient, tmp_path: Path) -> None:
    """發佈目錄留著舊檔是常態（回退用），不能挑到舊的。"""
    release_dir = _write_release(tmp_path, version=64)
    (release_dir / "lift-log-v9.apk").write_bytes(b"old")
    (release_dir / "lift-log-v65.apk").write_bytes(APK_BYTES + b"!")
    client.app.state.settings.release_dir = str(release_dir)

    data = client.get("/api/app/latest").json()
    assert data["version_code"] == 65, "v9 的字串排序比 v65 大，必須用數值比較"


def test_latest_404_when_no_release(client: TestClient, tmp_path: Path) -> None:
    """沒有任何 APK 時要明確回 404，前端據此不顯示更新橫幅（⑥ 不靜默）。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    client.app.state.settings.release_dir = str(empty)

    resp = client.get("/api/app/latest")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_apk_download_returns_file(client: TestClient, tmp_path: Path) -> None:
    release_dir = _write_release(tmp_path)
    client.app.state.settings.release_dir = str(release_dir)

    resp = client.get("/api/app/apk")
    assert resp.status_code == 200
    assert resp.content == APK_BYTES
    assert resp.headers["content-type"] == "application/vnd.android.package-archive"


def test_both_endpoints_require_token(anon_client: TestClient, tmp_path: Path) -> None:
    release_dir = _write_release(tmp_path)
    anon_client.app.state.settings.release_dir = str(release_dir)

    assert anon_client.get("/api/app/latest").status_code == 401
    assert anon_client.get("/api/app/apk").status_code == 401
