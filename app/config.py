from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服務設定：token 必填，缺少時 create_app 拒絕啟動。

    環境變數名以 `.env.example` 為準：LIFTLOG_TOKEN、LIFTLOG_DB。
    """

    model_config = SettingsConfigDict(
        env_prefix="LIFTLOG_", env_file=".env", extra="ignore", populate_by_name=True
    )

    token: str = ""
    db_path: str = Field(
        default="./liftlog.db",
        validation_alias=AliasChoices("LIFTLOG_DB", "db_path"),
    )
    # F67 app 自我更新：release APK 的存放目錄。build 完把 lift-log-v<N>.apk 放進來，
    # 伺服器就會把它當成最新版供 app 下載（目錄不存在＝沒有可更新的版本，不是錯誤）。
    release_dir: str = "./release"
    # F31 Web Push（休息結束通知）：缺任一則推播功能停用、其餘照常運作
    vapid_private_key: str = ""  # PKCS8 DER 的 base64url（.env 單行）
    vapid_public_key: str = ""  # 未壓縮公鑰點 base64url＝前端 applicationServerKey
    vapid_subject: str = "mailto:admin@example.com"  # VAPID claims 的 sub
