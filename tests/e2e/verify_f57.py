"""F57 體重頁圖表 x 軸改為時間軸 E2E ——**大部分條文已退役**。

用法：PYTHONUTF8=1 uv run python tests/e2e/verify_f57.py

F87 ⑤ 曾把折線圖整個換成 24 根長條圖，F57 賴以驗證的 `svg polyline` 一度不存在。
原本的核心手法（讀 polyline 的 x 座標，驗「水平間距與日期成比例」）在長條圖時代
**沒有對應物可驗**：長條圖是等寬等距的，日期差多遠都長一樣。

⚠ **這代表 F57 的存在理由曾經消失過**：它要守的是「兩點之間的時間差看得出來」——
中間停量兩個月，圖上要看得出那是一段空白。長條圖看不出來。
**2026-08-01 Ryan 裁決：接受這個語意消失，不在長條圖上補回。**

**F162 把體重頁的長條圖換回折線圖**（`.line-chart` / `.line-pt`，見 line-chart.js），
但沿用的是動作表現共用的序位等距折線模組，x 軸依然不是「與日期成比例」——F57 ①②⑤
那條「水平間距與日期成比例」的驗法仍然沒有對應物，繼續不補回；本檔只把量測手段從
`.body-bars .body-bar` 換成 `.line-pt`，選擇器過期不代表條文重新成立。

留下來的是**與圖表型別無關、至今仍然有效**的那幾條：⑦ 版號同步、③ 的邊界不炸圖
（0 點 / 1 點 / 全部同一天）、⑥ 切體脂後區間不變且單位正確。
折線圖專屬的條目（①②⑤ 的 x 軸比例與 domain、review P2-1 的每點小圓）已移除——
被驗的東西不存在了，不是把斷言放寬。折線圖自己的契約由 verify_f134/135/136 顧著。
"""

import datetime
import json
import math
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ≥、①、⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from verify_f67 import (  # noqa: E402
    TOKEN,
    read_version,
    safe_port,
    start_server,
    wait_home,
)


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


def main():
    port = safe_port()
    tmp = Path(tempfile.mkdtemp(prefix="liftlog-f57-"))
    release = tmp / "release"
    release.mkdir()
    proc = start_server(port, tmp / "e2e.db", release)
    base = f"http://127.0.0.1:{port}"
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    try:
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
            # F162 把長條圖換回折線圖，畫的是 .line-chart 底下的 .line-pt（見 line-chart.js）。
            # 12 筆 <= AGG_MAX_POINTS(50)，不觸發聚合，點數恆等於筆數。
            pts = page.locator(".line-chart .line-pt").count()
            rows = page.locator(".bm-rows .bm-row").count()
            check(
                "（承接自 ①②）12 筆資料畫得出折線圖、清單同步（原文驗的 x 軸比例已隨折線圖退役）",
                pts == 12 and rows == 12,
                f"pts={pts} rows={rows}",
            )

            # ⑥ 切體脂：區間不變、單位跟著換（與圖表型別無關）
            range_before = page.locator(".body-range button.on").inner_text().strip()
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(600)
            range_after = page.locator(".body-range button.on").inner_text().strip()
            fat_pts = page.locator(".line-chart .line-pt").count()
            unit_pct = "%" in page.locator(".body-card").first.inner_text()
            check(
                "⑥ 切體脂後區間不變、圖照畫、單位是 %",
                range_before == range_after and fat_pts == 12 and unit_pct,
                f"range {range_before}→{range_after} pts={fat_pts} unit_pct={unit_pct}",
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
                "③ 0 點：顯示「還沒有紀錄」、沒有資料點、不炸圖",
                page.locator(".screen.body .body-empty").count() >= 1
                and page.locator(".line-chart .line-pt").count() == 0
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
            # 長條圖時代這裡驗的是「高度」（正規化分母為 0 時的除零風險）。折線圖沒有
            # 高度概念（.line-pt 是固定直徑的圓點，靠 top 定位），除零風險轉移到
            # layoutPoints() 的 y 座標計算：span===0（單點時 valMax===valMin）要落到
            # 繪圖區中線而非 NaN。改驗這個——y 座標是有限數字即代表分母為 0 的邊界沒有炸開。
            one_pts = page.locator(".line-chart .line-pt").count()
            one_top = page.evaluate(
                "() => { const p = document.querySelector('.line-chart .line-pt');"
                " return p ? parseFloat(p.style.top) : NaN; }"
            )
            check(
                "③ 1 點：畫得出一個資料點且 y 座標非 NaN（正規化分母為 0 的邊界不除零）",
                one_pts == 1
                and not math.isnan(one_top)
                and one_top > 0
                and page.locator(".bm-rows .bm-row").count() == 1,
                f"pts={one_pts} top={one_top}",
            )

            # ③ 全部同一天（值不同）：仍不炸圖
            api(base, "POST", "/api/body-metrics", {"date": one_day, "weight_kg": 81.5})
            page.reload()
            page.wait_for_timeout(400)
            page.locator(".bottom-nav .nav-item", has_text="體重").click()
            page.wait_for_selector(".screen.body", timeout=8000)
            page.wait_for_timeout(400)
            check(
                "③ 同一天重複記錄（upsert）：仍是一筆一點、不炸圖",
                page.locator(".line-chart .line-pt").count() == 1
                and page.locator(".bm-rows .bm-row").count() == 1,
                f"pts={page.locator('.line-chart .line-pt').count()}",
            )

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

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
