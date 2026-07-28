"""F67：sideload 版 app 的自我更新端點。

app 版沒有商店的更新鏈（見 README 已知限制），所以由伺服器告訴它「最新版是哪一版」並供檔。
兩個端點都要 token——APK 不含密鑰，但沒有理由讓它對外開放下載。
"""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from app.api.deps import require_token
from app.errors import NotFoundError

router = APIRouter(prefix="/api/app", dependencies=[Depends(require_token)])

APK_PATTERN = re.compile(r"^lift-log-v(\d+)\.apk$")
APK_MEDIA_TYPE = "application/vnd.android.package-archive"


def _latest_apk(release_dir: str) -> tuple[int, Path] | None:
    """發佈目錄裡版號最大的 APK。舊檔留著是常態（回退用），故取最大而非最新 mtime。"""
    directory = Path(release_dir)
    if not directory.is_dir():
        return None
    candidates: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        match = APK_PATTERN.match(path.name)
        # 數值比較：字串排序會讓 v9 大於 v65
        if match and path.is_file():
            candidates.append((int(match.group(1)), path))
    return max(candidates, key=lambda item: item[0]) if candidates else None


def _require_latest(request: Request) -> tuple[int, Path]:
    found = _latest_apk(request.app.state.settings.release_dir)
    if found is None:
        raise NotFoundError("目前沒有可下載的 app 版本")
    return found


@router.get("/latest")
def latest(request: Request) -> dict:
    version, path = _require_latest(request)
    return {
        "version_code": version,
        "version_name": str(version),
        "url": "/api/app/apk",
        "size_bytes": path.stat().st_size,
    }


@router.get("/apk")
def apk(request: Request) -> FileResponse:
    version, path = _require_latest(request)
    return FileResponse(path, media_type=APK_MEDIA_TYPE, filename=f"lift-log-v{version}.apk")
