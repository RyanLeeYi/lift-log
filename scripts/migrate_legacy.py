"""F149：把 cutover 前的 legacy 單庫 `liftlog.db` domain 資料遷進某個 user 的 data DB。

遷移方向 legacy → target，**target 既有列一律勝出**：自然鍵已存在就不覆寫，天然冪等
（重跑第二次全部 skip）；自然鍵存在但內容不同不寫，列進 conflicts 明細供人工處理。
外鍵一律重新解析成 target 的 id——legacy 的整數 id 只在遷移過程內部當查表 key 用。

寫完 domain 列之後，同一個 run 內呼叫 `scripts/backfill_sync.py` 的 `run_backfill()` 補齊
同步層（D17：domain 表是唯一事實來源，同步層是版本簿），不自己組 sync payload。

用法（repo 根目錄）：
    uv run python scripts/migrate_legacy.py --legacy-db ./liftlog.db [--dry-run]
    uv run python scripts/migrate_legacy.py --rollback <snapshot 路徑>

**目標 user 的識別值不從命令列取得**（F149 ③：不得留在指令歷史或 process table）。
依序從這兩個地方拿，二選一即可：

1. 環境變數 `LIFTLOG_MIGRATE_GOOGLE_SUB`，或 `LIFTLOG_MIGRATE_EMAIL`
2. 互動式安全輸入——沒設環境變數且 stdin 是 TTY 時，用不回顯的提示字元讀 Google sub

非互動環境又沒設環境變數就直接中止，不 fallback 到命令列參數。查不到 user 時的錯誤訊息
只說用了哪個來源，**不回印識別值本身**。目標 user 由 control DB 的 `User` 表查出，
data DB 路徑一律走 `app.db.canonical_user_db_path`。

非 dry-run 開始寫入前，會先用 `backfill_sync.backup_before_run` 對 target DB 做快照備份，
快照路徑印在輸出最前面——那就是 `--rollback` 要用的路徑。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.config import Settings  # noqa: E402
from app.control_db import make_control_session_factory  # noqa: E402
from app.control_models import User  # noqa: E402
from app.db import UserDataUnavailable, canonical_user_db_path, make_engine  # noqa: E402
from app.models import (  # noqa: E402
    AppSetting,
    BodyMetric,
    DailyStatus,
    Exercise,
    Template,
    TemplateExercise,
    Workout,
    WorkoutSet,
)
from app.services import projection  # noqa: E402
from scripts.backfill_sync import backup_before_run, run_backfill  # noqa: E402

TABLE_MODELS: dict[str, type] = {
    "exercises": Exercise,
    "templates": Template,
    "workouts": Workout,
    "sets": WorkoutSet,
    "body_metrics": BodyMetric,
    "daily_status": DailyStatus,
    "app_settings": AppSetting,
}


class MigrationAbort(Exception):
    """使用者輸入或資料狀態問題——main() 據此印錯誤訊息並回傳非零碼，而不是讓例外炸穿。"""


@dataclass
class TableReport:
    before_target: int
    legacy_total: int
    migrated: int = 0
    skipped: int = 0
    # 軟刪列刻意不遷（見 _migrate_sets）。獨立計數而不併進 skipped——
    # 「因為重複所以跳過」與「因為是墓碑所以不搬」是兩件事，混在一個數字裡就查不出來了。
    skipped_deleted: int = 0
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    after_target: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "before_target": self.before_target,
            "legacy_total": self.legacy_total,
            "migrated": self.migrated,
            "skipped": self.skipped,
            "skipped_deleted": self.skipped_deleted,
            "conflicts": len(self.conflicts),
            "conflict_detail": self.conflicts,
            "after_target": self.after_target,
        }


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# ---- user／路徑解析 ----


ENV_GOOGLE_SUB = "LIFTLOG_MIGRATE_GOOGLE_SUB"
ENV_EMAIL = "LIFTLOG_MIGRATE_EMAIL"


def resolve_identifier(
    env: dict[str, str] | None = None, *, interactive: bool | None = None
) -> tuple[str | None, str | None]:
    """回傳 (google_sub, email)，兩者恰有一個非 None。

    F149 ③：識別值只從環境變數或互動式安全輸入取得。命令列參數會留在 shell 歷史與
    process table 裡，所以這條路徑不存在——拿不到就中止，不做 fallback。
    """
    env = os.environ if env is None else env
    sub = (env.get(ENV_GOOGLE_SUB) or "").strip()
    if sub:
        return sub, None
    email = (env.get(ENV_EMAIL) or "").strip()
    if email:
        return None, email

    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise MigrationAbort(
            f"未取得目標 user 識別值：請設定 {ENV_GOOGLE_SUB} 或 {ENV_EMAIL}，"
            "或在互動式終端執行以安全輸入（識別值不接受命令列參數）"
        )

    # getpass 不回顯，因此識別值不會留在終端畫面上（也不會進 shell 歷史）。
    sub = getpass.getpass("目標 user 的 Google sub（輸入不會顯示）：").strip()
    if not sub:
        raise MigrationAbort("未輸入 Google sub，中止")
    return sub, None


def resolve_target_user(session: Session, google_sub: str | None, email: str | None) -> User:
    if google_sub:
        user = session.scalar(select(User).where(User.google_sub == google_sub))
    else:
        user = session.scalar(select(User).where(User.email == email))
    if user is None:
        # F149 ③：不回印識別值本身，只說用了哪個欄位查。
        field = "google_sub" if google_sub else "email"
        raise MigrationAbort(f"找不到符合的 user（依 {field} 查詢，識別值已隱去）")
    if user.status == "closed":
        raise MigrationAbort(f"user {user.id} 已刪除（status=closed），不遷入已關閉帳號")
    return user


def resolve_target_db_path(user_data_dir: str, user: User) -> Path:
    try:
        path = canonical_user_db_path(user_data_dir, user.id, user.data_db_name)
    except UserDataUnavailable as exc:
        raise MigrationAbort(f"user {user.id} 的 data DB 路徑不合法：{exc}") from exc
    if not path.is_file():
        raise MigrationAbort(f"target data DB 不存在：{path}（user 需先用 Google 登入建立過）")
    return path


# ---- 逐表遷移：exercises → templates → workouts → sets（依外鍵相依順序），
# body_metrics／daily_status 無相依，順序不影響正確性 ----


def _migrate_exercises(legacy: Session, target: Session) -> tuple[TableReport, dict[int, int]]:
    report = TableReport(
        before_target=_count(target, Exercise), legacy_total=_count(legacy, Exercise)
    )
    id_map: dict[int, int] = {}
    for row in legacy.scalars(select(Exercise)):
        match = projection._natural_key_match(  # noqa: SLF001 — 重用既有自然鍵規則，避免另拼一份會漂移的
            target, "exercise", {"name_zh": row.name_zh, "name_en": row.name_en}
        )
        legacy_values = {
            "name_zh": row.name_zh,
            "name_en": row.name_en,
            "muscle_group": row.muscle_group,
            "is_bodyweight": bool(row.is_bodyweight),
        }
        if match is None:
            new_row = Exercise(**legacy_values, deleted_at=row.deleted_at)
            target.add(new_row)
            target.flush()
            id_map[row.id] = new_row.id
            report.migrated += 1
            continue
        id_map[row.id] = match.id
        target_values = {
            "name_zh": match.name_zh,
            "name_en": match.name_en,
            "muscle_group": match.muscle_group,
            "is_bodyweight": bool(match.is_bodyweight),
        }
        if target_values == legacy_values:
            report.skipped += 1
        else:
            report.conflicts.append(
                {
                    "natural_key": {"name_zh": row.name_zh, "name_en": row.name_en},
                    "legacy": legacy_values,
                    "target": target_values,
                }
            )
    report.after_target = _count(target, Exercise)
    return report, id_map


def _template_children(
    session: Session, template_id: int, exercise_id_map: dict[int, int] | None
) -> list[tuple[int, int, int, int | None]]:
    """(mapped_exercise_id, position, default_sets, rest_hint_seconds) 依 position 排序。

    `exercise_id_map` 為 None 代表呼叫端已經是 target 自己的列，exercise_id 不必轉換。
    """
    items = session.scalars(
        select(TemplateExercise)
        .where(TemplateExercise.template_id == template_id)
        .order_by(TemplateExercise.position)
    ).all()
    return [
        (
            exercise_id_map[item.exercise_id] if exercise_id_map is not None else item.exercise_id,
            item.position,
            item.default_sets,
            item.rest_hint_seconds,
        )
        for item in items
    ]


def _migrate_templates(
    legacy: Session, target: Session, exercise_id_map: dict[int, int]
) -> tuple[TableReport, dict[int, int]]:
    report = TableReport(
        before_target=_count(target, Template), legacy_total=_count(legacy, Template)
    )
    id_map: dict[int, int] = {}
    for row in legacy.scalars(select(Template)):
        legacy_children = _template_children(legacy, row.id, exercise_id_map)
        legacy_signature = {"weekdays": row.weekdays, "children": legacy_children}
        # Template.name 不是 DB 層唯一約束，同名可能不只一筆——取第一筆當自然鍵目標，
        # 其餘視為與遷移無關的既有資料，不動它們。
        match = target.scalars(
            select(Template).where(Template.name == row.name).order_by(Template.id)
        ).first()
        if match is None:
            new_row = Template(name=row.name, weekdays=row.weekdays, deleted_at=row.deleted_at)
            target.add(new_row)
            target.flush()
            for exercise_id, position, default_sets, rest_hint_seconds in legacy_children:
                target.add(
                    TemplateExercise(
                        template_id=new_row.id,
                        position=position,
                        exercise_id=exercise_id,
                        default_sets=default_sets,
                        rest_hint_seconds=rest_hint_seconds,
                    )
                )
            target.flush()
            id_map[row.id] = new_row.id
            report.migrated += 1
            continue
        id_map[row.id] = match.id
        target_signature = {
            "weekdays": match.weekdays,
            "children": _template_children(target, match.id, None),
        }
        if target_signature == legacy_signature:
            report.skipped += 1
        else:
            report.conflicts.append(
                {
                    "natural_key": {"name": row.name},
                    "legacy": legacy_signature,
                    "target": target_signature,
                }
            )
    report.after_target = _count(target, Template)
    return report, id_map


def _migrate_workouts(
    legacy: Session, target: Session, template_id_map: dict[int, int]
) -> tuple[TableReport, dict[int, int]]:
    report = TableReport(
        before_target=_count(target, Workout), legacy_total=_count(legacy, Workout)
    )
    id_map: dict[int, int] = {}
    for row in legacy.scalars(select(Workout)):
        mapped_template_id = (
            template_id_map[row.template_id] if row.template_id is not None else None
        )
        conditions = [
            Workout.date == row.date,
            Workout.note == row.note if row.note is not None else Workout.note.is_(None),
            Workout.template_id == mapped_template_id
            if mapped_template_id is not None
            else Workout.template_id.is_(None),
        ]
        # 同一天同課表同備註沒有唯一約束擋，理論上可能不只一筆——取第一筆，其餘不動。
        match = target.scalars(select(Workout).where(*conditions).order_by(Workout.id)).first()
        legacy_values = {
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "owner_device_id": row.owner_device_id,
            "lease_generation": row.lease_generation,
        }
        if match is None:
            new_row = Workout(
                date=row.date,
                template_id=mapped_template_id,
                note=row.note,
                ended_at=row.ended_at,
                owner_device_id=row.owner_device_id,
                lease_generation=row.lease_generation,
                deleted_at=row.deleted_at,
            )
            target.add(new_row)
            target.flush()
            id_map[row.id] = new_row.id
            report.migrated += 1
            continue
        id_map[row.id] = match.id
        target_values = {
            "ended_at": match.ended_at.isoformat() if match.ended_at else None,
            "owner_device_id": match.owner_device_id,
            "lease_generation": match.lease_generation,
        }
        if target_values == legacy_values:
            report.skipped += 1
        else:
            report.conflicts.append(
                {
                    "natural_key": {
                        "date": row.date.isoformat(),
                        "note": row.note,
                        "template_id": mapped_template_id,
                    },
                    "legacy": legacy_values,
                    "target": target_values,
                }
            )
    report.after_target = _count(target, Workout)
    return report, id_map


def _migrate_sets(
    legacy: Session,
    target: Session,
    workout_id_map: dict[int, int],
    exercise_id_map: dict[int, int],
) -> TableReport:
    report = TableReport(
        before_target=_count(target, WorkoutSet), legacy_total=_count(legacy, WorkoutSet)
    )
    for row in legacy.scalars(select(WorkoutSet)):
        # 軟刪列不遷：墓碑的用途是告訴其他裝置「這筆被刪了」，而 target 從來沒看過這些列，
        # 沒有要通知的對象。搬進去只是把已刪資料複製一份到新庫。
        if row.deleted_at is not None:
            report.skipped_deleted += 1
            continue
        mapped_workout_id = workout_id_map[row.workout_id]
        mapped_exercise_id = exercise_id_map[row.exercise_id]
        match = projection._natural_key_match(  # noqa: SLF001
            target, "set", {"client_uuid": row.client_uuid}
        )
        if match is None:
            # client_uuid 沒撞不代表能寫進去——DB 真正的唯一約束是
            # partial unique index(workout, exercise, set_number) WHERE deleted_at IS NULL。
            # 同一天開兩場訓練時 workout 自然鍵會把它們併成一場，兩場各自記的同一組就在這裡撞。
            # 少了這道，遷移會在 flush 時炸 IntegrityError 而不是產出可讀的衝突報表。
            match = target.scalars(
                select(WorkoutSet).where(
                    WorkoutSet.workout_id == mapped_workout_id,
                    WorkoutSet.exercise_id == mapped_exercise_id,
                    WorkoutSet.set_number == row.set_number,
                    WorkoutSet.deleted_at.is_(None),
                )
            ).first()
        legacy_values = {
            "workout_id": mapped_workout_id,
            "exercise_id": mapped_exercise_id,
            "set_number": row.set_number,
            "weight_kg": row.weight_kg,
            "reps": row.reps,
            "rpe": row.rpe,
            "rest_seconds": row.rest_seconds,
        }
        if match is None:
            target.add(
                WorkoutSet(
                    client_uuid=row.client_uuid,
                    idem_key=row.idem_key,
                    deleted_at=row.deleted_at,
                    **legacy_values,
                )
            )
            report.migrated += 1
            continue
        target_values = {
            "workout_id": match.workout_id,
            "exercise_id": match.exercise_id,
            "set_number": match.set_number,
            "weight_kg": match.weight_kg,
            "reps": match.reps,
            "rpe": match.rpe,
            "rest_seconds": match.rest_seconds,
        }
        if target_values == legacy_values:
            report.skipped += 1
        else:
            report.conflicts.append(
                {
                    "natural_key": {
                        "client_uuid": row.client_uuid,
                        "matched_by": "client_uuid"
                        if match.client_uuid == row.client_uuid
                        else "workout+exercise+set_number",
                    },
                    "legacy": legacy_values,
                    "target": target_values,
                }
            )
    target.flush()
    report.after_target = _count(target, WorkoutSet)
    return report


def _migrate_dated_table(
    legacy: Session,
    target: Session,
    model: type,
    entity_type: str,
    value_fields: tuple[str, ...],
) -> TableReport:
    """body_metrics／daily_status 共用：自然鍵都是 date，差別只在要比對的欄位。"""
    report = TableReport(before_target=_count(target, model), legacy_total=_count(legacy, model))
    for row in legacy.scalars(select(model)):
        match = projection._natural_key_match(  # noqa: SLF001
            target, entity_type, {"date": row.date.isoformat()}
        )
        legacy_values = {name: getattr(row, name) for name in value_fields}
        if match is None:
            target.add(model(date=row.date, deleted_at=row.deleted_at, **legacy_values))
            report.migrated += 1
            continue
        target_values = {name: getattr(match, name) for name in value_fields}
        if target_values == legacy_values:
            report.skipped += 1
        else:
            report.conflicts.append(
                {
                    "natural_key": {"date": row.date.isoformat()},
                    "legacy": legacy_values,
                    "target": target_values,
                }
            )
    report.after_target = _count(target, model)
    return report


def _migrate_settings(legacy: Session, target: Session) -> TableReport:
    """app_settings：自然鍵就是主鍵 key，所以不必經 projection 的自然鍵規則。

    這張表看起來很小（目前只有 weekly_target_days），但它是使用者調過的設定——
    不搬的話遷移後每週目標會默默退回預設值，而畫面上不會有任何地方說「你的設定掉了」。
    """
    report = TableReport(
        before_target=_count(target, AppSetting), legacy_total=_count(legacy, AppSetting)
    )
    for row in legacy.scalars(select(AppSetting)):
        match = target.get(AppSetting, row.key)
        if match is None:
            target.add(AppSetting(key=row.key, value=row.value, updated_at=row.updated_at))
            report.migrated += 1
        elif match.value == row.value:
            report.skipped += 1
        else:
            report.conflicts.append(
                {
                    "natural_key": {"key": row.key},
                    "legacy": {"value": row.value},
                    "target": {"value": match.value},
                }
            )
    report.after_target = _count(target, AppSetting)
    return report


def run_migration(legacy: Session, target: Session) -> dict[str, TableReport]:
    """依外鍵相依順序跑完六張表，回傳依 TABLE_MODELS 順序排列的報表。"""
    exercise_report, exercise_id_map = _migrate_exercises(legacy, target)
    template_report, template_id_map = _migrate_templates(legacy, target, exercise_id_map)
    workout_report, workout_id_map = _migrate_workouts(legacy, target, template_id_map)
    set_report = _migrate_sets(legacy, target, workout_id_map, exercise_id_map)
    body_metric_report = _migrate_dated_table(
        legacy, target, BodyMetric, "body_metric", ("weight_kg", "body_fat_pct")
    )
    daily_status_report = _migrate_dated_table(
        legacy, target, DailyStatus, "daily_status", ("energy", "sleep_quality", "note")
    )
    settings_report = _migrate_settings(legacy, target)
    target.flush()

    reports = {
        "exercises": exercise_report,
        "templates": template_report,
        "workouts": workout_report,
        "sets": set_report,
        "body_metrics": body_metric_report,
        "daily_status": daily_status_report,
        "app_settings": settings_report,
    }
    for name, report in reports.items():
        expected = report.before_target + report.migrated
        if report.after_target != expected:
            raise MigrationAbort(
                f"row count 自我檢查失敗：{name} after_target={report.after_target} != "
                f"before_target({report.before_target}) + migrated({report.migrated})"
            )
    return reports


# ---- CLI ----


def _count_all_tables(db_path: Path) -> dict[str, int]:
    engine = make_engine(str(db_path))
    try:
        with sessionmaker(bind=engine)() as session:
            return {name: _count(session, model) for name, model in TABLE_MODELS.items()}
    finally:
        engine.dispose()


def _run_rollback(target_path: Path, snapshot_path: Path) -> int:
    if not snapshot_path.is_file():
        print(f"[ERROR] 找不到快照：{snapshot_path}", file=sys.stderr)
        return 1
    before = _count_all_tables(target_path)
    shutil.copyfile(snapshot_path, target_path)
    # 舊 WAL/SHM 指向的是回滾前那份檔案的頁面對映，留著會讓 SQLite 用錯頁——
    # 複製回去的快照本身已是一致狀態，靠它重建即可。
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{target_path}{suffix}")
        if sidecar.is_file():
            sidecar.unlink()
    after = _count_all_tables(target_path)
    print(f"[OK] 已從 {snapshot_path} 回滾至 {target_path}")
    print(json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=2))
    return 0


def _run_migration(
    legacy_db_path: Path, target_path: Path, *, dry_run: bool, remind_token: str
) -> int:
    if dry_run:
        print("[INFO] --dry-run：略過備份，僅試算摘要")
    else:
        backup_path = backup_before_run(target_path, datetime.now(UTC))
        print(f"[OK] 已備份（回滾用）：{backup_path}")

    legacy_engine = make_engine(str(legacy_db_path))
    target_engine = make_engine(str(target_path))
    legacy_session = sessionmaker(bind=legacy_engine)()
    target_session = sessionmaker(bind=target_engine)()
    try:
        reports = run_migration(legacy_session, target_session)
        run_backfill(target_session)
        if dry_run:
            target_session.rollback()
        else:
            target_session.commit()
    except MigrationAbort as exc:
        target_session.rollback()
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    finally:
        legacy_session.close()
        target_session.close()
        legacy_engine.dispose()
        target_engine.dispose()

    if not dry_run and remind_token:
        print(
            "[INFO] .env 仍設有 LIFTLOG_TOKEN——確認資料無誤後記得撤銷這個共用 demo token。"
        )
    summary = {name: r.as_dict() for name, r in reports.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F149：既有單庫資料遷移進 user data DB")
    parser.add_argument("--legacy-db", type=Path, default=None, help="cutover 前的單庫 liftlog.db")
    parser.add_argument("--dry-run", action="store_true", help="只試算摘要，不備份、不寫入")
    parser.add_argument(
        "--rollback", type=Path, default=None, metavar="SNAPSHOT", help="還原指定快照回 target DB"
    )
    parser.add_argument(
        "--control-db", type=Path, default=None, help="預設讀 Settings.control_db_path"
    )
    parser.add_argument(
        "--user-data-dir", type=Path, default=None, help="預設讀 Settings.user_data_dir"
    )
    args = parser.parse_args(argv)

    try:
        google_sub, email = resolve_identifier()
    except MigrationAbort as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    settings = Settings()
    control_db_path = args.control_db or Path(settings.control_db_path)
    user_data_dir = args.user_data_dir or Path(settings.user_data_dir)
    factory = make_control_session_factory(str(control_db_path))

    try:
        with factory() as control_session:
            user = resolve_target_user(control_session, google_sub, email)
        target_path = resolve_target_db_path(str(user_data_dir), user)
    except MigrationAbort as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.rollback is not None:
        return _run_rollback(target_path, args.rollback)

    if args.legacy_db is None or not args.legacy_db.is_file():
        print(f"[ERROR] 找不到 legacy DB：{args.legacy_db}", file=sys.stderr)
        return 1

    return _run_migration(
        args.legacy_db, target_path, dry_run=args.dry_run, remind_token=settings.token
    )


if __name__ == "__main__":
    raise SystemExit(main())
