from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_zh: Mapped[str] = mapped_column(String, unique=True)
    name_en: Mapped[str] = mapped_column(String, unique=True)
    muscle_group: Mapped[str] = mapped_column(String)
    is_bodyweight: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Template(Base):
    """課表：動作清單＋順序＋預設組數。刪除不影響歷史 workout（workouts.template_id 無 FK）。"""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    # F80 排程：ISO 星期（1=週一…7=週日）的逗號字串，例 "1,3,5"。
    # NULL＝這份課表沒排進星期（升級上來的舊資料都是這樣）。
    # 用字串而非關聯表：一份課表最多七個小整數，開一張表換來的正規化不值得多一次 join。
    weekdays: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    exercises: Mapped[list["TemplateExercise"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TemplateExercise.position",
    )


class TemplateExercise(Base):
    __tablename__ = "template_exercises"

    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    default_sets: Mapped[int] = mapped_column()
    rest_hint_seconds: Mapped[int | None] = mapped_column(default=None)

    template: Mapped[Template] = relationship(back_populates="exercises")
    exercise: Mapped[Exercise] = relationship()


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    template_id: Mapped[int | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # F91：這場訓練已結束（按過「結束訓練／收工」）。NULL＝進行中或從未正常結束。
    # 存在的理由是**跨裝置**：結束只清當下那台的快取，另一台的舊快取會把它接下去。
    # 刻意不擋 sets 寫入——離線佇列裡先記的組必須補得進去（見 docs/decisions/）。
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    sets: Mapped[list["WorkoutSet"]] = relationship(back_populates="workout")


class BodyMetric(Base):
    """體重體脂 SSOT：一天一筆（date UNIQUE），同日重送為覆蓋更新。"""

    __tablename__ = "body_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailyStatus(Base):
    """當日狀態：一天一筆（date UNIQUE），同日重送為覆蓋更新；休息日也可記，不依附 workout。"""

    __tablename__ = "daily_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    energy: Mapped[int] = mapped_column()
    sleep_quality: Mapped[int | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkoutSet(Base):
    """一組訓練，append-only：不做 update，記錯用軟刪除（deleted_at）。"""

    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_uuid: Mapped[str] = mapped_column(String, unique=True, index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"), index=True)
    set_number: Mapped[int] = mapped_column()
    weight_kg: Mapped[float] = mapped_column(Float)
    reps: Mapped[int] = mapped_column()
    rpe: Mapped[int | None] = mapped_column(default=None)
    rest_seconds: Mapped[int | None] = mapped_column(default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    workout: Mapped[Workout] = relationship(back_populates="sets")


class PushSubscription(Base):
    """F31 Web Push 訂閱：一台裝置一筆，以 endpoint 唯一。單人 app 但可多裝置。"""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(String, unique=True, index=True)
    p256dh: Mapped[str] = mapped_column(String)  # 訂閱公鑰
    auth: Mapped[str] = mapped_column(String)  # 驗證秘密
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppSetting(Base):
    """F80 應用設定：單人系統的 key/value 小表。

    第一個 key 是 weekly_target_days（每週想練幾天）。用 key/value 而不是逐項加欄位，
    是因為這類設定會零星長出來（預設休息秒數、單位…），每次加欄位就得改 schema 與遷移。
    值一律存字串，語意與值域由 services/settings.py 負責——DB 不是驗證的地方。
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
