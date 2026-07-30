"""F93：把測試站的 DB 灌成一份看得出畫面長相的假資料。

**只對測試站的 DB 動手**——執行前會確認目標路徑不是正式站的 `liftlog.db`，
不是就直接中止。灌假資料的腳本誤指到正式 DB 是不可逆的。

跑法（在 repo 根目錄）：
    PYTHONUTF8=1 uv run python scripts/seed_dev.py            # 沿用 .env.dev 的 LIFTLOG_DB
    PYTHONUTF8=1 uv run python scripts/seed_dev.py --reset    # 先清空再灌

假資料的形狀刻意涵蓋這些畫面會用到的東西：跨度夠長的體重體脂（時間窗 chips 才有東西可選）、
同一個動作的多次紀錄且有 PR（動作表現的長條圖與 ★）、有課表與自由訓練混合的日子（日曆熱力分階）。
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sqlalchemy.orm import Session  # noqa: E402

from app.db import make_engine  # noqa: E402
from app.migrations import migrate_schema  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    BodyMetric,
    Exercise,
    Template,
    TemplateExercise,
    Workout,
    WorkoutSet,
)

PROD_DB_NAMES = {"liftlog.db"}


def resolve_db_path() -> str:
    """優先用環境變數；沒有就讀 .env.dev。不讀 .env——那是正式站的。"""
    if os.environ.get("LIFTLOG_DB"):
        return os.environ["LIFTLOG_DB"]
    env_dev = REPO / ".env.dev"
    if env_dev.exists():
        for line in env_dev.read_text(encoding="utf-8").splitlines():
            if line.startswith("LIFTLOG_DB="):
                return line.partition("=")[2].strip()
    raise SystemExit("找不到測試站的 LIFTLOG_DB（設環境變數或建 .env.dev）")


def guard(db_path: str) -> None:
    name = Path(db_path).name
    if name in PROD_DB_NAMES:
        raise SystemExit(
            f"拒絕執行：目標是 {name}，那是正式站的資料庫。\n"
            f"這支腳本只能對測試站的 DB 動手。"
        )


EXERCISES = [
    ("槓鈴臥推", "Bench Press", "胸", False),
    ("槓鈴深蹲", "Back Squat", "腿", False),
    ("硬舉", "Deadlift", "背", False),
    ("引體向上", "Pull Up", "背", True),
    ("肩推", "Overhead Press", "肩", False),
]


def seed(session: Session, today: date) -> dict[str, int]:
    rng = random.Random(93)  # 固定種子：每次 seed 出來的畫面一致，回歸比對才有意義

    exercises = [
        Exercise(name_zh=zh, name_en=en, muscle_group=mg, is_bodyweight=bw)
        for zh, en, mg, bw in EXERCISES
    ]
    session.add_all(exercises)
    session.flush()

    upper = Template(name="上半身", weekdays="1,4")
    lower = Template(name="下半身", weekdays="2,5")
    session.add_all([upper, lower])
    session.flush()
    for pos, ex in enumerate([exercises[0], exercises[4], exercises[3]], start=1):
        session.add(TemplateExercise(
            template_id=upper.id, position=pos, exercise_id=ex.id,
            default_sets=3, rest_hint_seconds=90,
        ))
    for pos, ex in enumerate([exercises[1], exercises[2]], start=1):
        session.add(TemplateExercise(
            template_id=lower.id, position=pos, exercise_id=ex.id,
            default_sets=4, rest_hint_seconds=120,
        ))

    # 體重體脂：120 天、每 3~4 天一筆，緩降——時間窗 chips 才有多個檔位可用
    weight, fat, day, metrics = 82.0, 19.5, today - timedelta(days=120), 0
    while day <= today:
        session.add(BodyMetric(
            date=day,
            weight_kg=round(weight + rng.uniform(-0.3, 0.3), 1),
            body_fat_pct=round(fat + rng.uniform(-0.2, 0.2), 1),
        ))
        metrics += 1
        weight -= rng.uniform(0.05, 0.2)
        fat -= rng.uniform(0.02, 0.08)
        day += timedelta(days=rng.choice([3, 3, 4]))

    # 訓練：過去 100 天內每週 2–3 次，臥推逐步進步且有幾次 PR
    workouts = sets_n = 0
    bench_top = 52.5
    day = today - timedelta(days=100)
    while day <= today:
        if day.isoweekday() in (1, 4, 6):
            template = upper if day.isoweekday() != 6 else None
            started = datetime.combine(day, datetime.min.time()) + timedelta(hours=19)
            workout = Workout(
                date=day,
                template_id=template.id if template else None,
                created_at=started,
                ended_at=started + timedelta(hours=1, minutes=15),
            )
            session.add(workout)
            session.flush()
            workouts += 1
            picks = [exercises[0], exercises[4]] if template else [exercises[1]]
            for ex in picks:
                base = bench_top if ex is exercises[0] else 40.0
                for n in range(1, 4):
                    session.add(WorkoutSet(
                        client_uuid=f"seed-{workout.id}-{ex.id}-{n}",
                        workout_id=workout.id,
                        exercise_id=ex.id,
                        set_number=n,
                        weight_kg=round(base - (n - 1) * 2.5, 1),
                        reps=rng.choice([5, 6, 8]),
                        rpe=rng.choice([6, 7, 8]),
                        rest_seconds=rng.choice([80, 90, 110]),
                        created_at=workout.created_at + timedelta(minutes=6 * n),
                    ))
                    sets_n += 1
            if rng.random() < 0.25:
                bench_top += 2.5  # 偶爾進步 → 動作表現頁看得到 PR
        day += timedelta(days=1)

    session.commit()
    return {"exercises": len(exercises), "templates": 2, "workouts": workouts,
            "sets": sets_n, "body_metrics": metrics}


def main() -> int:
    parser = argparse.ArgumentParser(description="灌測試站假資料")
    parser.add_argument("--reset", action="store_true", help="先刪掉既有 DB 再重建")
    args = parser.parse_args()

    db_path = resolve_db_path()
    guard(db_path)

    if args.reset and Path(db_path).exists():
        Path(db_path).unlink()
        print(f"已刪除舊的 {Path(db_path).name}")

    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    migrate_schema(engine)
    with Session(engine) as session:
        if session.query(Exercise).count() > 0:
            print("這顆 DB 已經有資料了——要重灌請加 --reset")
            return 1
        stats = seed(session, date.today())

    print(f"已灌入 {Path(db_path).name}：")
    for key, value in stats.items():
        print(f"  {key:14} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
