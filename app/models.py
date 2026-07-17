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

    template: Mapped[Template] = relationship(back_populates="exercises")
    exercise: Mapped[Exercise] = relationship()


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    template_id: Mapped[int | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

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
