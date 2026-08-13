"""F80 應用設定：key/value 的取得與寫入。

值一律以字串存放，**語意與值域驗證集中在這裡**——DB 欄位是 TEXT，幫不上任何忙。
未知的 key 一律拒絕（DomainError），免得打錯字就悄悄長出一個沒人讀的設定。
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import AppSetting
from app.services import projection

WEEKLY_TARGET_DAYS = "weekly_target_days"


def _validate_weekly_target(value: str) -> str:
    try:
        days = int(value)
    except ValueError:
        raise DomainError(f"{WEEKLY_TARGET_DAYS} must be an integer 1-7") from None
    if not 1 <= days <= 7:
        raise DomainError(f"{WEEKLY_TARGET_DAYS} must be an integer 1-7")
    return str(days)


# key → (預設值, 驗證器)。新增設定就加在這裡，不必動 API 或 schema。
KNOWN: dict[str, tuple[str, Callable[[str], str]]] = {
    WEEKLY_TARGET_DAYS: ("4", _validate_weekly_target),
}


def get_setting(session: Session, key: str) -> str:
    """取設定值；沒設過就回預設值（不寫入——第一次讀不該產生副作用）。"""
    if key not in KNOWN:
        raise DomainError("unknown setting")
    row = session.get(AppSetting, key)
    return row.value if row else KNOWN[key][0]


def set_setting(session: Session, key: str, value: str) -> str:
    if key not in KNOWN:
        raise DomainError("unknown setting")
    cleaned = KNOWN[key][1](value)
    row = session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=cleaned)
        session.add(row)
    else:
        row.value = cleaned
        row.deleted_at = None
    projection.record_write(session, "setting", row)
    session.commit()
    return cleaned


def weekly_target_days(session: Session) -> int:
    return int(get_setting(session, WEEKLY_TARGET_DAYS))
