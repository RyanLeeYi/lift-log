"""F133 ②④：兩條寫入路徑同時記組時，組號不得撞號，且都要寫入成功。

為什麼值得測：`_next_set_number()` 是 SELECT MAX 再 INSERT，兩個請求同時跑到中間那一刻
就會讀到同一個值（codex review P1 實測重現，F131 時代靠行程內鎖擋）。F133 把防線換成
DB 層 (workout_id, exercise_id, set_number) 唯一約束＋撞號重試——這條測試驗的就是重試
真的有效：兩執行緒同時進場，兩列組號不同、都寫入成功。**拿掉重試這條測試就會 fail**
（撞號的那條會在耗盡重試後收到 409 ConflictError，執行緒內會有例外，下方 errors 斷言抓得到）。
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
