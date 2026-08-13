import hashlib
import uuid
from datetime import date as date_type
from datetime import datetime
from difflib import SequenceMatcher
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, DomainError, NotFoundError, UnknownExerciseError
from app.models import Exercise, Template, Workout, WorkoutSet
from app.schemas import (
    BatchDryRunPreviewItem,
    BatchDryRunSummary,
    LogSetIn,
    LogWorkoutIn,
    LogWorkoutSummary,
    SetCreate,
    SetUpdate,
    WorkoutCreate,
)
from app.services.body_metrics import latest_weight
from app.services.exercises import exercise_label, normalize_name
from app.services.stats import set_tonnage

_SUGGEST_CUTOFF = 0.4
_SUGGEST_LIMIT = 3
_SUBSTRING_BOOST = 0.9  # 子字串命中視為高相似（difflib ratio 對中英混排偏低）
DEFAULT_MUSCLE_GROUP = "未分類"  # create_missing 自動建檔的預設部位


def _exercise_index(exercises: list[Exercise]) -> dict[str, Exercise]:
    """正規化雙語名稱 → Exercise（與 exercises.find_by_name 同語意）。"""
    index: dict[str, Exercise] = {}
    for exercise in exercises:
        index[normalize_name(exercise.name_zh)] = exercise
        index[normalize_name(exercise.name_en)] = exercise
    return index


def _suggest(exercises: list[Exercise], unknown: str) -> list[str]:
    """對未命中名稱給相近動作建議，格式「深蹲 Squat」。"""
    target = normalize_name(unknown)
    scored: list[tuple[float, str]] = []
    for exercise in exercises:
        zh = normalize_name(exercise.name_zh)
        en = normalize_name(exercise.name_en)
        score = max(
            SequenceMatcher(None, target, zh).ratio(),
            SequenceMatcher(None, target, en).ratio(),
        )
        if target in zh or target in en or zh in target or en in target:
            score = max(score, _SUBSTRING_BOOST)
        if score >= _SUGGEST_CUTOFF:
            scored.append((score, exercise_label(exercise)))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [label for _, label in scored[:_SUGGEST_LIMIT]]


def _resolve_template_id(session: Session, name: str) -> int:
    ids = list(session.scalars(select(Template.id).where(Template.name == name)))
    if not ids:
        raise DomainError("template not found")
    if len(ids) > 1:
        # 同名課表隨機掛一個會安靜寫錯資料——寧可拒絕要求改名
        raise DomainError("multiple templates share this name; rename to disambiguate")
    return ids[0]


def _set_uuid(client_uuid: str | None, ordinal: int) -> str:
    """呼叫端有帶冪等鍵→確定性 uuid（重放撞 UNIQUE 可辨識）；否則隨機。"""
    return f"{client_uuid}:{ordinal}" if client_uuid else str(uuid.uuid4())


def _idem_key(workout_date: date_type, exercise_id: int, set_number: int) -> str:
    """F151：date+exercise+set_index 的 server 端冪等鍵，不依賴 client 狀態。"""
    return hashlib.sha256(f"{workout_date}|{exercise_id}|{set_number}".encode()).hexdigest()


class _PlannedSet(NamedTuple):
    """F151：寫入前先算好每一組的鍵，才知道哪些要跳過、workout 要不要新建。"""

    ordinal: int  # data.sets 內的原始序號（1-based），決定 client_uuid 後綴
    item: LogSetIn
    exercise: Exercise
    set_number: int
    idem_key: str


class _BatchPlan(NamedTuple):
    """F151 前半段的輸出：F152 dry-run 與實際寫入共用同一份判斷，不得各自算一套。"""

    planned: list[_PlannedSet]
    existing_by_key: dict[str, WorkoutSet]
    to_write: list[_PlannedSet]
    skipped_count: int
    template_id: int | None
    workout_date: date_type


def _replayed_summary(session: Session, data: LogWorkoutIn) -> LogWorkoutSummary | None:
    """同 client_uuid 重放（MCP timeout 後 LLM 重試）：回既有 workout 摘要，不重複寫入。"""
    if data.client_uuid is None:
        return None
    first = _find_by_client_uuid(session, _set_uuid(data.client_uuid, 1))
    if first is None:
        return None
    workout = get_workout(session, first.workout_id)
    prefix = f"{data.client_uuid}:"
    logged = [
        s
        for s in session.scalars(
            select(WorkoutSet).where(WorkoutSet.workout_id == workout.id)
        )
        if s.client_uuid.startswith(prefix)
    ]
    bodyweight_kg = latest_weight(session)
    flags = {e.id: e.is_bodyweight for e in session.scalars(select(Exercise))}
    tonnage = sum(
        set_tonnage(s.weight_kg, s.reps, flags[s.exercise_id], bodyweight_kg) for s in logged
    )
    return LogWorkoutSummary(
        workout_id=workout.id,
        date=workout.date,
        sets_count=len(logged),
        tonnage_kg=tonnage,
        # F143 層重放：整批視為已處理過，不算這次新建
        created_count=0,
        skipped_count=len(logged),
    )


def log_workout(session: Session, data: LogWorkoutIn) -> LogWorkoutSummary:
    """MCP 與 batch endpoint 共用的單一 writer 入口。"""
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    try:
        summary = _log_workout(session, data)
        if session.in_transaction():
            session.rollback()
        return summary
    except Exception:
        session.rollback()
        raise


def _plan_batch(session: Session, data: LogWorkoutIn) -> _BatchPlan:
    """算出這批要新建/略過的組（F151 冪等鍵比對）；`_log_workout` 與 dry-run 共用同一段。

    unknown 動作、create_missing 的 flush 都在這裡發生——dry-run 呼叫端算完要自己
    rollback，不然 create_missing 建的 Exercise 會真的留在 DB 裡。
    """
    template_id = _resolve_template_id(session, data.template) if data.template else None

    exercises = list(session.scalars(select(Exercise)))
    index = _exercise_index(exercises)
    wanted = list(dict.fromkeys(item.exercise for item in data.sets))
    # 大小寫變體視為同一動作：以 lower 去重，避免 create_missing 建出重複動作留孤兒
    unknown: list[str] = []
    seen_unknown: set[str] = set()
    for name in wanted:
        key = name.lower()
        if key not in index and key not in seen_unknown:
            seen_unknown.add(key)
            unknown.append(name)

    if unknown and not data.create_missing:
        suggestions: list[str] = []
        for name in unknown:
            suggestions.extend(_suggest(exercises, name))
        raise UnknownExerciseError(unknown, list(dict.fromkeys(suggestions)))

    for name in unknown:
        created = Exercise(name_zh=name, name_en=name, muscle_group=DEFAULT_MUSCLE_GROUP)
        session.add(created)
        index[name.lower()] = created
    session.flush()

    # F151：每組先算出 date+exercise+set_index 的冪等鍵，才知道哪些是重送、workout 要不要新建。
    # server 本地時區＝自家機台灣時間；異地（UTC）部署前要重新確認
    workout_date = data.date or date_type.today()
    set_counts: dict[int, int] = {}
    planned: list[_PlannedSet] = []
    for ordinal, item in enumerate(data.sets, start=1):
        exercise = index[item.exercise.lower()]
        set_counts[exercise.id] = set_counts.get(exercise.id, 0) + 1
        set_number = set_counts[exercise.id]
        planned.append(
            _PlannedSet(
                ordinal=ordinal,
                item=item,
                exercise=exercise,
                set_number=set_number,
                idem_key=_idem_key(workout_date, exercise.id, set_number),
            )
        )

    existing_by_key = {
        row.idem_key: row
        for row in session.scalars(
            select(WorkoutSet).where(
                WorkoutSet.idem_key.in_([p.idem_key for p in planned]),
                WorkoutSet.deleted_at.is_(None),
            )
        )
    }
    to_write = [p for p in planned if p.idem_key not in existing_by_key]
    return _BatchPlan(
        planned=planned,
        existing_by_key=existing_by_key,
        to_write=to_write,
        skipped_count=len(planned) - len(to_write),
        template_id=template_id,
        workout_date=workout_date,
    )


def _log_workout(session: Session, data: LogWorkoutIn) -> LogWorkoutSummary:
    """MCP 代記錄的單一交易入口（PRD R7b）。

    整包寫入或整包拒絕（單一 commit，不留半套）；動作名雙語比對，
    未命中且未帶 create_missing 時回未知清單＋相近建議；
    同 client_uuid 重放冪等回既有摘要。
    """
    replayed = _replayed_summary(session, data)
    if replayed is not None:
        return replayed

    plan = _plan_batch(session, data)

    if not plan.to_write:
        # 整批都已寫過——連 Workout 列都不得新建，回既有那些組所屬的 workout
        existing_workout = get_workout(
            session, next(iter(plan.existing_by_key.values())).workout_id
        )
        return LogWorkoutSummary(
            workout_id=existing_workout.id,
            date=existing_workout.date,
            sets_count=0,
            tonnage_kg=0.0,
            created_count=0,
            skipped_count=plan.skipped_count,
        )

    if plan.existing_by_key:
        # 部分重送：新組併入舊組所屬的 workout，不得另開一場（否則同一天多出只含新組的
        # 孤兒 workout）。命中鍵理論上都屬同一 workout；真的橫跨多場（只可能是 F151 之前
        # 的舊資料）就取第一個，不特別處理。template/note 不套用到既有 workout——那是別人
        # 已經存在的資料，不得覆寫。
        workout = get_workout(session, next(iter(plan.existing_by_key.values())).workout_id)
    else:
        workout = Workout(date=plan.workout_date, template_id=plan.template_id, note=data.note)
        session.add(workout)
        session.flush()

    bodyweight_kg = latest_weight(session)
    tonnage = 0.0
    for planned_set in plan.to_write:
        session.add(
            WorkoutSet(
                client_uuid=_set_uuid(data.client_uuid, planned_set.ordinal),
                workout_id=workout.id,
                exercise_id=planned_set.exercise.id,
                set_number=planned_set.set_number,
                weight_kg=planned_set.item.weight_kg,
                reps=planned_set.item.reps,
                rpe=planned_set.item.rpe,
                idem_key=planned_set.idem_key,
            )
        )
        tonnage += set_tonnage(
            planned_set.item.weight_kg,
            planned_set.item.reps,
            planned_set.exercise.is_bodyweight,
            bodyweight_kg,
        )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # 三種撞法：同 client_uuid 併發重放、冪等鍵併發重放（復原為冪等）、
        # create_missing 同名競賽（明確錯誤）；冪等鍵撞號不重試，循序重送才是 acceptance 範圍。
        raced = _replayed_summary(session, data)
        if raced is not None:
            return raced
        raise DomainError("concurrent write conflict, please retry") from exc
    return LogWorkoutSummary(
        workout_id=workout.id,
        date=workout.date,
        sets_count=len(plan.to_write),
        tonnage_kg=tonnage,
        created_count=len(plan.to_write),
        skipped_count=plan.skipped_count,
    )


_DRY_RUN_PREVIEW_LIMIT = 5


def dry_run_log_workout(session: Session, data: LogWorkoutIn) -> BatchDryRunSummary:
    """F152：批次寫入 dry-run——只算 will_create/will_skip/will_conflict，零副作用。

    重用 `_plan_batch` 同一套判斷（不複製第二套）；conflict＝idem_key 沒命中但目標
    workout 已有同 (exercise_id, set_number) 的未軟刪組（典型是 F151 之前、idem_key
    為 NULL 的舊資料）。目標 workout 的判定與實際寫入一致：有鍵命中就是那個既有
    workout，否則是將新建的 workout＝不可能衝突。無論成功或例外都在 finally 裡
    rollback，不依賴「沒呼叫 commit 所以沒事」——create_missing 可能已 flush 進去的
    Exercise 也要一併丟掉。
    """
    try:
        plan = _plan_batch(session, data)

        conflict_keys: set[tuple[int, int]] = set()
        if plan.existing_by_key:
            target_workout_id = next(iter(plan.existing_by_key.values())).workout_id
            conflict_keys = {
                (row.exercise_id, row.set_number)
                for row in session.scalars(
                    select(WorkoutSet).where(
                        WorkoutSet.workout_id == target_workout_id,
                        WorkoutSet.deleted_at.is_(None),
                    )
                )
            }

        will_create = 0
        will_conflict = 0
        preview: list[BatchDryRunPreviewItem] = []
        for planned_set in plan.planned:
            if planned_set.idem_key in plan.existing_by_key:
                disposition = "skip"
            elif (planned_set.exercise.id, planned_set.set_number) in conflict_keys:
                disposition = "conflict"
                will_conflict += 1
            else:
                disposition = "create"
                will_create += 1
            if len(preview) < _DRY_RUN_PREVIEW_LIMIT:
                preview.append(
                    BatchDryRunPreviewItem(
                        index=planned_set.ordinal - 1,
                        exercise=planned_set.item.exercise,
                        weight_kg=planned_set.item.weight_kg,
                        reps=planned_set.item.reps,
                        disposition=disposition,
                    )
                )

        return BatchDryRunSummary(
            will_create_count=will_create,
            will_skip_count=plan.skipped_count,
            will_conflict_count=will_conflict,
            preview=preview,
        )
    finally:
        session.rollback()


def create_workout(session: Session, data: WorkoutCreate) -> Workout:
    workout = Workout(
        date=data.date or date_type.today(),
        template_id=data.template_id,
        note=data.note,
    )
    session.add(workout)
    session.commit()
    session.refresh(workout)
    return workout


def get_workout(session: Session, workout_id: int) -> Workout:
    workout = session.get(Workout, workout_id)
    if workout is None:
        raise NotFoundError()
    return workout


def end_workout(session: Session, workout_id: int) -> Workout:
    """F91：標記這場訓練已結束。

    冪等——已結束的再呼叫一次回同一筆、時間不變。離線佇列補傳與連點都會重送，
    每次都覆寫時間的話「結束於何時」會被最後一次重送污染。
    """
    workout = get_workout(session, workout_id)
    if workout.ended_at is None:
        workout.ended_at = datetime.now()
        session.commit()
        session.refresh(workout)
    return workout


def delete_workout(session: Session, workout_id: int) -> None:
    """F92 ⑤：刪掉一場沒有任何組的 workout（按了「開始訓練」卻沒記東西留下的）。

    **連軟刪除的組都不能有**——有的話代表確實練過又刪掉，那是歷史紀錄，
    不得因為「查詢起來看不到組」就當成空的清掉。
    """
    workout = get_workout(session, workout_id)
    any_set = session.scalar(
        select(WorkoutSet.id).where(WorkoutSet.workout_id == workout_id).limit(1)
    )
    if any_set is not None:
        raise ConflictError("這場訓練有紀錄過的組，不能刪除")
    session.delete(workout)
    session.commit()


def get_active_sets(session: Session, workout_id: int) -> list[WorkoutSet]:
    """該 workout 未刪除的組，SQL 端過濾與排序（軟刪除不變量的唯一入口）。"""
    return list(
        session.scalars(
            select(WorkoutSet)
            .where(WorkoutSet.workout_id == workout_id, WorkoutSet.deleted_at.is_(None))
            .order_by(WorkoutSet.exercise_id, WorkoutSet.set_number, WorkoutSet.id)
        )
    )


def get_active_sets_by_workout(
    session: Session, workout_ids: list[int]
) -> dict[int, list[WorkoutSet]]:
    """多 workout 一次查未刪除組（MCP 區間查詢避免 N+1）；組內排序同 get_active_sets。"""
    grouped: dict[int, list[WorkoutSet]] = {workout_id: [] for workout_id in workout_ids}
    rows = session.scalars(
        select(WorkoutSet)
        .where(WorkoutSet.workout_id.in_(workout_ids), WorkoutSet.deleted_at.is_(None))
        .order_by(
            WorkoutSet.workout_id, WorkoutSet.exercise_id, WorkoutSet.set_number, WorkoutSet.id
        )
    )
    for row in rows:
        grouped[row.workout_id].append(row)
    return grouped


def list_workouts(
    session: Session, start: date_type | None, end: date_type | None
) -> list[Workout]:
    query = select(Workout).order_by(Workout.date, Workout.id)
    if start is not None:
        query = query.where(Workout.date >= start)
    if end is not None:
        query = query.where(Workout.date <= end)
    return list(session.scalars(query))


def _find_by_client_uuid(session: Session, client_uuid: str) -> WorkoutSet | None:
    return session.scalar(select(WorkoutSet).where(WorkoutSet.client_uuid == client_uuid))


def _as_idempotent_hit(existing: WorkoutSet, workout_id: int) -> WorkoutSet:
    """重放必須命中「同一 workout 的未刪除組」，否則是衝突不是冪等。"""
    if existing.workout_id != workout_id or existing.deleted_at is not None:
        raise ConflictError("client_uuid already used")
    return existing


_SET_NUMBER_MAX_RETRIES = 5  # F133 ②：server 配號撞唯一約束的重試上限


def _next_set_number(session: Session, workout_id: int, exercise_id: int) -> int:
    """F131 ③：該 workout 該動作的最大組號 +1（F32 語意，範圍是「這一場的這個動作」）。

    **軟刪的組仍計入**：重用已刪組的號碼會讓同場同動作出現兩筆相同組號（前端
    app.js:1095 有同一個顧慮）。寧可跳號也不撞號。DB 端由 F133 的唯一約束兜底。
    """
    highest = session.scalar(
        select(func.max(WorkoutSet.set_number)).where(
            WorkoutSet.workout_id == workout_id,
            WorkoutSet.exercise_id == exercise_id,
        )
    )
    return (highest or 0) + 1


def log_set(session: Session, workout_id: int, data: SetCreate) -> tuple[WorkoutSet, bool]:
    """寫入一組。回傳 (set, created)；同 client_uuid 重放冪等回傳既有那筆。

    順序：先驗證 workout（404）與 exercise（400），再查冪等鍵；insert 撞 UNIQUE 時
    rollback 重查——命中 client_uuid 就是併發重放，復原為冪等回應；否則是 F133 ①的
    (workout_id, exercise_id, set_number) 唯一約束擋下撞號：
      - server 自己配的號撞號 → 重新配號重試（上限 `_SET_NUMBER_MAX_RETRIES`），
        耗盡就回 409，不得靜默吞掉（F133 ②）。
      - client 自己帶號撞號 → 直接回 409，不得改配別的號碼靜默寫成重複列（F133 ③）。
    """
    get_workout(session, workout_id)
    if session.get(Exercise, data.exercise_id) is None:
        raise DomainError("exercise not found")

    existing = _find_by_client_uuid(session, data.client_uuid)
    if existing is not None:
        return _as_idempotent_hit(existing, workout_id), False

    fields = data.model_dump()
    client_supplied_set_number = fields.get("set_number") is not None
    max_attempts = 1 if client_supplied_set_number else _SET_NUMBER_MAX_RETRIES

    for attempt in range(1, max_attempts + 1):
        if not client_supplied_set_number:
            fields["set_number"] = _next_set_number(session, workout_id, data.exercise_id)
        workout_set = WorkoutSet(workout_id=workout_id, **fields)
        session.add(workout_set)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raced = _find_by_client_uuid(session, data.client_uuid)
            if raced is not None:
                return _as_idempotent_hit(raced, workout_id), False
            # SQLite 的 IntegrityError 訊息列出撞到的欄位（如「UNIQUE constraint failed:
            # sets.workout_id, sets.exercise_id, sets.set_number」），不是索引名。只有這個
            # 約束涉及 set_number，其他 IntegrityError（FK 違反、未來新增的 NOT NULL 欄位
            # 漏填…）不是組號衝突，翻成 409 會誤導使用者、也讓 server 端查不出真因，原樣拋出。
            if "sets.set_number" not in str(exc.orig):
                raise
            if client_supplied_set_number:
                raise ConflictError(
                    f"set_number {fields['set_number']} 在這場這個動作已存在"
                    f"（workout_id={workout_id}, exercise_id={data.exercise_id}）"
                ) from exc
            if attempt == max_attempts:
                raise ConflictError(
                    f"組號配號重試 {max_attempts} 次仍撞號"
                    f"（workout_id={workout_id}, exercise_id={data.exercise_id}），請重新嘗試"
                ) from exc
            continue
        session.refresh(workout_set)
        return workout_set, True


def soft_delete_set(session: Session, set_id: int) -> None:
    workout_set = session.get(WorkoutSet, set_id)
    if workout_set is None or workout_set.deleted_at is not None:
        raise NotFoundError()
    workout_set.deleted_at = datetime.now()
    session.commit()


def update_set(session: Session, set_id: int, data: SetUpdate) -> WorkoutSet:
    """F16 原位編輯：只改量測欄位，set_number/exercise/client_uuid 不動；已刪或不存在回 404。"""
    workout_set = session.get(WorkoutSet, set_id)
    if workout_set is None or workout_set.deleted_at is not None:
        raise NotFoundError()
    workout_set.weight_kg = data.weight_kg
    workout_set.reps = data.reps
    workout_set.rpe = data.rpe
    workout_set.rest_seconds = data.rest_seconds
    session.commit()
    session.refresh(workout_set)
    return workout_set
