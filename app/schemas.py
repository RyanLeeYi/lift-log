from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExerciseCreate(BaseModel):
    name_zh: str = Field(min_length=1)
    name_en: str = Field(min_length=1)
    muscle_group: str = Field(min_length=1)
    is_bodyweight: bool = False


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


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1)
    exercises: list[TemplateExerciseIn] = Field(min_length=1)


class TemplateExerciseOut(BaseModel):
    exercise_id: int
    position: int
    default_sets: int
    name_zh: str
    name_en: str
    muscle_group: str
    is_bodyweight: bool


class TemplateOut(BaseModel):
    id: int
    name: str
    exercises: list[TemplateExerciseOut]


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


class BodyMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date_type
    weight_kg: float
    body_fat_pct: float | None


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
