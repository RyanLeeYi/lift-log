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

    def test_service_worker_served_at_root_scope(self, anon_client: TestClient) -> None:
        """F5：sw.js 必須掛在根路徑（scope 才能涵蓋整個 app），且為 JS。"""
        resp = anon_client.get("/sw.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]

    def test_sw_shell_list_matches_static_files(self) -> None:
        """F5 漂移防護：SHELL 清單的檔案要存在；新增的 js/css 檔要記得進 SHELL。

        漏列的檔案不會進離線快取——使用者離線重整就 404，且沒有任何建置期錯誤。
        """
        import re
        from pathlib import Path

        static_dir = Path(__file__).parent.parent / "app" / "static"
        sw_source = (static_dir / "sw.js").read_text(encoding="utf-8")
        shell_block = re.search(r"const SHELL = \[(.*?)\];", sw_source, re.S)
        assert shell_block, "sw.js 裡找不到 SHELL 清單"
        shell = set(re.findall(r'"(/[^"]*)"', shell_block.group(1)))

        # SHELL 裡的每個路徑都必須真的存在（"/" 對應 index.html）
        for url in shell:
            target = static_dir / ("index.html" if url == "/" else url.lstrip("/"))
            assert target.is_file(), f"SHELL 列了不存在的檔案：{url}"

        # 每個 js/css 檔都必須列進 SHELL（sw.js 自己除外——瀏覽器另行管理）
        for file in [*static_dir.glob("js/*.js"), *static_dir.glob("css/*.css")]:
            url = "/" + file.relative_to(static_dir).as_posix()
            assert url in shell, f"{url} 沒列進 sw.js 的 SHELL，離線時會載不到"
