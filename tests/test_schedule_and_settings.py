"""F80：課表排程（星期）與應用設定。

排程的資料形狀很小，容易漏掉的是邊界：值域、去重、一天多份、以及「本週練幾天」的推導
在跨週、軟刪除、空 workout 這幾種情況下算不算。這裡把那些情況一條條釘住。
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.db import make_engine
from app.migrations import migrate_schema
from app.models import Base
from app.services import schedule as schedule_svc
from app.services import settings as settings_svc


def _make_template(client, name: str, weekdays=None, sets: int = 3, ex_id: int = 1):
    body = {
        "name": name,
        "exercises": [{"exercise_id": ex_id, "default_sets": sets}],
    }
    if weekdays is not None:
        body["weekdays"] = weekdays
    resp = client.post("/api/templates", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestTemplateWeekdays:
    def test_create_and_read_back(self, client, exercise_id) -> None:
        created = _make_template(client, ex_id=exercise_id, name="推胸日", weekdays=[1, 3, 5])
        assert created["weekdays"] == [1, 3, 5]
        assert client.get("/api/templates").json()[0]["weekdays"] == [1, 3, 5]

    def test_no_schedule_reads_as_empty_list(self, client, exercise_id) -> None:
        """沒排程回空陣列而不是 null——前端少一個判斷分支。"""
        assert _make_template(client, ex_id=exercise_id, name="自由日")["weekdays"] == []

    def test_duplicates_are_collapsed_and_sorted(self, client, exercise_id) -> None:
        created = _make_template(client, ex_id=exercise_id, name="亂序", weekdays=[5, 1, 5, 3])
        assert created["weekdays"] == [1, 3, 5]

    @pytest.mark.parametrize("bad", [[0], [8], [-1], [1, 9]])
    def test_out_of_range_rejected(self, client, exercise_id, bad) -> None:
        resp = client.post(
            "/api/templates",
            json={
                "name": f"壞的{bad}",
                "exercises": [{"exercise_id": exercise_id, "default_sets": 3}],
                "weekdays": bad,
            },
        )
        assert resp.status_code == 400
        assert "weekday" in resp.json()["error"]

    def test_patch_weekdays_only(self, client, exercise_id) -> None:
        """PATCH 只動排程，動作清單原封不動。"""
        created = _make_template(client, ex_id=exercise_id, name="拉背日", weekdays=[2], sets=4)
        resp = client.patch(f"/api/templates/{created['id']}/weekdays", json={"weekdays": [2, 4]})
        assert resp.status_code == 200
        assert resp.json()["weekdays"] == [2, 4]
        assert resp.json()["exercises"] == created["exercises"]

    def test_patch_can_clear_schedule(self, client, exercise_id) -> None:
        created = _make_template(client, ex_id=exercise_id, name="腿日", weekdays=[6])
        resp = client.patch(f"/api/templates/{created['id']}/weekdays", json={"weekdays": []})
        assert resp.json()["weekdays"] == []

    def test_patch_validates_range(self, client, exercise_id) -> None:
        created = _make_template(client, ex_id=exercise_id, name="肩日", weekdays=[1])
        resp = client.patch(f"/api/templates/{created['id']}/weekdays", json={"weekdays": [0]})
        assert resp.status_code == 400

    def test_put_without_weekdays_keeps_schedule(self, client, exercise_id) -> None:
        """沒帶 weekdays＝不動排程。

        差別對舊版前端很要命：PWA 快取沒更新的那台送出的 payload 不含 weekdays，
        若當成「清空」，另一台裝置排好的星期就被它悄悄洗掉（Codex P1 指出的情境）。
        """
        created = _make_template(client, ex_id=exercise_id, name="全身日", weekdays=[1, 2])
        resp = client.put(
            f"/api/templates/{created['id']}",
            json={"name": "全身日", "exercises": [{"exercise_id": exercise_id, "default_sets": 3}]},
        )
        assert resp.json()["weekdays"] == [1, 2]

    def test_put_with_empty_weekdays_clears_schedule(self, client, exercise_id) -> None:
        """明確帶空陣列才是「清掉排程」。"""
        created = _make_template(client, ex_id=exercise_id, name="清空日", weekdays=[3])
        resp = client.put(
            f"/api/templates/{created['id']}",
            json={
                "name": "清空日",
                "exercises": [{"exercise_id": exercise_id, "default_sets": 3}],
                "weekdays": [],
            },
        )
        assert resp.json()["weekdays"] == []


class TestSettings:
    def test_default_when_never_set(self, client, exercise_id) -> None:
        assert client.get("/api/settings/weekly_target_days").json()["value"] == "4"

    def test_reading_default_does_not_persist(self, db_session) -> None:
        """第一次讀不該產生副作用——否則「沒設定過」與「設成預設值」就分不出來。"""
        assert settings_svc.get_setting(db_session, "weekly_target_days") == "4"
        rows = db_session.execute(text("SELECT COUNT(*) FROM app_settings")).scalar()
        assert rows == 0

    def test_set_and_read_back(self, client, exercise_id) -> None:
        resp = client.put("/api/settings/weekly_target_days", json={"value": "5"})
        assert resp.status_code == 200
        assert client.get("/api/settings/weekly_target_days").json()["value"] == "5"

    def test_overwrite(self, client, exercise_id) -> None:
        client.put("/api/settings/weekly_target_days", json={"value": "3"})
        client.put("/api/settings/weekly_target_days", json={"value": "6"})
        assert client.get("/api/settings/weekly_target_days").json()["value"] == "6"

    @pytest.mark.parametrize("bad", ["0", "8", "abc", "3.5"])
    def test_range_and_type_validated(self, client, exercise_id, bad) -> None:
        resp = client.put("/api/settings/weekly_target_days", json={"value": bad})
        assert resp.status_code == 400

    def test_unknown_key_rejected(self, client, exercise_id) -> None:
        """打錯字不該悄悄長出一個沒人讀的設定。"""
        assert client.get("/api/settings/nope").status_code == 400
        assert client.put("/api/settings/nope", json={"value": "1"}).status_code == 400


class TestScheduleToday:
    def test_shape(self, client, exercise_id) -> None:
        body = client.get("/api/schedule/today").json()
        assert body["weekday"] == date.today().isoweekday()
        assert body["weekly_target_days"] == 4
        assert len(body["week_days"]) == 7

    def test_today_lists_matching_templates(self, client, exercise_id) -> None:
        today_iso = date.today().isoweekday()
        _make_template(client, ex_id=exercise_id, name="今天的", weekdays=[today_iso], sets=4)
        _make_template(client, ex_id=exercise_id, name="別天的", weekdays=[today_iso % 7 + 1])
        names = [t["name"] for t in client.get("/api/schedule/today").json()["templates"]]
        assert names == ["今天的"]

    def test_multiple_templates_same_day(self, client, exercise_id) -> None:
        """一天可以排多份（早上推、晚上有氧）——Ryan 2026-07-29 決定。"""
        today_iso = date.today().isoweekday()
        _make_template(client, ex_id=exercise_id, name="早上推", weekdays=[today_iso])
        _make_template(client, ex_id=exercise_id, name="晚上有氧", weekdays=[today_iso])
        body = client.get("/api/schedule/today").json()
        assert [t["name"] for t in body["templates"]] == ["早上推", "晚上有氧"]

    def test_counts_come_from_template_contents(self, client, exercise_id) -> None:
        _make_template(
            client, ex_id=exercise_id, name="數量", weekdays=[date.today().isoweekday()], sets=5
        )
        one = client.get("/api/schedule/today").json()["templates"][0]
        assert one["exercise_count"] == 1
        assert one["set_count"] == 5


class TestWeekProgress:
    def _log(self, client, exercise_id: int, day: date) -> None:
        workout = client.post("/api/workouts", json={"date": day.isoformat()}).json()
        client.post(
            f"/api/workouts/{workout['id']}/sets",
            json={
                "client_uuid": f"uuid-{day.isoformat()}-{workout['id']}",
                "exercise_id": exercise_id,
                "set_number": 1,
                "weight_kg": 60,
                "reps": 8,
            },
        )

    def test_counts_distinct_days(self, client, exercise_id) -> None:
        start = schedule_svc.week_start(date.today())
        self._log(client, exercise_id, start)
        self._log(client, exercise_id, start)  # 同一天記兩次仍是一天
        self._log(client, exercise_id, start + timedelta(days=1))
        body = client.get("/api/schedule/today").json()
        assert body["week_done_days"] == 2
        assert body["week_days"][0] is True and body["week_days"][1] is True

    def test_empty_workout_does_not_count(self, client, exercise_id) -> None:
        """開了訓練卻一組都沒記，不算練過——首頁的進度不能被「開一下」灌水。"""
        start = schedule_svc.week_start(date.today())
        client.post("/api/workouts", json={"date": start.isoformat()})
        assert client.get("/api/schedule/today").json()["week_done_days"] == 0

    def test_soft_deleted_sets_do_not_count(self, client, exercise_id) -> None:
        start = schedule_svc.week_start(date.today())
        workout = client.post("/api/workouts", json={"date": start.isoformat()}).json()
        created = client.post(
            f"/api/workouts/{workout['id']}/sets",
            json={
                "client_uuid": "uuid-soft-del",
                "exercise_id": exercise_id,
                "set_number": 1,
                "weight_kg": 60,
                "reps": 8,
            },
        ).json()
        client.delete(f"/api/sets/{created['id']}")
        assert client.get("/api/schedule/today").json()["week_done_days"] == 0

    def test_last_week_does_not_leak_in(self, client, exercise_id) -> None:
        start = schedule_svc.week_start(date.today())
        self._log(client, exercise_id, start - timedelta(days=1))  # 上週日
        assert client.get("/api/schedule/today").json()["week_done_days"] == 0


class TestMigration:
    def test_weekdays_column_added_idempotently(self, tmp_path) -> None:
        """升級上來的舊 DB 沒有 weekdays 欄位；遷移要能重複跑不炸。"""
        engine = make_engine(str(tmp_path / "old.db"))
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE templates DROP COLUMN weekdays"))
        migrate_schema(engine)
        migrate_schema(engine)  # 第二次應為 no-op
        with engine.begin() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(templates)"))}
        assert "weekdays" in cols


class TestLastWorkout:
    """F81 首頁的「上次訓練」卡。"""

    def _log(self, client, exercise_id: int, day: date, uuid: str, template_id=None) -> int:
        body = {"date": day.isoformat()}
        if template_id is not None:
            body["template_id"] = template_id
        workout = client.post("/api/workouts", json=body).json()
        client.post(
            f"/api/workouts/{workout['id']}/sets",
            json={
                "client_uuid": uuid,
                "exercise_id": exercise_id,
                "set_number": 1,
                "weight_kg": 60,
                "reps": 8,
            },
        )
        return workout["id"]

    def test_none_when_no_history(self, client) -> None:
        assert client.get("/api/schedule/today").json()["last_workout"] is None

    def test_reports_latest_workout(self, client, exercise_id) -> None:
        self._log(client, exercise_id, date.today() - timedelta(days=3), "uuid-old-0001")
        self._log(client, exercise_id, date.today() - timedelta(days=1), "uuid-new-0001")
        last = client.get("/api/schedule/today").json()["last_workout"]
        assert last["date"] == (date.today() - timedelta(days=1)).isoformat()
        assert last["set_count"] == 1
        assert last["volume_kg"] == 480.0

    def test_template_name_resolved(self, client, exercise_id) -> None:
        template = _make_template(client, ex_id=exercise_id, name="拉背日")
        self._log(client, exercise_id, date.today(), "uuid-tpl-0001", template_id=template["id"])
        assert client.get("/api/schedule/today").json()["last_workout"]["template_name"] == "拉背日"

    def test_deleted_template_leaves_name_empty(self, client, exercise_id) -> None:
        """課表被刪掉不該讓首頁壞掉——workouts.template_id 沒有 FK，查不到就留空。"""
        template = _make_template(client, ex_id=exercise_id, name="會被刪的")
        self._log(client, exercise_id, date.today(), "uuid-del-0001", template_id=template["id"])
        client.delete(f"/api/templates/{template['id']}")
        assert client.get("/api/schedule/today").json()["last_workout"]["template_name"] is None

    def test_empty_workout_is_not_the_last(self, client, exercise_id) -> None:
        """今天開了訓練還沒記組時，卡片要講的仍是上一次真的有練的那次。"""
        self._log(client, exercise_id, date.today() - timedelta(days=2), "uuid-real-0001")
        client.post("/api/workouts", json={"date": date.today().isoformat()})
        last = client.get("/api/schedule/today").json()["last_workout"]
        assert last["date"] == (date.today() - timedelta(days=2)).isoformat()


class TestTemplateLastUsed:
    """F82 挑課表畫面：每份課表的「上次 M/D · X,XXX kg」。"""

    def _log(self, client, exercise_id: int, template_id: int, day: date, uuid: str,
             weight: float = 60) -> int:
        workout = client.post(
            "/api/workouts", json={"date": day.isoformat(), "template_id": template_id}
        ).json()
        client.post(
            f"/api/workouts/{workout['id']}/sets",
            json={
                "client_uuid": uuid,
                "exercise_id": exercise_id,
                "set_number": 1,
                "weight_kg": weight,
                "reps": 8,
            },
        )
        return workout["id"]

    def test_none_when_never_used(self, client, exercise_id) -> None:
        _make_template(client, ex_id=exercise_id, name="沒用過")
        row = client.get("/api/templates").json()[0]
        assert row["last_used_date"] is None
        assert row["last_volume_kg"] is None

    def test_reports_latest_use(self, client, exercise_id) -> None:
        template = _make_template(client, ex_id=exercise_id, name="推胸日")
        self._log(client, exercise_id, template["id"], date(2026, 7, 20), "uuid-lu-old", 50)
        self._log(client, exercise_id, template["id"], date(2026, 7, 27), "uuid-lu-new", 60)
        row = client.get("/api/templates").json()[0]
        assert row["last_used_date"] == "2026-07-27"
        assert row["last_volume_kg"] == 480.0  # 只算最後那次，不是全部加總

    def test_each_template_independent(self, client, exercise_id) -> None:
        a = _make_template(client, ex_id=exercise_id, name="A")
        b = _make_template(client, ex_id=exercise_id, name="B")
        self._log(client, exercise_id, a["id"], date(2026, 7, 20), "uuid-lu-a")
        self._log(client, exercise_id, b["id"], date(2026, 7, 25), "uuid-lu-b")
        rows = {t["name"]: t["last_used_date"] for t in client.get("/api/templates").json()}
        assert rows == {"A": "2026-07-20", "B": "2026-07-25"}

    def test_soft_deleted_sets_excluded(self, client, exercise_id) -> None:
        """整場都被刪光的訓練不算用過——否則卡片會顯示一個查不到東西的日期。"""
        template = _make_template(client, ex_id=exercise_id, name="全刪")
        workout_id = self._log(
            client, exercise_id, template["id"], date(2026, 7, 20), "uuid-lu-del"
        )
        set_id = client.get(f"/api/workouts/{workout_id}").json()["sets"][0]["id"]
        client.delete(f"/api/sets/{set_id}")
        assert client.get("/api/templates").json()[0]["last_used_date"] is None

    def test_free_workout_not_attributed(self, client, exercise_id) -> None:
        """自由訓練（template_id 為 null）不該算到任何一份課表頭上。"""
        template = _make_template(client, ex_id=exercise_id, name="沒用過")
        workout = client.post("/api/workouts", json={"date": date.today().isoformat()}).json()
        client.post(
            f"/api/workouts/{workout['id']}/sets",
            json={
                "client_uuid": "uuid-lu-free",
                "exercise_id": exercise_id,
                "set_number": 1,
                "weight_kg": 60,
                "reps": 8,
            },
        )
        assert template["id"]  # 課表存在但沒被用過
        assert client.get("/api/templates").json()[0]["last_used_date"] is None


class TestDeletedTemplateIdReuse:
    """SQLite 的 INTEGER PRIMARY KEY 會重用被刪掉的最大 id。

    刪掉最後一份課表再建一份新的，新課表會拿到同一個 id，而歷史 workout 仍存著那個數字——
    若只靠 id 比對，新課表就會繼承前一份的訓練歷史（Codex 2026-07-29 P2）。

    **F154 起課表改軟刪**（tombstone 要同步給另一台裝置），被刪的列還在，id 因此不再被重用，
    這個 bug 從根上消失。兩條測試改成釘住「id 不重用」與「新課表看不到舊歷史」——
    後者是使用者真正看得到的那一面，不論 id 怎麼配都必須成立。
    """

    def _log(self, client, exercise_id: int, template_id: int, uuid: str) -> None:
        workout = client.post(
            "/api/workouts",
            json={"date": date.today().isoformat(), "template_id": template_id},
        ).json()
        client.post(
            f"/api/workouts/{workout['id']}/sets",
            json={
                "client_uuid": uuid,
                "exercise_id": exercise_id,
                "set_number": 1,
                "weight_kg": 60,
                "reps": 8,
            },
        )

    def test_new_template_does_not_inherit_history(self, client, exercise_id) -> None:
        old = _make_template(client, ex_id=exercise_id, name="舊課表")
        self._log(client, exercise_id, old["id"], "uuid-reuse-001")
        client.delete(f"/api/templates/{old['id']}")

        new = _make_template(client, ex_id=exercise_id, name="新課表")
        assert new["id"] != old["id"], "軟刪之後 id 不該被重用"

        row = [t for t in client.get("/api/templates").json() if t["id"] == new["id"]][0]
        assert row["last_used_date"] is None
        assert row["last_volume_kg"] is None

    def test_home_last_workout_does_not_borrow_new_name(self, client, exercise_id) -> None:
        """首頁的「上次訓練」也一樣——不該把舊訓練標上新課表的名字。"""
        old = _make_template(client, ex_id=exercise_id, name="舊課表")
        self._log(client, exercise_id, old["id"], "uuid-reuse-002")
        client.delete(f"/api/templates/{old['id']}")
        new = _make_template(client, ex_id=exercise_id, name="新課表")
        assert new["id"] != old["id"]

        last = client.get("/api/schedule/today").json()["last_workout"]
        assert last is not None
        assert last["template_name"] is None


class TestLastSetValues:
    """F83 今日菜單：一次取多個動作的「上次」代表值。"""

    def _log(self, client, exercise_id: int, day: date, uuid: str,
             weight: float, reps: int, set_number: int = 1) -> int:
        workout = client.post("/api/workouts", json={"date": day.isoformat()}).json()
        client.post(
            f"/api/workouts/{workout['id']}/sets",
            json={
                "client_uuid": uuid,
                "exercise_id": exercise_id,
                "set_number": set_number,
                "weight_kg": weight,
                "reps": reps,
            },
        )
        return workout["id"]

    def test_empty_when_no_history(self, client, exercise_id) -> None:
        assert client.get(f"/api/exercises/last-set-values?ids={exercise_id}").json() == []

    def test_returns_latest_workout_values(self, client, exercise_id) -> None:
        self._log(client, exercise_id, date(2026, 7, 20), "uuid-lsv-old", 50, 10)
        self._log(client, exercise_id, date(2026, 7, 27), "uuid-lsv-new", 60, 8)
        row = client.get(f"/api/exercises/last-set-values?ids={exercise_id}").json()[0]
        assert (row["weight_kg"], row["reps"]) == (60.0, 8)

    def test_uses_last_set_of_that_workout(self, client, exercise_id) -> None:
        """同一次訓練有多組時，代表值是最後一組（那才是你上次收在哪個重量）。"""
        workout = client.post(
            "/api/workouts", json={"date": date(2026, 7, 27).isoformat()}
        ).json()
        for n, weight in ((1, 50.0), (2, 55.0), (3, 60.0)):
            client.post(
                f"/api/workouts/{workout['id']}/sets",
                json={
                    "client_uuid": f"uuid-lsv-multi-{n}",
                    "exercise_id": exercise_id,
                    "set_number": n,
                    "weight_kg": weight,
                    "reps": 8,
                },
            )
        row = client.get(f"/api/exercises/last-set-values?ids={exercise_id}").json()[0]
        assert row["weight_kg"] == 60.0

    def test_exclude_workout_keeps_previous_session(self, client, exercise_id) -> None:
        """排除進行中的訓練——否則「上次」會變成今天剛記的那組（同 F32 的老問題）。"""
        self._log(client, exercise_id, date(2026, 7, 20), "uuid-lsv-prev", 50, 10)
        current = self._log(client, exercise_id, date.today(), "uuid-lsv-cur", 80, 5)
        url = f"/api/exercises/last-set-values?ids={exercise_id}&exclude_workout={current}"
        row = client.get(url).json()[0]
        assert (row["weight_kg"], row["reps"]) == (50.0, 10)

    def test_batch_covers_several_exercises(self, client, exercise_id) -> None:
        second = client.post(
            "/api/exercises",
            json={"name_zh": "臥推", "name_en": "Bench Press", "muscle_group": "胸"},
        ).json()["id"]
        ids = [exercise_id, second]
        self._log(client, ids[0], date(2026, 7, 20), "uuid-lsv-b1", 40, 12)
        self._log(client, ids[1], date(2026, 7, 21), "uuid-lsv-b2", 70, 6)
        rows = client.get(f"/api/exercises/last-set-values?ids={ids[0]},{ids[1]}").json()
        got = {r["exercise_id"]: (r["weight_kg"], r["reps"]) for r in rows}
        assert got == {ids[0]: (40.0, 12), ids[1]: (70.0, 6)}

    def test_soft_deleted_ignored(self, client, exercise_id) -> None:
        workout_id = self._log(client, exercise_id, date(2026, 7, 27), "uuid-lsv-del", 99, 1)
        set_id = client.get(f"/api/workouts/{workout_id}").json()["sets"][0]["id"]
        client.delete(f"/api/sets/{set_id}")
        assert client.get(f"/api/exercises/last-set-values?ids={exercise_id}").json() == []


class TestWorkoutCreatedAt:
    def test_detail_exposes_created_at(self, client) -> None:
        """F83「已練 N 分」用伺服器時間——app 被回收後前端記的開始時間就沒了。"""
        workout = client.post("/api/workouts", json={}).json()
        assert client.get(f"/api/workouts/{workout['id']}").json()["created_at"] is not None
