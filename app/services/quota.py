"""F149／PRD R9：每 user 每天最多接受的 mutation 筆數。

配額與 `data_db_max_bytes`（容量）互補：容量擋的是「存太多」，這裡擋的是「寫太快」。
超限一律整批拒絕並回 429——部分接受會讓 client 的 outbox 對不上帳，而 429 在
Android 端（`SyncHttpTransport.java`）已被歸類為 retryable，本地資料不會被丟掉。
"""

from datetime import datetime, timedelta

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.control_models import UserDailyMutation
from app.services.auth import utcnow


class DailyMutationQuotaExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("daily mutation quota exceeded")
        self.retry_after = retry_after


def seconds_until_utc_midnight(now: datetime) -> int:
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


def consume_mutations(
    control_session_factory: sessionmaker[Session],
    user_id: str,
    limit: int,
    count: int = 1,
) -> None:
    """扣掉今天的額度；不足就拋 DailyMutationQuotaExceeded，一筆都不記。

    用單一 upsert 帶 WHERE 守衛而不是「先讀再寫」：兩個併發請求各自讀到同一個舊值時，
    先讀再寫會讓兩邊都通過而超額。
    """
    now = utcnow()
    if count > limit:
        raise DailyMutationQuotaExceeded(seconds_until_utc_midnight(now))

    statement = sqlite_insert(UserDailyMutation).values(
        user_id=user_id, day=now.date().isoformat(), count=count
    )
    statement = statement.on_conflict_do_update(
        index_elements=[UserDailyMutation.user_id, UserDailyMutation.day],
        set_={"count": UserDailyMutation.count + count},
        where=UserDailyMutation.count + count <= limit,
    )
    with control_session_factory() as session:
        accepted = session.execute(statement).rowcount
        session.commit()
    if not accepted:
        raise DailyMutationQuotaExceeded(seconds_until_utc_midnight(now))
