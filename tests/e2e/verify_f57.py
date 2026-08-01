"""F57 體重頁圖表 x 軸改為時間軸 E2E。
用法：PYTHONUTF8=1 uv run python verify_f57_own.py
涵蓋 acceptance ①–⑦。

核心手法：直接讀 SVG polyline 的 points，驗「x 座標與日期成比例」而不是「等距」。
測資刻意留一段兩個月的空缺——等距索引軸下該段與其他段的水平間距相同，時間軸下會明顯變寬。
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

from verify_f67 import (  # noqa: E402
    end_workout,
    read_version,
    start_from_home,
    wait_home,
)

REPO = Path(r"C:\Users\user\OneDrive\Desktop\SideProject\lift-log")
TOKEN = "f57-own-token"

POLY = """() => {
  const pl = document.querySelector('.body-chart svg polyline');
  if (!pl) return null;
  const xs = pl.getAttribute('points').trim().split(' ')
    .map(p => parseFloat(p.split(',')[0]));
  // 末點圓是 r=3；P2-1 起每個點還會多畫 r=2 的小圓，所以要指定 r=3 才抓得到末點
  const c = document.querySelector('.body-chart svg circle[r="3"]');
  return { xs, cx: c ? parseFloat(c.getAttribute('cx')) : null };
}"""


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

            # ①② 空缺要有水平間距：85→80 天那段每步 ≈ 1 天，80→20 那段一次跨 60 天
            poly = page.evaluate(POLY)
            xs = poly["xs"]
            steps = [round(xs[i + 1] - xs[i], 2) for i in range(len(xs) - 1)]
            gap_step = max(steps)
            normal_steps = [s for s in steps if s != gap_step]
            avg_normal = sum(normal_steps) / len(normal_steps)
            check(
                "①② x 軸依時間：兩個月空缺的水平間距遠大於相鄰日的間距（等距索引下會相同）",
                len(xs) == 12 and gap_step > avg_normal * 20,
                f"gap_step={gap_step} avg_normal={round(avg_normal, 2)} 倍率={round(gap_step / avg_normal, 1)}",
            )

            # ① domain＝區間：3M 下最舊點（85 天前）不在最左緣、最新點（15 天前）不在最右緣
            foot = page.locator(".body-main-delta").inner_text().split("\n")
            check(
                "①⑤ x 軸 domain＝選取區間：首點不貼左緣、末點不貼右緣；卡片底部顯示區間邊界",
                xs[0] > 7 and xs[-1] < 313 and poly["cx"] == xs[-1],
                f"first_x={xs[0]} last_x={xs[-1]} circle_cx={poly['cx']} foot={foot}",
            )

            # ⑤ 底部起訖＝區間邊界（3M 前 → 今天）
            three_m_ago = (today - datetime.timedelta(days=92)).strftime("%Y-%m")
            foot_text = page.locator(".body-main-delta").inner_text()
            check(
                "⑤ 卡片底部起訖顯示區間邊界（非資料首末點）",
                today.strftime("%Y-%m-%d") in foot_text
                and (
                    three_m_ago in foot_text
                    or (today - datetime.timedelta(days=90)).strftime("%Y-%m") in foot_text
                ),
                f"foot={foot_text!r}",
            )

            # ② 換更長的區間：同一批資料被壓縮到右側一小段（domain 變寬 → 資料占比變小）。
            # 用「自訂」而非長 preset——F58 起超出資料範圍的 preset 會被停用（本測資 85 天，
            # 連 3M 都是「第一個涵蓋得住」的檔位，沒有更長的可用 preset），而自訂不受限制
            span_3m = xs[-1] - xs[0]
            ensure_custom(page)
            wide = page.locator(".ex-custom .ex-date")
            wide.nth(0).fill((today - datetime.timedelta(days=300)).strftime("%Y-%m-%d"))
            wide.nth(1).fill(today.strftime("%Y-%m-%d"))
            page.locator(".ex-custom-apply").click()
            page.wait_for_timeout(900)
            poly_long = page.evaluate(POLY)
            span_long = poly_long["xs"][-1] - poly_long["xs"][0]
            check(
                "② 換長區間（自訂 300 天）後同一批資料的水平跨度變窄（x 軸真的依區間縮放）",
                span_long < span_3m * 0.6,
                f"span_3M={round(span_3m, 1)} span_custom300={round(span_long, 1)}",
            )

            # ③ 單點：自訂區間只框住一天
            one_day = (today - datetime.timedelta(days=18)).strftime("%Y-%m-%d")
            ensure_custom(page)
            dts = page.locator(".ex-custom .ex-date")
            dts.nth(0).fill(one_day)
            dts.nth(1).fill(one_day)
            page.locator(".ex-custom-apply").click()
            page.wait_for_timeout(800)
            poly_one = page.evaluate(POLY)
            rows_one = page.locator(".bm-rows .bm-row").count()
            check(
                "③ from=to 的單日區間：不炸圖、點畫在中央、清單 1 筆",
                poly_one is not None
                and len(poly_one["xs"]) == 1
                and abs(poly_one["xs"][0] - 160) < 1
                and rows_one == 1,
                f"xs={poly_one['xs'] if poly_one else None} rows={rows_one}",
            )

            # ③ 0 點：空區間（測資之外）
            dts = page.locator(".ex-custom .ex-date")
            dts.nth(0).fill((today - datetime.timedelta(days=400)).strftime("%Y-%m-%d"))
            dts.nth(1).fill((today - datetime.timedelta(days=390)).strftime("%Y-%m-%d"))
            page.locator(".ex-custom-apply").click()
            page.wait_for_timeout(800)
            check(
                "③ 區間內 0 點：顯示「還沒有紀錄」、無 svg、不炸圖",
                page.locator(".body-empty").count() >= 1 and page.evaluate(POLY) is None,
                f"empty={page.locator('.body-empty').count()}",
            )

            # ⑥ 既有行為：切 metric（體脂）仍畫得出時間軸；區間不變
            page.locator('.body-range button:has-text("3M")').click()
            page.wait_for_timeout(800)
            page.locator(".metric-toggle .metric-pill", has_text="體脂").click()
            page.wait_for_timeout(400)
            poly_fat = page.evaluate(POLY)
            range_kept = page.locator(".body-range button.on").inner_text().strip()
            unit_ok = "%" in page.locator(".body-main-delta").inner_text()
            check(
                "⑥ 切體脂後仍是時間軸（同樣的空缺間距）、區間不變、單位 %",
                poly_fat is not None
                and len(poly_fat["xs"]) == 12
                and max(
                    round(poly_fat["xs"][i + 1] - poly_fat["xs"][i], 2)
                    for i in range(len(poly_fat["xs"]) - 1)
                )
                > 100
                and range_kept == "3M"
                and unit_ok,
                f"points={len(poly_fat['xs']) if poly_fat else 0} range={range_kept!r} unit_ok={unit_ok}",
            )

            # review P2-1 回歸：點數少時每點都有小圓（短跨度塌成豎線時仍看得出有幾筆、在哪）
            page.locator('.body-range button:has-text("3M")').click()
            page.wait_for_timeout(800)
            page.locator(".metric-toggle .metric-pill", has_text="體重").click()
            page.wait_for_timeout(400)
            dots = page.evaluate(
                "() => document.querySelectorAll('.body-chart svg circle[r=\"2\"]').length"
            )
            check(
                "review P2-1：12 個點時每點都畫小圓（含末點的大圓另計）",
                dots == 12,
                f"small_dots={dots}（期望 12）",
            )

            # review P3-5 回歸：最新值旁標出量測日期（與底部的區間邊界語意分開）
            latest_txt = " ".join(page.locator(".body-main-value").inner_text().split())
            foot_txt = " ".join(page.locator(".body-main-delta").inner_text().split())
            last_date = api(base, "GET", "/api/body-metrics")[-1]["date"]
            want = last_date[5:].replace("-", "/")
            check(
                "review P3-5：最新值旁顯示其量測日期（非區間邊界）",
                want in latest_txt and want not in foot_txt.split()[0],
                f"latest={latest_txt!r} 期望日期={want} foot={foot_txt!r}",
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
