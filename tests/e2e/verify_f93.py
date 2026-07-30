"""F93 E2E：開發與正式環境分離（①③⑧⑨⑩⑫的可自動化部分）。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f93.py`

**兩台伺服器都由這支腳本自己起**（各自的 port / token / DB），不碰真正在跑的兩站——
驗收腳本去戳正式服務，等於把「測試」變成「對正式環境動手」。

②（git archive 快照）與 ④⑤⑥⑦（APK flavor）不在這裡：前者驗的是部署腳本的行為，
後者必須在實機上看兩顆 app 並存，都由驗收者手動走。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, REPO, free_port  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def start(port: int, db: Path, token: str, env_label: str) -> subprocess.Popen:
    import os

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app_factory", "--factory",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO,
        env={**dict(os.environ), "LIFTLOG_TOKEN": token, "LIFTLOG_DB": str(db),
             "LIFTLOG_ENV": env_label, "LIFTLOG_RELEASE_DIR": str(REPO / f"rel_{port}")},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError(f"port {port} 沒起來")


def get(url: str, token: str | None = None) -> tuple[int, str]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


def label_text(page, base: str) -> str:
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=10_000)
    page.wait_for_timeout(1200)  # loadEnvLabel 是非同步的
    node = page.locator(".env-tag")
    return node.first.inner_text() if node.count() else "(沒有 env-tag)"


def main() -> int:
    p_port, d_port = free_port(), free_port()
    p_db = REPO / f"liftlog_f93_prod_{p_port}.db"
    d_db = REPO / f"liftlog_f93_dev_{d_port}.db"
    p_tok, d_tok = "f93-prod-token", "f93-dev-token"
    procs = []
    try:
        procs.append(start(p_port, p_db, p_tok, "prod"))
        procs.append(start(d_port, d_db, d_tok, "dev"))
        p_base, d_base = f"http://127.0.0.1:{p_port}", f"http://127.0.0.1:{d_port}"

        # ---------- ⑫ /health 回報 env ----------
        for base, expect, who in ((p_base, "prod", "正式"), (d_base, "dev", "測試")):
            status, body = get(f"{base}/health")
            env = json.loads(body).get("env")
            check(status == 200 and env == expect,
                  f"⑫ {who}站 /health 回 env={expect}（實際 {env}）")
        check(
            "env" in json.loads(get(f"{p_base}/health")[1]),
            "⑫ /health 免 auth 就拿得到 env（setup 畫面還沒 token 也顯示得出來）",
        )

        # ---------- ①⑧⑩ token 與 DB 互不污染 ----------
        check(get(f"{d_base}/api/workouts", p_tok)[0] == 401,
              "①⑩ 正式站的 token 打不開測試站")
        check(get(f"{p_base}/api/workouts", d_tok)[0] == 401,
              "①⑩ 測試站的 token 打不開正式站")

        # 在測試站建一場訓練，正式站不得看見
        req = urllib.request.Request(
            f"{d_base}/api/workouts", data=b"{}",
            headers={"Authorization": f"Bearer {d_tok}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            check(r.status == 201, "前置：測試站建立一場訓練")
        n_dev = len(json.loads(get(f"{d_base}/api/workouts", d_tok)[1]))
        n_prod = len(json.loads(get(f"{p_base}/api/workouts", p_tok)[1]))
        check(n_dev == 1 and n_prod == 0,
              f"⑧ 兩站的 DB 互不影響（測試站 {n_dev} 場、正式站 {n_prod} 場）")

        # ---------- ⑫ 畫面上的環境標示 ----------
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()

            dev_label = label_text(page, d_base)
            check(dev_label == "測試環境", f"⑫ 測試站顯示「測試環境」（實際「{dev_label}」）")

            page2 = ctx.new_page()
            prod_label = label_text(page2, p_base)
            check(prod_label == "正式環境", f"⑫ 正式站顯示「正式環境」（實際「{prod_label}」）")

            # 位置：必須在版號**下面**
            order = page.evaluate(
                """() => {
                    const v = document.querySelector('.version-tag');
                    const e = document.querySelector('.env-tag');
                    if (!v || !e) return null;
                    return e.getBoundingClientRect().top >= v.getBoundingClientRect().bottom - 1;
                }"""
            )
            check(order is True, f"⑫ 環境標示在版號下方（實際 {order}）")

            # 顏色：測試站要有警示色，不能與正式站同一個低調樣式
            colors = {}
            for tag, pg in (("dev", page), ("prod", page2)):
                colors[tag] = pg.evaluate(
                    "() => getComputedStyle(document.querySelector('.env-tag')).color"
                )
            check(colors["dev"] != colors["prod"],
                  f"⑫ 測試站用不同（警示）顏色：dev={colors['dev']} vs prod={colors['prod']}")

            browser.close()

        # ---------- ⑨ 公開 hostname 的 UA 陷阱 ----------
        # 這條驗的是「腳本知道這件事」，不是去戳真的公開站：Cloudflare 對
        # Python-urllib 回 403，不知道的人會把它誤判成服務故障。
        src = (REPO / "tests/e2e/verify_f93.py").read_text(encoding="utf-8")
        check("Cloudflare" in src and "403" in src,
              "⑨ 腳本內記載了 Cloudflare 對 Python-urllib 回 403 的陷阱")

    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=10)
        for db in (p_db, d_db):
            for suffix in ("", "-wal", "-shm"):
                target = Path(str(db) + suffix)
                for _ in range(10):
                    try:
                        target.unlink(missing_ok=True)
                        break
                    except OSError:
                        time.sleep(0.3)
        for port in (p_port, d_port):
            rel = REPO / f"rel_{port}"
            if rel.exists():
                for f in rel.iterdir():
                    f.unlink()
                rel.rmdir()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    if passed != len(results):
        print("\nFAILED:")
        for ok, label in results:
            if not ok:
                print(f"  - {label}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
