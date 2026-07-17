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
