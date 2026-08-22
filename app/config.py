from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服務設定。環境變數名以 `.env.example` 為準：LIFTLOG_TOKEN、LIFTLOG_DB。"""

    model_config = SettingsConfigDict(
        env_prefix="LIFTLOG_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # F149：demo 模式的單一共用 Bearer token。**選填，未設就整條 legacy 路徑關閉**
    # （公開版預設只能 Google 登入，見 PRD 非目標）。docker demo profile 才設它。
    # 曾經它同時兼任 CSRF HMAC 金鑰——那讓「改成選填」等於架空 CSRF，已拆給 secret_key。
    token: str = ""
    # web session 的 CSRF token 由 HMAC(secret_key, session_id) 推導，所以這把金鑰
    # 換掉等於讓所有既有 web session 的 CSRF 失效。未設時由 control DB 產一顆並持久化
    # （見 control_db.ensure_web_csrf_secret），自架者不必手動設定，重啟也不會被登出。
    secret_key: str = ""
    db_path: str = Field(
        default="./liftlog.db",
        validation_alias=AliasChoices("LIFTLOG_DB", "db_path"),
    )
    control_db_path: str = "./control.db"
    user_data_dir: str = "./users"
    data_db_max_bytes: int = 100 * 1024 * 1024
    # F149／PRD R9：每 user 每天最多接受的 mutation 筆數（容量之外的第二道配額）。
    daily_mutation_limit: int = 20_000
    # OAuth client ID 是公開識別值，不是 secret；Android 與 Web 都把它當 audience。
    google_client_id: str = ""
    # F67 app 自我更新：release APK 的存放目錄。build 完把 lift-log-v<N>.apk 放進來，
    # 伺服器就會把它當成最新版供 app 下載（目錄不存在＝沒有可更新的版本，不是錯誤）。
    release_dir: str = "./release"
    # F93：這台服務是正式站還是測試站。畫面會顯示在版號下面——
    # 兩站的網址與 app 圖示都很像，沒有標示時很容易對著測試站以為資料沒存進去。
    # 預設 prod：忘了設就當正式站看待（保守方向——把正式站誤標成測試站比較危險）。
    env_label: str = Field(
        default="prod",
        validation_alias=AliasChoices("LIFTLOG_ENV", "env_label"),
    )

    @field_validator("env_label", mode="after")
    @classmethod
    def _known_env(cls, value: str) -> str:
        """只接受 prod／dev；其餘（含拼錯的 production）一律當 prod。

        往 prod 收斂是刻意的保守方向：把測試站誤標成正式站，最壞是你多做一次確認；
        反過來把正式站標成「測試環境」，你會以為在動假資料而放心亂改。
        """
        return value if value in ("prod", "dev") else "prod"

    # F164 內建對話：server 代打 LLM。key 選填——未設時使用者仍可自填（前端每次請求
    # 以 X-LLM-API-Key 夾帶），兩者皆無時 /api/chat 回 llm_key_missing。
    llm_api_key: str = ""
    llm_base_url: str = "https://api.anthropic.com"
    llm_model: str = "claude-sonnet-5"
    llm_max_tokens: int = 2048
    llm_timeout_seconds: float = 60.0
    # F31 Web Push（休息結束通知）：缺任一則推播功能停用、其餘照常運作
    vapid_private_key: str = ""  # PKCS8 DER 的 base64url（.env 單行）
    vapid_public_key: str = ""  # 未壓縮公鑰點 base64url＝前端 applicationServerKey
    vapid_subject: str = "mailto:admin@example.com"  # VAPID claims 的 sub
