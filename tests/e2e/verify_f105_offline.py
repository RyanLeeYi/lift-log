"""F105 E2E：離線本地鏡射（`app/static/js/api.js` 的 `local*` 函式）與後端契約一致。

跑法：`PYTHONUTF8=1 uv run python tests/e2e/verify_f105_offline.py`

驗三件事：
  ① 離線路徑本身：native 殼＋假 LocalStore plugin，直接 `import('/js/api.js')` 呼叫
     匯出的 `api`（不經 UI——app.js/calendar.js/exercise-detail.js 由平行 worker
     同時在改，繞過它們才不會被無關的畫面改動連坐）。建一個 `mode:"time"` 的動作、
     離線記一組 60 秒，驗日曆熱力圖與歷史 PR 算出的形狀與數字。
  ② 離線／後端算法一致：把同樣的事實（相同重量、次數、秒數）直接送進真的後端 REST
     （模擬「重新上線同步後」這批資料已經在伺服器上），比對兩邊獨立算出的
     calendar／history 數字完全一致。
  ③ 次數型的離線行為完全不變（回歸）。

⚠ 界線：②驗的是「離線與後端同一套計算語意」，不是原生 SyncClient/SyncPlugin（Java）
真的把離線佇列的 mutation 推上伺服器——那條路徑是原生程式碼＋真實網路，
Playwright 碰不到，由 F140LocalStoreInstrumentedTest 那類原生測試涵蓋。
同 verify_f67 對「假 plugin 不代表真安裝」的界線說明。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 報告裡有 ①②③⚠ 這類字，Windows console 預設 CP950 編不出來會 UnicodeEncodeError exit 1
# ——腳本自己釘 UTF-8，不依賴呼叫端帶 PYTHONUTF8／PYTHONIOENCODING（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from playwright.sync_api import sync_playwright  # noqa: E402
from verify_f67 import PHONE, TOKEN, e2e_tmp, safe_port, start_server  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


# 只需要 isNativePlatform() 為真＋LocalStore 的幾個方法：不驅動 UI，
# 所以不必假 AuthSession/Sync/AppUpdate（api.js 的 local* 計算不碰那些外掛）。
FAKE_LOCAL_STORE = """
const __db = { exercises: [], workouts: [], sets: [] };
let __nextExercise = 1, __nextWorkout = 1, __nextSet = 1;
window.Capacitor = {
  isNativePlatform: () => true,
  getPlatform: () => 'android',
  Plugins: {
    LocalStore: {
      initialize: async () => ({ schemaVersion: 2, seededExercises: 0, pendingMutations: 0 }),
      snapshot: async () => structuredClone({
        ...__db, templates: [], body_metrics: [], daily_status: [], settings: [],
      }),
      createExercise: async (o) => {
        const row = { id: __nextExercise++, name_zh: o.nameZh, name_en: o.nameEn || o.nameZh,
          muscle_group: o.muscleGroup || '其他', is_bodyweight: o.isBodyweight ? 1 : 0,
          mode: o.mode || 'reps' };
        __db.exercises.push(row);
        return structuredClone(row);
      },
      createWorkout: async (o) => {
        const row = { id: __nextWorkout++, date: o.date, template_id: o.templateId ?? null,
          note: o.note ?? null, created_at: new Date().toISOString(), ended_at: null };
        __db.workouts.push(row);
        return structuredClone(row);
      },
      addSet: async (o) => {
        const row = { id: __nextSet++, client_uuid: o.clientUuid, workout_id: o.workoutId,
          exercise_id: o.exerciseId, set_number: o.setNumber ?? __nextSet - 1,
          weight_kg: o.weightKg, reps: o.reps ?? null,
          duration_seconds: o.durationSeconds ?? null,
          rpe: o.rpe ?? null, rest_seconds: o.restSeconds ?? null };
        __db.sets.push(row);
        return structuredClone(row);
      },
    },
  },
};
"""

# 全部在一次 evaluate 裡跑完——同一個 page，dynamic import 的模組實例（含 localReady 快取）
# 在多次呼叫間本來就會延續，不需要分次 evaluate。
DRIVE_OFFLINE = """
async () => {
  const { api } = await import('/js/api.js');
  const plank = await api.createExercise({ name_zh: '平板支撐', name_en: 'Plank',
    muscle_group: '核心', is_bodyweight: false, mode: 'time' });
  const squat = await api.createExercise({ name_zh: '深蹲', name_en: 'Squat',
    muscle_group: '腿', is_bodyweight: false });
  const w1 = await api.createWorkout({ date: '2026-08-19' });
  const plankSet = await api.logSet(w1.id, { exercise_id: plank.id, client_uuid: 'e2e-plank-1',
    set_number: 1, weight_kg: 0, duration_seconds: 60, rpe: null, rest_seconds: null });
  const w2 = await api.createWorkout({ date: '2026-08-20' });
  const squatSet = await api.logSet(w2.id, { exercise_id: squat.id, client_uuid: 'e2e-squat-1',
    set_number: 1, weight_kg: 50, reps: 5, rpe: null, rest_seconds: null });
  const calendar = await api.calendarStats(2026, 8);
  const plankHistory = await api.exerciseHistory(plank.id, '2026-08-01', '2026-08-31');
  const squatHistory = await api.exerciseHistory(squat.id, '2026-08-01', '2026-08-31');
  return { plank, squat, plankSet, squatSet, calendar, plankHistory, squatHistory };
}
"""


def rest(base: str, method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(f"{base}{path}", data=data, method=method, headers=headers)
    with urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def main() -> int:
    port = safe_port()
    db = e2e_tmp() / f"liftlog_f105_offline_e2e_{port}.db"
    release = e2e_tmp() / f"liftlog_f105_offline_release_{port}"
    release.mkdir(exist_ok=True)
    proc = start_server(port, db, release)
    base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=PHONE)
            page = ctx.new_page()
            page.add_init_script(FAKE_LOCAL_STORE)
            page.goto(base, wait_until="domcontentloaded")
            result = page.evaluate(DRIVE_OFFLINE)
            ctx.close()
            browser.close()

        # ① 離線建立時間型動作、記一組 60 秒
        check(result["plank"]["mode"] == "time", "① 離線建立 mode:time 動作")
        check(
            result["plankSet"]["duration_seconds"] == 60 and result["plankSet"]["reps"] is None,
            "① 離線記一組 60 秒：duration_seconds=60、reps=null",
        )

        day19 = result["calendar"]["days"]["2026-08-19"]
        check(
            day19 == {"tonnage_kg": 0, "duration_seconds": 60, "sets_count": 1},
            f"① 日曆熱力圖：tonnage=0、duration=60、sets_count=1（實得 {day19}）",
        )

        plank_prs = result["plankHistory"]["prs"]
        check(
            plank_prs["top_set_duration"] == {"weight_kg": 0, "reps": None, "duration_seconds": 60},
            f"① 時間型 PR top_set_duration（實得 {plank_prs['top_set_duration']}）",
        )
        check(plank_prs["top_session_duration_seconds"] == 60, "① top_session_duration_seconds=60")
        check(
            all(
                plank_prs[k] is None
                for k in ("top_weight", "top_set_volume", "top_est_1rm", "top_session_volume")
            ),
            "① 時間型的次數型 PR 欄位全部 null（估計 1RM 對秒數沒意義）",
        )
        plank_set_row = result["plankHistory"]["sessions"][0]["sets"][0]
        check(
            plank_set_row["duration_seconds"] == 60 and plank_set_row["reps"] is None,
            "① history sessions 內的組帶 duration_seconds、reps=null",
        )

        # ③ 回歸：次數型的離線行為不變
        day20 = result["calendar"]["days"]["2026-08-20"]
        check(
            day20 == {"tonnage_kg": 250, "duration_seconds": 0, "sets_count": 1},
            f"③ 回歸：次數型日曆 tonnage=250、duration=0、sets_count=1（實得 {day20}）",
        )
        squat_prs = result["squatHistory"]["prs"]
        expect_1rm = 50 * (1 + 5 / 30)
        check(
            squat_prs["top_weight"] == {"weight_kg": 50, "reps": 5, "duration_seconds": None}
            and squat_prs["top_set_volume"]
            == {"weight_kg": 50, "reps": 5, "duration_seconds": None}
            and abs(squat_prs["top_est_1rm"] - expect_1rm) < 1e-9
            and squat_prs["top_session_volume"] == 250
            and squat_prs["top_set_duration"] is None
            and squat_prs["top_session_duration_seconds"] is None,
            f"③ 回歸：次數型 PR 完全不變（實得 {squat_prs}）",
        )

        # ② 離線／後端算法一致：把相同事實直接送進真後端（模擬同步後資料已在伺服器上）
        plank_online = rest(
            base, "POST", "/api/exercises",
            {"name_zh": "平板支撐-online", "name_en": "Plank-online",
             "muscle_group": "核心", "is_bodyweight": False, "mode": "time"},
        )
        squat_online = rest(
            base, "POST", "/api/exercises",
            {"name_zh": "深蹲-online", "name_en": "Squat-online",
             "muscle_group": "腿", "is_bodyweight": False},
        )
        w1o = rest(base, "POST", "/api/workouts", {"date": "2026-08-19"})
        rest(
            base, "POST", f"/api/workouts/{w1o['id']}/sets",
            {"client_uuid": "e2e-plank-online-1", "exercise_id": plank_online["id"],
             "weight_kg": 0, "duration_seconds": 60},
        )
        w2o = rest(base, "POST", "/api/workouts", {"date": "2026-08-20"})
        rest(
            base, "POST", f"/api/workouts/{w2o['id']}/sets",
            {"client_uuid": "e2e-squat-online-1", "exercise_id": squat_online["id"],
             "weight_kg": 50, "reps": 5},
        )
        cal_online = rest(base, "GET", "/api/stats/calendar?year=2026&month=8")
        plank_hist_online = rest(
            base, "GET",
            f"/api/exercises/{plank_online['id']}/history?from=2026-08-01&to=2026-08-31",
        )
        squat_hist_online = rest(
            base, "GET",
            f"/api/exercises/{squat_online['id']}/history?from=2026-08-01&to=2026-08-31",
        )

        check(
            cal_online["days"]["2026-08-19"] == day19,
            f"② 離線／後端日曆一致（時間型）：{cal_online['days']['2026-08-19']} vs {day19}",
        )
        check(
            cal_online["days"]["2026-08-20"] == day20,
            f"② 離線／後端日曆一致（次數型）：{cal_online['days']['2026-08-20']} vs {day20}",
        )
        check(
            plank_hist_online["prs"] == plank_prs,
            f"② 離線／後端 PR 一致（時間型）：{plank_hist_online['prs']} vs {plank_prs}",
        )
        check(
            squat_hist_online["prs"] == squat_prs,
            f"② 離線／後端 PR 一致（次數型）：{squat_hist_online['prs']} vs {squat_prs}",
        )
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for _ in range(20):
            try:
                db.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.25)
        for f in release.iterdir():
            f.unlink()
        release.rmdir()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
