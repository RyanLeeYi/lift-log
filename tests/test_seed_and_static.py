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
    def test_health_returns_ok_without_token_and_probes_db(
        self, anon_client: TestClient
    ) -> None:
        """mission-control 健康檢查入口：無 auth、實際碰 DB（靜態 / 的 200 反映不了 DB 壞掉）。"""
        resp = anon_client.get("/health")
        assert resp.status_code == 200
        # 只檢查必要欄位在不在，不做整份相等比對——/health 是給 mission-control 用的外部契約，
        # 之後多帶欄位（F93 加了 env）是常態，鎖死欄位集合會讓每次擴充都假性失敗。
        assert resp.json()["status"] == "ok"

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

    def test_service_worker_is_never_edge_cached(self, anon_client: TestClient) -> None:
        """F13：/sw.js 回 no-cache——PWA 更新靠 sw.js 換版觸發，被 CDN 邊緣快取
        （Cloudflare 預設 4h）會讓部署延遲整個 TTL 才到手機。"""
        resp = anon_client.get("/sw.js")
        assert resp.headers.get("cache-control") == "no-cache"

    def test_other_shell_assets_keep_default_cache_policy(self, anon_client: TestClient) -> None:
        """F13：只有 sw.js 改策略；其餘殼資產由 SW CACHE_NAME 版本管理，不加 no-cache。"""
        resp = anon_client.get("/js/app.js")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") != "no-cache"

    def test_sw_install_fetches_shell_with_version_bust(self) -> None:
        """F14：install 抓 SHELL 必須帶 ?v=CACHE_NAME 版本戳並以原始 URL 存入。

        用 cache.add(url) 會吃到 CDN／瀏覽器快取的舊檔——新 SW 裝出「新版本號＋舊內容」
        的混版（2026-07-18 部署 F12 時實際發生）。版本戳讓每次換版的快取 key 必失效。
        """
        from pathlib import Path

        sw_source = (
            Path(__file__).parent.parent / "app" / "static" / "sw.js"
        ).read_text(encoding="utf-8")
        install_block = sw_source[sw_source.index('addEventListener("install"'):]
        install_block = install_block[: install_block.index("addEventListener", 20)]
        assert "cache.add(" not in install_block, "install 不得用 cache.add——吃快取舊檔"
        assert "?v=${CACHE_NAME}" in install_block, "SHELL 抓取要帶 ?v=CACHE_NAME 版本戳"
        assert "cache.put(url" in install_block, "回應要以原始 URL 存入（fetch handler 才對得到）"

    def test_app_reloads_once_when_new_sw_takes_over(self) -> None:
        """F14：新 SW 接管（controllerchange）後頁面自動 reload 一次，使用者不需手動強制重整。

        且「首次安裝的初次接管」不重載（頁面本就最新），但只跳過那一次——之後任何一次
        接管（部署新版）都要重載，否則首訪者不關頁面就更新不到下次部署（Codex P2①）。
        """
        from pathlib import Path

        app_source = (
            Path(__file__).parent.parent / "app" / "static" / "js" / "app.js"
        ).read_text(encoding="utf-8")
        assert "controllerchange" in app_source
        assert "location.reload()" in app_source
        # 只跳過首裝的「初次」接管，不是永久跳過首訪者——用一次性旗標而非永久 hadController 擋
        assert "skippedInitialClaim" in app_source, "首裝只跳過初次接管，之後部署仍須重載"

    def test_logger_rest_button_has_two_states(self) -> None:
        """F15：logger 主按鈕兩態切換——就緒態記錄、休息態「繼續下一組」（停倒數、凍結休息秒數）。

        行為由 Playwright E2E 驗（scratchpad verify_f15.py）；這裡守源碼不被靜默改回單態。
        """
        from pathlib import Path

        app_source = (
            Path(__file__).parent.parent / "app" / "static" / "js" / "app.js"
        ).read_text(encoding="utf-8")
        assert "繼續下一組" in app_source, "休息態按鈕文案缺失"
        assert "continueNext" in app_source, "缺少繼續下一組（凍結休息＋停倒數）處理"
        # rest_seconds 來自凍結值而非即時 elapsed——確保按鈕切換前不會把資料入輸入的時間算進休息
        assert "pendingRestSeconds" in app_source, "rest_seconds 應來自按繼續下一組凍結的值"

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

        # 每個 js/css/字型檔都必須列進 SHELL（sw.js 自己除外——瀏覽器另行管理）。
        # F79：字型漏列的後果比 js 更隱晦——離線時不會壞掉，只會安靜地掉回系統字。
        for file in [
            *static_dir.glob("js/*.js"),
            *static_dir.glob("css/*.css"),
            *static_dir.glob("fonts/*.woff2"),
        ]:
            url = "/" + file.relative_to(static_dir).as_posix()
            assert url in shell, f"{url} 沒列進 sw.js 的 SHELL，離線時會載不到"


class TestEnvLabel:
    """F93 追加：畫面要能一眼看出這是正式站還是測試站。"""

    def test_health_reports_env(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["env"] == "prod"  # 預設值：沒設 LIFTLOG_ENV 就是正式站

    def test_env_label_comes_from_settings(self, tmp_path):
        from fastapi.testclient import TestClient

        from app.config import Settings
        from app.main import create_app

        app = create_app(Settings(token="t", db_path=str(tmp_path / "e.db"), env_label="dev"))
        with TestClient(app) as c:
            assert c.get("/health").json()["env"] == "dev"

    def test_unknown_env_value_falls_back_to_prod(self):
        """拼錯或用了變體（production）時要當正式站，不能被前端標成「測試環境」。"""
        from app.config import Settings

        assert Settings(token="t", env_label="production").env_label == "prod"
        assert Settings(token="t", env_label="").env_label == "prod"
        assert Settings(token="t", env_label="dev").env_label == "dev"
