"""F131 ③：兩條寫入路徑同時記組時，組號不得撞號。

為什麼值得測：`_next_set_number()` 是 SELECT MAX 再 INSERT，兩個請求同時跑到中間那一刻
就會讀到同一個值（codex review P1 實測重現）。組號沒有唯一約束擋，撞了不會報錯，
只會在訓練資料裡留下兩筆同組號——正是 F131 開第二條寫入路徑要避免的事。
"""

import threading
from datetime import date

from sqlalchemy.orm import sessionmaker

from app.models import Exercise, Workout, WorkoutSet
from app.schemas import SetCreate
from app.services.workouts import log_set


def test_concurrent_log_set_never_reuses_a_set_number(session_factory: sessionmaker) -> None:
    with session_factory() as setup:
        setup.add(Exercise(name_zh="臥推", name_en="Bench Press", muscle_group="胸"))
        setup.add(Workout(date=date(2026, 8, 5)))
        setup.commit()
        workout_id = setup.query(Workout).one().id
        exercise_id = setup.query(Exercise).one().id

    start = threading.Barrier(2)

    def write(tag: str) -> None:
        with session_factory() as s:
            data = SetCreate(client_uuid=tag, exercise_id=exercise_id, weight_kg=40, reps=5)
            start.wait()  # 兩條路徑卡在同一刻進場，才逼得出 SELECT MAX 的競賽
            log_set(s, workout_id, data)

    tags = ("uuid-aaaa-0001", "uuid-bbbb-0002")
    threads = [threading.Thread(target=write, args=(tag,)) for tag in tags]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with session_factory() as check:
        numbers = sorted(s.set_number for s in check.query(WorkoutSet).all())
    assert numbers == [1, 2], f"組號撞號了：{numbers}"
