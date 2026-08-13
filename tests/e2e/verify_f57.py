"""F57 體重頁圖表 x 軸改為時間軸 E2E ——**大部分條文已退役**。

用法：PYTHONUTF8=1 uv run python tests/e2e/verify_f57.py

F87 ⑤ 把折線圖整個換成 24 根長條圖，F57 賴以驗證的 `svg polyline` 不存在了。
原本的核心手法（讀 polyline 的 x 座標，驗「水平間距與日期成比例」）**沒有對應物可驗**：
長條圖是等寬等距的，日期差多遠都長一樣。

⚠ **這代表 F57 的存在理由消失了**：它要守的是「兩點之間的時間差看得出來」——
中間停量兩個月，圖上要看得出那是一段空白。長條圖看不出來。
**2026-08-01 Ryan 裁決：接受這個語意消失，不在長條圖上補回。**
記在這裡是為了讓後人知道它是被知情地放棄的，不是被漏掉的。

留下來的是**與圖表型別無關、至今仍然有效**的那幾條：⑦ 版號同步、③ 的邊界不炸圖
（0 點 / 1 點 / 全部同一天）、⑥ 切體脂後區間不變且單位正確。
折線圖專屬的條目（①②⑤ 的 x 軸比例與 domain、review P2-1 的每點小圓）已移除——
被驗的東西不存在了，不是把斷言放寬。長條圖自己的契約由 verify_f87 顧著（38 條）。
"""

import datetime
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from verify_f67 import (  # noqa: E402
    read_version,
    wait_home,
)

REPO = Path(__file__).resolve().parents[2]
TOKEN = "f57-own-token"


def ensure_custom(page):
    """確保自訂面板是開著的。點「自訂」是 toggle：面板已開時再點會關掉，
    後續找 .ex-custom .ex-date 就會 timeout（本腳本踩過）。"""
    if page.locator(".ex-custom").count() == 0:
        page.locator('.body-range button:has-text("自訂")').click()
        page.wait_for_timeout(350)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def api(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw.strip() else None


def wait_up(url, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    port = free_port()
    tmpdb = Path(tempfile.gettempdir()) / f"liftlog_f57_{port}.db"
    if tmpdb.exists():
        tmpdb.unlink()
    env = dict(os.environ, LIFTLOG_TOKEN=TOKEN, LIFTLOG_DB=str(tmpdb))
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app_factory",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    try:
        if not wait_up(base + "/"):
            print("SERVER FAILED")
            return 1

        today = datetime.date.today()
        # 刻意的空缺：85–80 天前有資料，之後跳到 20 天前才有（中間約兩個月空白）
        DAYS = [85, 84, 83, 82, 81, 80, 20, 19, 18, 17, 16, 15]
        for i in DAYS:
            d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            api(
                base,
                "POST",
                "/api/body-metrics",
                {"date": d, "weight_kg": 100.0 + i * 0.05, "body_fat_pct": 24.0 + i * 0.01},
            )

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 900})
            page.goto(base + "/")
            page.evaluate("t => localStorage.setItem('liftlog.token', t)", TOKEN)
            page.reload()
            wait_home(page)

            ver = read_version(page)  # F81 把版號搬進設定畫面
            sw_src = urllib.request.urlopen(base + "/sw.js", timeout=5).read().decode()
            check(
                "⑦ APP_VERSION 與 sw.js CACHE_NAME 同步遞增（兩處一致，≥v58）",
                ver.startswith("v") and int(ver[1:]) >= 58 and f'liftlog-shell-{ver}"' in sw_src,
                f"tag={ver!r}",
            )

            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.wait_for_timeout(400)

            # ③ 邊界不炸圖（0 點 / 1 點 / 全部同一天）——與圖表型別無關，仍然有效。
            # F87 ⑤ 之後畫的是 .body-bars .body-bar，不再是 svg polyline。
            bars = page.locator(".body-bars .body-bar").count()
            rows = page.locator(".bm-rows .bm-row").count()
            check(
                "（承接自 ①②）12 筆資料畫得出長條圖、清單同步（原文驗的 x 軸比例已隨折線圖退役）",
                bars > 0 and rows == 12,
                f"bars={bars} rows={rows}",
            )

            # ⑥ 切體脂：區間不變、單位跟著換（與圖表型別無關）
            range_before = page.locator(".body-range button.on").inner_text().strip()
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(600)
            range_after = page.locator(".body-range button.on").inner_text().strip()
            fat_bars = page.locator(".body-bars .body-bar").count()
            unit_pct = "%" in page.locator(".body-card").first.inner_text()
            check(
                "⑥ 切體脂後區間不變、圖照畫、單位是 %",
                range_before == range_after and fat_bars > 0 and unit_pct,
                f"range {range_before}→{range_after} bars={fat_bars} unit_pct={unit_pct}",
            )
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(500)

            # ③ 區間內 0 點：顯示空狀態、不炸圖。用「刪光資料」達成——
            # F87 ③ 拿掉自訂區間後，沒有別的辦法選到一段空窗（同 verify_f56 (6) 的處置）。
            for m in api(base, "GET", "/api/body-metrics"):
                api(base, "DELETE", f"/api/body-metrics/{m['date']}")
            page.reload()
            page.wait_for_timeout(400)
            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.wait_for_timeout(400)
            check(
                "③ 0 點：顯示「還沒有紀錄」、沒有長條、不炸圖",
                page.locator(".screen.body .body-empty").count() >= 1
                and page.locator(".body-bars .body-bar").count() == 0
                and page.locator(".bm-rows .bm-row").count() == 0,
                f"empty={page.locator('.screen.body .body-empty').count()}",
            )

            # ③ 1 點：畫得出來、不炸圖（正規化的分母是 0，最容易在這裡除零）
            one_day = (today - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
            api(base, "POST", "/api/body-metrics", {"date": one_day, "weight_kg": 80.0})
            page.reload()
            page.wait_for_timeout(400)
            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.wait_for_timeout(400)
            one_bars = page.locator(".body-bars .body-bar").count()
            one_h = page.evaluate(
                "() => { const b = document.querySelector('.body-bars .body-bar');"
                " return b ? Math.round(b.getBoundingClientRect().height) : 0; }"
            )
            check(
                "③ 1 點：畫得出一根長條且高度 > 0（正規化分母為 0 的邊界不除零）",
                one_bars == 1 and one_h > 0 and page.locator(".bm-rows .bm-row").count() == 1,
                f"bars={one_bars} h={one_h}",
            )

            # ③ 全部同一天（值不同）：仍不炸圖
            api(base, "POST", "/api/body-metrics", {"date": one_day, "weight_kg": 81.5})
            page.reload()
            page.wait_for_timeout(400)
            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.wait_for_timeout(400)
            check(
                "③ 同一天重複記錄（upsert）：仍是一筆一根、不炸圖",
                page.locator(".body-bars .body-bar").count() == 1
                and page.locator(".bm-rows .bm-row").count() == 1,
                f"bars={page.locator('.body-bars .body-bar').count()}",
            )

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        if tmpdb.exists():
            try:
                tmpdb.unlink()
            except Exception:
                pass

    print("\n==== F57 E2E ====")
    allok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
        allok = allok and ok
    print("=================")
    print("ALL PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
