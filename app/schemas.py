from datetime import date as date_type
from datetime import datetime as datetime_type
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GoogleLoginIn(BaseModel):
    id_token: str = Field(min_length=1, max_length=8192)
    nonce: str = Field(min_length=16, max_length=512)
    device_id: UUID
    device_name: str = Field(min_length=1, max_length=100)
    client: Literal["android", "web"]


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)
    device_id: UUID


class AuthUserOut(BaseModel):
    id: str


class AuthDeviceOut(BaseModel):
    id: str
    name: str


class AndroidAuthOut(BaseModel):
    access_token: str
    expires_in: int
    refresh_token: str
    user: AuthUserOut
    device: AuthDeviceOut


class WebAuthOut(BaseModel):
    csrf_token: str
    user: AuthUserOut
    device: AuthDeviceOut


class AuthSessionOut(BaseModel):
    user: AuthUserOut
    device: AuthDeviceOut


class ReauthIn(BaseModel):
    """F148／PRD R7：匯出／刪帳前的近期 Google 身分重驗——欄位形狀同登入的 id_token+nonce。"""

    id_token: str = Field(min_length=1, max_length=8192)
    nonce: str = Field(min_length=16, max_length=512)


class AccountDeleteIn(ReauthIn):
    """二次確認：前端要求使用者輸入 DELETE 才會帶上這個值。"""

    confirm: Literal["DELETE"]


class McpTokenCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class McpTokenCreateOut(BaseModel):
    id: str
    name: str
    token: str
    created_at: datetime_type


class McpTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime_type
    last_used_at: datetime_type | None
    revoked_at: datetime_type | None


class ExerciseCreate(BaseModel):
    # F10 自訂動作：中文名必填；英文名、部位選填（留空由 service 補齊：en 鏡射 zh、部位預設其他）
    name_zh: str = Field(min_length=1)
    name_en: str | None = None
    muscle_group: str | None = None
    is_bodyweight: bool = False

    @field_validator("name_zh")
    @classmethod
    def _name_zh_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("name_zh required")
        return stripped

    @field_validator("name_en", "muscle_group")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


class ExerciseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name_zh: str
    name_en: str
    muscle_group: str
    is_bodyweight: bool


class TemplateExerciseIn(BaseModel):
    exercise_id: int
    default_sets: int = Field(gt=0)
    # R10 參考休息：選填；未設=null（前端以 60s 為預設倒數）
    rest_hint_seconds: int | None = Field(default=None, ge=15, le=600)


def _clean_weekdays(v: list[int] | None) -> list[int] | None:
    """F80：ISO 星期（1=週一…7=週日）。去重排序後回傳；空清單視為「沒排程」＝None。

    值域錯誤在這裡就擋下來（→ 400），不讓 "8" 或 "0" 進到 DB 的字串欄位裡——
    存成字串的代價就是 DB 幫不上忙，驗證只能在邊界做足。
    """
    if v is None:
        return None
    if any(day < 1 or day > 7 for day in v):
        raise ValueError("weekday must be 1-7 (1=Mon)")
    return sorted(set(v)) or None


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1)
    exercises: list[TemplateExerciseIn] = Field(min_length=1)
    # F80：排程；未提供＝不排（PUT 整份取代時，沒帶就是清掉排程）
    weekdays: list[int] | None = None

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, v: list[int] | None) -> list[int] | None:
        return _clean_weekdays(v)


class TemplateWeekdaysPatch(BaseModel):
    """只改排程，不動動作清單（課表列表上直接排星期用）。"""

    weekdays: list[int] | None = None

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, v: list[int] | None) -> list[int] | None:
        return _clean_weekdays(v)


class TemplateExerciseOut(BaseModel):
    exercise_id: int
    position: int
    default_sets: int
    rest_hint_seconds: int | None
    name_zh: str
    name_en: str
    muscle_group: str
    is_bodyweight: bool


class TemplateOut(BaseModel):
    id: int
    name: str
    exercises: list[TemplateExerciseOut]
    weekdays: list[int] = Field(default_factory=list)  # F80：沒排程回空陣列，前端不必判 null
    # F82 挑課表畫面：這份課表上次練是什麼時候、練了多少（沒練過為 None）
    last_used_date: date_type | None = None
    last_volume_kg: float | None = None


class SettingOut(BaseModel):
    key: str
    value: str


class SettingIn(BaseModel):
    value: str = Field(min_length=1)


class ScheduledTemplate(BaseModel):
    """今天排到的一份課表（一天可以有多份——早上推、晚上有氧）。"""

    id: int
    name: str
    exercise_count: int
    set_count: int


class LastWorkout(BaseModel):
    """首頁「上次訓練」卡。沒有任何歷史時整個欄位為 None，前端就不畫這張卡。"""

    date: date_type
    template_name: str | None
    set_count: int
    volume_kg: float


class ScheduleTodayOut(BaseModel):
    date: date_type
    weekday: int  # ISO 1=週一…7=週日
    templates: list[ScheduledTemplate]
    last_workout: LastWorkout | None = None  # F81：首頁的「上次訓練」
    weekly_target_days: int
    week_done_days: int  # 本週（週一起算）有記錄的不重複天數
    week_days: list[bool]  # 週一…週日，各日有沒有練——首頁的七段進度條


class WorkoutCreate(BaseModel):
    date: date_type | None = None
    template_id: int | None = None
    note: str | None = None


class SetCreate(BaseModel):
    client_uuid: str = Field(min_length=8)
    exercise_id: int
    # F131 ③：省略時由 server 算（該 workout 該動作最大組號 +1）。選填是為了讓原生側的
    # 寫入路徑不必把 F32 的組號規則再實作一份；有帶就沿用，前端與匯入路徑行為不變。
    set_number: int | None = Field(default=None, gt=0)
    weight_kg: float = Field(ge=0)
    reps: int = Field(gt=0)
    rpe: int | None = Field(default=None, ge=1, le=10)
    rest_seconds: int | None = Field(default=None, ge=0)


class SetUpdate(BaseModel):
    """F16 原位編輯一組：只改可修的量測欄位；set_number/exercise/client_uuid 不動。

    未帶的選填欄位（rpe/rest_seconds）＝清掉，不沿用舊值（編輯表單所見即所存）。
    """

    weight_kg: float = Field(ge=0)
    reps: int = Field(gt=0)
    rpe: int | None = Field(default=None, ge=1, le=10)
    rest_seconds: int | None = Field(default=None, ge=0)


class LogSetIn(BaseModel):
    """MCP 代記錄的一組：動作以雙語名稱指定（非 id）。"""

    exercise: str = Field(min_length=1)
    weight_kg: float = Field(ge=0)
    reps: int = Field(gt=0)
    rpe: int | None = Field(default=None, ge=1, le=10)

    @field_validator("exercise")
    @classmethod
    def _strip_and_require_content(cls, value: str) -> str:
        # 空白名若放行，create_missing 會建出空名動作、_suggest 對空字串全命中
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class LogWorkoutIn(BaseModel):
    sets: list[LogSetIn] = Field(min_length=1)
    date: date_type | None = None
    template: str | None = None
    note: str | None = None
    create_missing: bool = False
    client_uuid: str | None = Field(default=None, min_length=8)
    """呼叫端冪等鍵：timeout 重試帶同值不會重複寫入（每組落庫為 client_uuid:序號）。"""
    # F152：只算將發生什麼、不寫入、不留任何新列。
    dry_run: bool = False


class LogWorkoutSummary(BaseModel):
    workout_id: int
    date: date_type
    sets_count: int
    tonnage_kg: float
    # F151：這次呼叫實際新寫入 vs 因冪等鍵命中而略過的組數
    created_count: int
    skipped_count: int


class BatchDryRunPreviewItem(BaseModel):
    """F152：dry-run 預覽單筆；index 是原 payload 內的 0-based 位置。"""

    index: int
    exercise: str
    weight_kg: float
    reps: int
    disposition: Literal["create", "skip", "conflict"]


class BatchDryRunSummary(BaseModel):
    """F152：批次寫入 dry-run 摘要——回傳前不寫入任何資料、不產生 change log。"""

    will_create_count: int
    will_skip_count: int
    will_conflict_count: int
    preview: list[BatchDryRunPreviewItem]


class ExerciseName(BaseModel):
    name_zh: str
    name_en: str


class ProgressPoint(BaseModel):
    date: date_type
    top_weight_kg: float
    reps: int


class ProgressOut(BaseModel):
    """進步曲線：每次訓練該動作的最大重量與該重量的次數。"""

    exercise: ExerciseName
    points: list[ProgressPoint]


class BodyMetricIn(BaseModel):
    date: date_type | None = None
    weight_kg: float = Field(ge=30, le=300)
    body_fat_pct: float | None = Field(default=None, gt=0, lt=100)


class BodyMetricBounds(BaseModel):
    """F58：體重／體脂各自的最早紀錄日與整體最後一天（無資料為 None）。

    `last` 目前前端未使用（僅為端點語意完整）——不要以為有邏輯依賴它。
    """

    weight_first: date_type | None
    fat_first: date_type | None
    last: date_type | None


class BodyMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date_type
    weight_kg: float
    body_fat_pct: float | None


class DailyStatusIn(BaseModel):
    date: date_type | None = None
    energy: int = Field(ge=1, le=5)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None


class DailyStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date_type
    energy: int
    sleep_quality: int | None
    note: str | None


class SetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_uuid: str  # F90：離線佇列判斷「這筆送達了沒」的唯一識別，不回傳的話只能用間接特徵猜
    workout_id: int
    exercise_id: int
    set_number: int
    weight_kg: float
    reps: int
    rpe: int | None
    rest_seconds: int | None


class LastSetOut(SetOut):
    """F84：logger 的「上次提示卡」要顯示日期（「上次 7/22 · 57.5 kg × 8」）。

    只有 last-sets 這一支用它——共用的 SetOut 不動，免得每個回傳組的端點都多帶一個欄位。
    """

    workout_date: date_type


class WorkoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date_type
    template_id: int | None
    note: str | None
    # F83：今日菜單的「已練 N 分」。用伺服器時間而不是前端記的開始時間——
    # app 被系統回收後 sessionStorage 就沒了，但訓練還在進行
    created_at: datetime_type | None = None
    # F91：非 null＝已結束。前端還原時據此拒絕續接（跨裝置一致）
    ended_at: datetime_type | None = None


class WorkoutDetailOut(WorkoutOut):
    sets: list[SetOut]


# F35：動作詳情頁的歷來查詢
class PrEntry(BaseModel):
    weight_kg: float
    reps: int


class PrSummary(BaseModel):
    top_weight: PrEntry | None  # 全期單組最大 weight_kg
    top_set_volume: PrEntry | None  # 全期單組最大 weight_kg × reps
    # F86 ②：PR 卡改成三張，這兩個是新的。都是**全期**值——
    # 從畫面當下的區間去算等於把「這三個月最好的一次」當成個人紀錄顯示。
    top_est_1rm: float | None = None  # Epley：max(w × (1 + reps/30))
    top_session_volume: float | None = None  # 單次訓練總量 Σ(w × reps) 的全期最大值


class HistorySet(BaseModel):
    # F35 R1 契約：只回這 5 欄，不外洩 workout_id/exercise_id/rest_seconds
    model_config = ConfigDict(from_attributes=True)

    id: int
    set_number: int
    weight_kg: float
    reps: int
    rpe: int | None


class HistorySession(BaseModel):
    workout_id: int
    date: date_type
    sets: list[HistorySet]


class ExerciseHistoryOut(BaseModel):
    prs: PrSummary  # 全期個人紀錄（不受 from/to 影響）
    sessions: list[HistorySession]  # 區間內每次訓練的全部組，依日期升冪
    # F59：全期最早訓練日（不受 from/to 影響；無未軟刪的組時為 None）
    # 前端據此停用超出資料範圍的區間檔位
    first_session_date: date_type | None = None


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class PushSubscriptionIn(BaseModel):
    """瀏覽器 PushSubscription.toJSON() 的形狀：{endpoint, keys:{p256dh, auth}}。"""

    endpoint: str = Field(min_length=1)
    keys: PushKeys


class RestTimerIn(BaseModel):
    seconds: int = Field(ge=1, le=3600)  # 休息秒數，到點推「休息結束」通知


class ExerciseLastSet(BaseModel):
    """F83 今日菜單：某個動作「上次」的代表數值（最後一組）。"""

    exercise_id: int
    weight_kg: float
    reps: int


class SyncPushIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    device_id: UUID
    mutations: list[dict[str, Any]] = Field(max_length=500)


class SyncMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mutation_id: UUID
    entity_type: str = Field(min_length=1, max_length=32)
    entity_id: UUID
    operation: str = Field(min_length=1, max_length=16)
    base_version: int = Field(ge=0)
    lease_generation: int | None = Field(default=None, ge=1)
    payload: dict[str, Any]


class _SyncPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_id: UUID


class SyncExercisePayload(_SyncPayload):
    name_zh: str = Field(min_length=1, max_length=100)
    name_en: str = Field(min_length=1, max_length=100)
    muscle_group: str = Field(min_length=1, max_length=100)
    is_bodyweight: bool


class SyncTemplateExercisePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_sync_id: UUID
    position: int = Field(ge=0)
    default_sets: int = Field(gt=0, le=100)
    rest_hint_seconds: int | None = Field(default=None, ge=0, le=3600)


class SyncTemplatePayload(_SyncPayload):
    name: str = Field(min_length=1, max_length=100)
    weekdays: list[int] | None = Field(default=None, max_length=7)
    exercises: list[SyncTemplateExercisePayload] = Field(default_factory=list, max_length=100)

    @field_validator("weekdays")
    @classmethod
    def _sync_weekdays(cls, value: list[int] | None) -> list[int] | None:
        return _clean_weekdays(value)


class SyncWorkoutPayload(_SyncPayload):
    date: date_type
    template_sync_id: UUID | None = None
    note: str | None = Field(default=None, max_length=10_000)
    ended_at: datetime_type | None = None
    owner_device_id: UUID | None = None
    lease_generation: int = Field(default=1, ge=1)


class SyncSetPayload(_SyncPayload):
    client_uuid: str = Field(min_length=8, max_length=100)
    workout_sync_id: UUID
    exercise_sync_id: UUID
    set_number: int = Field(gt=0)
    weight_kg: float = Field(ge=0)
    reps: int = Field(gt=0)
    rpe: int | None = Field(default=None, ge=1, le=10)
    rest_seconds: int | None = Field(default=None, ge=0)


class SyncBodyMetricPayload(_SyncPayload):
    date: date_type
    weight_kg: float = Field(ge=30, le=300)
    body_fat_pct: float | None = Field(default=None, gt=0, lt=100)


class SyncDailyStatusPayload(_SyncPayload):
    date: date_type
    energy: int = Field(ge=1, le=5)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=10_000)


class SyncSettingPayload(_SyncPayload):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=1000)


class SyncDeletePayload(_SyncPayload):
    pass


class SyncAccepted(BaseModel):
    mutation_id: str
    version: int
    server_seq: int


class SyncConflict(BaseModel):
    mutation_id: str | None
    reason: str
    server: dict[str, Any] | None = None


class SyncPushOut(BaseModel):
    accepted: list[SyncAccepted]
    conflicts: list[SyncConflict]


class SyncChangeOut(BaseModel):
    server_seq: int
    schema_version: int
    entity_type: str
    entity_id: str
    operation: str
    version: int
    updated_at: datetime_type
    deleted_at: datetime_type | None
    payload: dict[str, Any]


class SyncPullOut(BaseModel):
    changes: list[SyncChangeOut]
    next_cursor: int
    has_more: bool
