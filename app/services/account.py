"""F148／PRD R7、R9：資料匯出、刪帳與 backup tombstone。

匯出只重用既有 REST 回應形狀（`ExerciseOut`／`WorkoutOut`／`SetOut`／...）——那些欄位集合
已經是對外公開、審過不含憑證的形狀，不必另外維護一份匯出專用的欄位白名單。
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.control_models import AccountTombstone, AuthSession, McpToken, RefreshToken, User
from app.db import UserDataUnavailable, canonical_user_db_path
from app.errors import NotFoundError
from app.models import PushSubscription
from app.schemas import BodyMetricOut, DailyStatusOut, ExerciseOut, SetOut, WorkoutOut
from app.services import body_metrics as body_metrics_service
from app.services import daily_status as daily_status_service
from app.services import exercises as exercises_service
from app.services import settings as settings_service
from app.services import templates as templates_service
from app.services import workouts as workouts_service
from app.services.auth import utcnow

EXPORT_SCHEMA_VERSION = 1
# ponytail：backup 保留期只存成一個到期時間欄位，不蓋一整套備份系統——
# 真正的每日備份與清除排程是 R9 的營運事，這裡只留「多久之後可以真的丟掉」的紀錄。
ACCOUNT_DELETE_RETENTION = timedelta(days=30)


def export_account_data(session: Session) -> dict[str, Any]:
    """完整、版本化 JSON：只含 domain 資料，不碰 control DB 的任何憑證欄位。"""
    exercises = exercises_service.search_exercises(session, q=None)
    templates = templates_service.list_templates(session)
    workouts = workouts_service.list_workouts(session, None, None)
    sets_by_workout = workouts_service.get_active_sets_by_workout(
        session, [w.id for w in workouts]
    )
    body_metrics = body_metrics_service.list_body_metrics(session)
    daily_status = daily_status_service.list_daily_status(session)
    settings_out = {
        key: settings_service.get_setting(session, key) for key in settings_service.KNOWN
    }
    # push_subscriptions 沒有對外 GET 端點，所以不能沿用「既有 REST 形狀」那條捷徑；
    # 它仍是 data DB 內的 domain 表，acceptance 的「涵蓋所有 domain 資料」把它算在內。
    push_subscriptions = session.scalars(
        select(PushSubscription).order_by(PushSubscription.id)
    ).all()

    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": utcnow().isoformat() + "Z",
        "exercises": [ExerciseOut.model_validate(row).model_dump(mode="json") for row in exercises],
        "templates": [row.model_dump(mode="json") for row in templates],
        "workouts": [
            {
                **WorkoutOut.model_validate(workout).model_dump(mode="json"),
                "sets": [
                    SetOut.model_validate(row).model_dump(mode="json")
                    for row in sets_by_workout.get(workout.id, [])
                ],
            }
            for workout in workouts
        ],
        "body_metrics": [
            BodyMetricOut.model_validate(row).model_dump(mode="json") for row in body_metrics
        ],
        "daily_status": [
            DailyStatusOut.model_validate(row).model_dump(mode="json") for row in daily_status
        ],
        "settings": settings_out,
        "push_subscriptions": [
            {
                "endpoint": row.endpoint,
                "p256dh": row.p256dh,
                "auth": row.auth,
                "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
            }
            for row in push_subscriptions
        ],
    }


def is_tombstoned(control_session: Session, user_id: str) -> bool:
    """這個 user 是否已被刪帳。啟動／復原流程據此拒絕把資料當 active 復原（PRD R7）。"""
    return control_session.get(AccountTombstone, user_id) is not None


def delete_account(
    control_session_factory: sessionmaker[Session],
    settings: Settings,
    user_id: str,
) -> None:
    """撤銷全部 session／device／MCP token、標記帳號關閉、留刪帳 tombstone，再刪 active data DB。

    保留 `User` 列（只標 `status="closed"`）而不硬刪：google_sub 的 UNIQUE 約束因此繼續擋著
    同一個 Google 帳號用登入流程復活；`AccountTombstone` 外鍵也才有列可以指。
    """
    now = utcnow()
    with control_session_factory() as control:
        user = control.get(User, user_id)
        if user is None:
            raise NotFoundError()
        if user.status == "closed":
            return  # 已刪過：不重複撤銷、不重複寫 tombstone（primary key 會撞）
        data_db_name = user.data_db_name

        control.execute(
            update(AuthSession).where(AuthSession.user_id == user_id).values(revoked_at=now)
        )
        session_ids = list(
            control.scalars(select(AuthSession.id).where(AuthSession.user_id == user_id))
        )
        if session_ids:
            control.execute(
                update(RefreshToken)
                .where(RefreshToken.session_id.in_(session_ids))
                .values(status="revoked")
            )
        control.execute(
            update(McpToken)
            .where(McpToken.user_id == user_id, McpToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        control.add(
            AccountTombstone(
                user_id=user_id, deleted_at=now, purge_after=now + ACCOUNT_DELETE_RETENTION
            )
        )
        user.status = "closed"
        control.commit()

    try:
        path = canonical_user_db_path(settings.user_data_dir, user_id, data_db_name)
    except UserDataUnavailable:
        return  # 路徑本身異常——帳號已在 control DB 關閉且憑證已撤銷，不強求刪檔
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)
