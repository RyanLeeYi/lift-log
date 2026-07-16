from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服務設定：token 必填，缺少時 create_app 拒絕啟動。"""

    model_config = SettingsConfigDict(env_prefix="LIFTLOG_", env_file=".env", extra="ignore")

    token: str = ""
    db_path: str = "./liftlog.db"
