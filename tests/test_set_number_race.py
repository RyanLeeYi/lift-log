"""F133 ①②④：sets 組號唯一約束——併發配號、決定性重試、軟刪重用三個角度各自釘一條。

`test_concurrent_log_set_never_reuses_a_set_number` 驗的是併發配號本身：`_next_set_number()`
是 SELECT MAX 再 INSERT，兩個請求同時跑到中間那一刻就會讀到同一個值（codex review P1 實測
重現，F131 時代靠行程內鎖擋）。F133 把防線換成 DB 層 (workout_id, exercise_id, set_number)
唯一約束＋撞號重試——這條測試驗的就是兩執行緒同時進場，兩列組號不同、都寫入成功。

但這條測試本身不是決定性的：SQLite 寫鎖序列化下，thread B 的 SELECT MAX 常常已經看得到
thread A 的 commit，兩邊天生就配到不同號，永遠不會真的撞號——拿掉重試迴圈它照樣綠。
acceptance ④ 明文要求「移除重試會 fail」，所以另外補
`test_retry_recovers_when_assigned_number_is_already_taken`：monkeypatch `_next_set_number`
逼出撞號，不靠執行緒排程運氣。
"""

import threading
from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from app.models import Exercise, Workout, WorkoutSet
from app.schemas import SetCreate
from app.services import workouts as svc
from app.services.workouts import log_set, soft_delete_set


def test_concurrent_log_set_never_reuses_a_set_number(session_factory: sessionmaker) -> None:
    with session_factory() as setup:
        setup.add(Exercise(name_zh="臥推", name_en="Bench Press", muscle_group="胸"))
        setup.add(Workout(date=date(2026, 8, 5)))
        setup.commit()
        workout_id = setup.query(Workout).one().id
        exercise_id = setup.query(Exercise).one().id

    start = threading.Barrier(2)
    errors: list[Exception] = []

    def write(tag: str) -> None:
        with session_factory() as s:
            data = SetCreate(client_uuid=tag, exercise_id=exercise_id, weight_kg=40, reps=5)
            start.wait()  # 兩條路徑卡在同一刻進場，才逼得出 SELECT MAX 的競賽
            try:
                log_set(s, workout_id, data)
            except Exception as exc:  # noqa: BLE001 - 就是要把重試失敗的例外收集起來斷言
                errors.append(exc)

    tags = ("uuid-aaaa-0001", "uuid-bbbb-0002")
    threads = [threading.Thread(target=write, args=(tag,)) for tag in tags]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"重試沒能救回撞號的寫入：{errors}"
    with session_factory() as check:
        numbers = sorted(s.set_number for s in check.query(WorkoutSet).all())
    assert numbers == [1, 2], f"組號撞號了：{numbers}"


def test_retry_recovers_when_assigned_number_is_already_taken(
    session_factory: sessionmaker, monkeypatch
) -> None:
    """acceptance ④ 的決定性版本：不靠執行緒排程碰運氣，直接證明重試迴圈真的有在做事。

    monkeypatch `_next_set_number`：第一次回傳一個已被佔用的號（逼出第一次 commit 撞
    UNIQUE），第二次才回真正的下一號。重試迴圈應該吃下第一次的撞號、重新配號後成功寫入。
    移除重試（把 server 配號路徑的重試上限固定成 1）這條測試就會 fail：第一次 commit
    撞號直接 raise，不會有第二次機會配到號 2。
    """
    with session_factory() as setup:
        setup.add(Exercise(name_zh="臥推", name_en="Bench Press", muscle_group="胸"))
        setup.add(Workout(date=date(2026, 8, 5)))
        setup.commit()
        workout_id = setup.query(Workout).one().id
        exercise_id = setup.query(Exercise).one().id

    with session_factory() as s:
        taken = SetCreate(
            client_uuid="uuid-eeee-0005",
            exercise_id=exercise_id,
            weight_kg=40,
            reps=5,
            set_number=1,
        )
        log_set(s, workout_id, taken)

    real_next_set_number = svc._next_set_number
    calls = {"n": 0}

    def fake_next_set_number(session: Session, workout_id: int, exercise_id: int) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            return 1  # 假裝配到已被佔用的號，逼出第一次 commit 撞 UNIQUE
        return real_next_set_number(session, workout_id, exercise_id)

    monkeypatch.setattr(svc, "_next_set_number", fake_next_set_number)

    with session_factory() as s:
        data = SetCreate(
            client_uuid="uuid-ffff-0006", exercise_id=exercise_id, weight_kg=40, reps=5
        )
        workout_set, created = log_set(s, workout_id, data)

    assert created is True
    assert workout_set.set_number == 2
    assert calls["n"] == 2


def test_soft_deleted_set_number_can_be_reused_by_another_client_uuid(
    session_factory: sessionmaker,
) -> None:
    """F133 ①：partial unique index 只擋未軟刪列——軟刪後重用組號是既有語意（F32），
    不得被唯一約束誤傷。這條釘住 `sqlite_where` 那個條件：拿掉它（索引變成全表 unique）
    現有測試不會抓到，因為既有測試都只驗「server 跳過軟刪組號」，沒人會去重用它。
    """
    with session_factory() as setup:
        setup.add(Exercise(name_zh="臥推", name_en="Bench Press", muscle_group="胸"))
        setup.add(Workout(date=date(2026, 8, 5)))
        setup.commit()
        workout_id = setup.query(Workout).one().id
        exercise_id = setup.query(Exercise).one().id

    with session_factory() as s:
        first_data = SetCreate(
            client_uuid="uuid-cccc-0003",
            exercise_id=exercise_id,
            weight_kg=40,
            reps=5,
            set_number=1,
        )
        first_set, _ = log_set(s, workout_id, first_data)
        soft_delete_set(s, first_set.id)

    with session_factory() as s:
        second_data = SetCreate(
            client_uuid="uuid-dddd-0004",
            exercise_id=exercise_id,
            weight_kg=40,
            reps=5,
            set_number=1,
        )
        second_set, created = log_set(s, workout_id, second_data)

    assert created is True
    assert second_set.set_number == 1
