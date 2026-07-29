from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class ScheduleTodayOut(BaseModel):
    date: date_type
    weekday: int  # ISO 1=週一…7=週日
    templates: list[ScheduledTemplate]
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
    set_number: int = Field(gt=0)
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


class LogWorkoutSummary(BaseModel):
    workout_id: int
    date: date_type
    sets_count: int
    tonnage_kg: float


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
    workout_id: int
    exercise_id: int
    set_number: int
    weight_kg: float
    reps: int
    rpe: int | None
    rest_seconds: int | None


class WorkoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date_type
    template_id: int | None
    note: str | None


class WorkoutDetailOut(WorkoutOut):
    sets: list[SetOut]


# F35：動作詳情頁的歷來查詢
class PrEntry(BaseModel):
    weight_kg: float
    reps: int


class PrSummary(BaseModel):
    top_weight: PrEntry | None  # 全期單組最大 weight_kg
    top_set_volume: PrEntry | None  # 全期單組最大 weight_kg × reps


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
