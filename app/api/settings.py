"""F80：應用設定（目前只有每週目標天數）。"""

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_token
from app.schemas import SettingIn, SettingOut
from app.services import settings as svc

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.get("/settings/{key}", response_model=SettingOut)
def get_setting(key: str, session: DbSession) -> SettingOut:
    return SettingOut(key=key, value=svc.get_setting(session, key))


@router.put("/settings/{key}", response_model=SettingOut)
def put_setting(key: str, data: SettingIn, session: DbSession) -> SettingOut:
    return SettingOut(key=key, value=svc.set_setting(session, key, data.value))
