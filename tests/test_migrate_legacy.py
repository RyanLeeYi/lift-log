"""F149：既有單庫 liftlog.db 資料遷進 user data DB。

六個情境對應完成條件：空 target 全量遷移、重跑第二次全 skip、自然鍵撞且內容不同進
conflicts 不寫、dry-run 不產生檔案、rollback 還原、遷移後同步層有對應 SyncEntity
（併入全量遷移測試一起斷言）。另補三個查無 user／已關閉／target 未建的錯誤路徑。
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.control_db import make_control_session_factory
from app.control_models import User
from app.db import make_engine
from app.migrations import migrate_schema
from app.models import (
    AppSetting,
    Base,
    BodyMetric,
    DailyStatus,
    Exercise,
    Template,
    TemplateExercise,
    Workout,
    WorkoutSet,
)
from app.sync_models import SyncEntity
from scripts.migrate_legacy import main


def _open_session(db_path: Path):
    engine = make_engine(str(db_path))
    return engine, sessionmaker(bind=engine)()


def _build_legacy_db(tmp_path: Path) -> Path:
    """空白 domain schema，不灌種子動作——每個測試自己填想要的資料才好精準斷言。"""
    db_path = tmp_path / "liftlog.db"
    engine = make_engine(str(db_path))
    Base.metadata.create_all(engine)
    migrate_schema(engine)
    engine.dispose()
    return db_path


def _build_control_and_user(
    tmp_path: Path,
    *,
    google_sub: str = "sub-1",
    email: str = "ryan@example.com",
    status: str = "active",
) -> tuple[Path, Path, str]:
    """回傳 (control_db_path, user_data_dir, user_id)。不建 target db 檔案——留給呼叫端決定。"""
    control_path = tmp_path / "control.db"
    user_data_dir = tmp_path / "users"
    user_id = str(uuid4())
    factory = make_control_session_factory(str(control_path))
    with factory() as session:
        session.add(
            User(
                id=user_id,
                google_sub=google_sub,
                email=email,
                data_db_name=f"{user_id}.db",
                status=status,
                created_at=datetime(2026, 1, 1),
            )
        )
        session.commit()
    return control_path, user_data_dir, user_id


def _build_target_db(user_data_dir: Path, user_id: str) -> Path:
    """比照 test_backfill_sync 的空白 target：已用 Google 登入建立，但還沒種子動作以外的資料。"""
    user_data_dir.mkdir(exist_ok=True)
    db_path = user_data_dir / f"{user_id}.db"
    engine = make_engine(str(db_path))
    Base.metadata.create_all(engine)
    migrate_schema(engine)
    engine.dispose()
    return db_path


def _seed_full_legacy_dataset(db_path: Path) -> None:
    """湊齊六張表的相依鏈：exercises → template(children) → workout → sets，外加獨立兩張。"""
    engine, session = _open_session(db_path)
    squat = Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿", is_bodyweight=False)
    bench = Exercise(name_zh="臥推", name_en="BenchPress", muscle_group="胸", is_bodyweight=False)
    session.add_all([squat, bench])
    session.flush()

    template = Template(name="推力課表", weekdays="1,3,5")
    session.add(template)
    session.flush()
    session.add_all(
        [
            TemplateExercise(
                template_id=template.id, position=0, exercise_id=squat.id,
                default_sets=3, rest_hint_seconds=60,
            ),
            TemplateExercise(
                template_id=template.id, position=1, exercise_id=bench.id,
                default_sets=4, rest_hint_seconds=90,
            ),
        ]
    )

    workout = Workout(date=date(2026, 1, 5), template_id=template.id, note="早上")
    session.add(workout)
    session.flush()
    session.add_all(
        [
            WorkoutSet(
                client_uuid=str(uuid4()), workout_id=workout.id, exercise_id=squat.id,
                set_number=1, weight_kg=100.0, reps=5,
            ),
            WorkoutSet(
                client_uuid=str(uuid4()), workout_id=workout.id, exercise_id=bench.id,
                set_number=1, weight_kg=60.0, reps=8,
            ),
        ]
    )
    session.add(BodyMetric(date=date(2026, 1, 5), weight_kg=80.5, body_fat_pct=18.2))
    session.add(DailyStatus(date=date(2026, 1, 5), energy=4, sleep_quality=3, note="有點累"))
    session.commit()
    session.close()
    engine.dispose()


def _parse_summary(output: str) -> dict:
    return json.loads(output[output.index("{") :])


def _extract_backup_path(output: str) -> Path:
    for line in output.splitlines():
        if "已備份（回滾用）：" in line:
            return Path(line.split("已備份（回滾用）：", 1)[1].strip())
    raise AssertionError(f"輸出裡找不到備份路徑：{output}")


def test_full_migration_into_empty_target(tmp_path: Path, capsys) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    _seed_full_legacy_dataset(legacy_path)
    control_path, user_data_dir, user_id = _build_control_and_user(tmp_path)
    target_path = _build_target_db(user_data_dir, user_id)

    exit_code = main(
        [
            "--legacy-db", str(legacy_path),
            "--google-sub", "sub-1",
            "--control-db", str(control_path),
            "--user-data-dir", str(user_data_dir),
        ]
    )
    assert exit_code == 0

    summary = _parse_summary(capsys.readouterr().out)
    assert summary["exercises"]["migrated"] == 2
    assert summary["templates"]["migrated"] == 1
    assert summary["workouts"]["migrated"] == 1
    assert summary["sets"]["migrated"] == 2
    assert summary["body_metrics"]["migrated"] == 1
    assert summary["daily_status"]["migrated"] == 1
    for table_report in summary.values():
        assert table_report["conflicts"] == 0
        expected_after = table_report["before_target"] + table_report["migrated"]
        assert table_report["after_target"] == expected_after

    engine, session = _open_session(target_path)
    assert session.scalar(select(func.count()).select_from(TemplateExercise)) == 2
    sync_entity_total = session.scalar(select(func.count()).select_from(SyncEntity))
    assert sync_entity_total == 8, "六張表共 8 筆都要有 sync entity"
    session.close()
    engine.dispose()


def test_rerun_is_idempotent(tmp_path: Path, capsys) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    _seed_full_legacy_dataset(legacy_path)
    control_path, user_data_dir, user_id = _build_control_and_user(tmp_path)
    _build_target_db(user_data_dir, user_id)
    argv = [
        "--legacy-db", str(legacy_path),
        "--google-sub", "sub-1",
        "--control-db", str(control_path),
        "--user-data-dir", str(user_data_dir),
    ]

    assert main(argv) == 0
    first_summary = _parse_summary(capsys.readouterr().out)

    # backup_before_run 的快照目錄用秒級時間戳命名（backfill_sync.py 既有行為，不在本次改動範圍）：
    # 同一秒內重跑會撞 VACUUM INTO 的目的檔已存在，跨秒才是重跑的真實情境。
    time.sleep(1.1)
    assert main(argv) == 0
    second_summary = _parse_summary(capsys.readouterr().out)

    for table, report in second_summary.items():
        assert report["migrated"] == 0, table
        assert report["conflicts"] == 0, table
        assert report["after_target"] == first_summary[table]["after_target"], table


def test_natural_key_conflict_recorded_and_not_overwritten(tmp_path: Path, capsys) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    engine, session = _open_session(legacy_path)
    session.add(Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿", is_bodyweight=False))
    session.commit()
    session.close()
    engine.dispose()

    control_path, user_data_dir, user_id = _build_control_and_user(tmp_path)
    target_path = _build_target_db(user_data_dir, user_id)
    engine, session = _open_session(target_path)
    session.add(Exercise(name_zh="深蹲", name_en="Squat", muscle_group="臀", is_bodyweight=False))
    session.commit()
    session.close()
    engine.dispose()

    exit_code = main(
        [
            "--legacy-db", str(legacy_path),
            "--google-sub", "sub-1",
            "--control-db", str(control_path),
            "--user-data-dir", str(user_data_dir),
        ]
    )
    assert exit_code == 0

    summary = _parse_summary(capsys.readouterr().out)
    exercises = summary["exercises"]
    assert exercises["migrated"] == 0
    assert exercises["conflicts"] == 1
    detail = exercises["conflict_detail"][0]
    assert detail["legacy"]["muscle_group"] == "腿"
    assert detail["target"]["muscle_group"] == "臀"

    engine, session = _open_session(target_path)
    kept = session.scalar(select(Exercise).where(Exercise.name_zh == "深蹲"))
    assert kept.muscle_group == "臀", "target 既有列必須勝出，不得被 legacy 覆寫"
    session.close()
    engine.dispose()


def test_dry_run_creates_no_files(tmp_path: Path, capsys) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    engine, session = _open_session(legacy_path)
    session.add(Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿", is_bodyweight=False))
    session.commit()
    session.close()
    engine.dispose()

    control_path, user_data_dir, user_id = _build_control_and_user(tmp_path)
    target_path = _build_target_db(user_data_dir, user_id)

    exit_code = main(
        [
            "--legacy-db", str(legacy_path),
            "--google-sub", "sub-1",
            "--control-db", str(control_path),
            "--user-data-dir", str(user_data_dir),
            "--dry-run",
        ]
    )
    assert exit_code == 0

    summary = _parse_summary(capsys.readouterr().out)
    assert summary["exercises"]["migrated"] == 1, "dry-run 仍要試算摘要"
    assert not (target_path.parent / "backfill_backups").exists(), "--dry-run 不得產生備份快照"

    engine, session = _open_session(target_path)
    assert session.scalar(select(func.count()).select_from(Exercise)) == 0, "--dry-run 不該真的寫入"
    session.close()
    engine.dispose()


def test_rollback_restores_target(tmp_path: Path, capsys) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    engine, session = _open_session(legacy_path)
    session.add(Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿", is_bodyweight=False))
    session.commit()
    session.close()
    engine.dispose()

    control_path, user_data_dir, user_id = _build_control_and_user(tmp_path)
    target_path = _build_target_db(user_data_dir, user_id)
    argv_common = [
        "--google-sub", "sub-1",
        "--control-db", str(control_path),
        "--user-data-dir", str(user_data_dir),
    ]

    assert main(["--legacy-db", str(legacy_path), *argv_common]) == 0
    backup_path = _extract_backup_path(capsys.readouterr().out)
    assert backup_path.is_file()

    engine, session = _open_session(target_path)
    assert session.scalar(select(func.count()).select_from(Exercise)) == 1
    session.close()
    engine.dispose()

    exit_code = main(["--rollback", str(backup_path), *argv_common])
    assert exit_code == 0
    counts = _parse_summary(capsys.readouterr().out)
    assert counts["before"]["exercises"] == 1
    assert counts["after"]["exercises"] == 0

    engine, session = _open_session(target_path)
    restored_total = session.scalar(select(func.count()).select_from(Exercise))
    assert restored_total == 0, "回滾後要恢復遷移前的狀態"
    session.close()
    engine.dispose()


def test_lookup_by_email(tmp_path: Path, capsys) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    control_path, user_data_dir, user_id = _build_control_and_user(
        tmp_path, email="ryan@example.com"
    )
    _build_target_db(user_data_dir, user_id)

    exit_code = main(
        [
            "--legacy-db", str(legacy_path),
            "--email", "ryan@example.com",
            "--control-db", str(control_path),
            "--user-data-dir", str(user_data_dir),
            "--dry-run",
        ]
    )
    assert exit_code == 0


def test_missing_user_returns_error(tmp_path: Path) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    control_path, user_data_dir, _ = _build_control_and_user(tmp_path)

    exit_code = main(
        [
            "--legacy-db", str(legacy_path),
            "--google-sub", "no-such-sub",
            "--control-db", str(control_path),
            "--user-data-dir", str(user_data_dir),
        ]
    )
    assert exit_code != 0


def test_closed_user_returns_error(tmp_path: Path) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    control_path, user_data_dir, _ = _build_control_and_user(tmp_path, status="closed")

    exit_code = main(
        [
            "--legacy-db", str(legacy_path),
            "--google-sub", "sub-1",
            "--control-db", str(control_path),
            "--user-data-dir", str(user_data_dir),
        ]
    )
    assert exit_code != 0


def test_missing_target_db_returns_error(tmp_path: Path) -> None:
    legacy_path = _build_legacy_db(tmp_path)
    control_path, user_data_dir, _ = _build_control_and_user(tmp_path)
    user_data_dir.mkdir(exist_ok=True)  # 沒建 target db 檔案——模擬 user 還沒用 Google 登入過

    exit_code = main(
        [
            "--legacy-db", str(legacy_path),
            "--google-sub", "sub-1",
            "--control-db", str(control_path),
            "--user-data-dir", str(user_data_dir),
        ]
    )
    assert exit_code != 0


def test_app_settings_migrate_and_never_overwrite_target(tmp_path: Path, capsys) -> None:
    """使用者調過的設定要跟著搬；target 已經有同一個 key 時仍然是 target 勝出。"""
    legacy_path = _build_legacy_db(tmp_path)
    engine, session = _open_session(legacy_path)
    session.add_all(
        [
            AppSetting(key="weekly_target_days", value="4", updated_at=datetime(2026, 1, 5)),
            AppSetting(key="default_rest_seconds", value="90", updated_at=datetime(2026, 1, 5)),
        ]
    )
    session.commit()
    session.close()
    engine.dispose()

    control_path, user_data_dir, user_id = _build_control_and_user(tmp_path)
    target_path = _build_target_db(user_data_dir, user_id)
    engine, session = _open_session(target_path)
    session.add(AppSetting(key="weekly_target_days", value="3", updated_at=datetime(2026, 2, 1)))
    session.commit()
    session.close()
    engine.dispose()

    exit_code = main(
        [
            "--legacy-db", str(legacy_path),
            "--google-sub", "sub-1",
            "--control-db", str(control_path),
            "--user-data-dir", str(user_data_dir),
        ]
    )
    assert exit_code == 0

    report = _parse_summary(capsys.readouterr().out)["app_settings"]
    assert report["migrated"] == 1
    assert report["conflicts"] == 1

    engine, session = _open_session(target_path)
    assert session.get(AppSetting, "weekly_target_days").value == "3", "target 既有值不得被覆寫"
    assert session.get(AppSetting, "default_rest_seconds").value == "90"
    session.close()
    engine.dispose()
