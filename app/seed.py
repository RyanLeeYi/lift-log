"""動作庫預載：台灣健身房常見動作（雙語），冪等——已存在的名稱跳過。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Exercise

# (name_zh, name_en, muscle_group, is_bodyweight)
DEFAULT_EXERCISES: list[tuple[str, str, str, bool]] = [
    # 腿
    ("深蹲", "Squat", "腿", False),
    ("前蹲舉", "Front Squat", "腿", False),
    ("腿推", "Leg Press", "腿", False),
    ("羅馬尼亞硬舉", "Romanian Deadlift", "腿", False),
    ("腿彎舉", "Leg Curl", "腿", False),
    ("腿伸展", "Leg Extension", "腿", False),
    ("保加利亞分腿蹲", "Bulgarian Split Squat", "腿", False),
    ("弓步蹲", "Lunge", "腿", False),
    ("站姿提踵", "Standing Calf Raise", "腿", False),
    # 背
    ("硬舉", "Deadlift", "背", False),
    ("引體向上", "Pull-up", "背", True),
    ("滑輪下拉", "Lat Pulldown", "背", False),
    ("槓鈴划船", "Barbell Row", "背", False),
    ("坐姿划船", "Seated Cable Row", "背", False),
    ("單臂啞鈴划船", "One-arm Dumbbell Row", "背", False),
    ("聳肩", "Shrug", "背", False),
    # 胸
    ("臥推", "Bench Press", "胸", False),
    ("上斜臥推", "Incline Bench Press", "胸", False),
    ("啞鈴臥推", "Dumbbell Bench Press", "胸", False),
    ("啞鈴飛鳥", "Dumbbell Fly", "胸", False),
    ("繩索夾胸", "Cable Crossover", "胸", False),
    ("伏地挺身", "Push-up", "胸", True),
    ("雙槓下推", "Dip", "胸", True),
    # 肩
    ("肩推", "Overhead Press", "肩", False),
    ("啞鈴肩推", "Dumbbell Shoulder Press", "肩", False),
    ("側平舉", "Lateral Raise", "肩", False),
    ("面拉", "Face Pull", "肩", False),
    ("後三角飛鳥", "Reverse Fly", "肩", False),
    # 手臂
    ("槓鈴彎舉", "Barbell Curl", "手臂", False),
    ("啞鈴彎舉", "Dumbbell Curl", "手臂", False),
    ("三頭下壓", "Triceps Pushdown", "手臂", False),
    ("窄握臥推", "Close-grip Bench Press", "手臂", False),
    # 核心
    ("棒式", "Plank", "核心", True),
    ("懸吊舉腿", "Hanging Leg Raise", "核心", True),
    ("腹部滾輪", "Ab Wheel Rollout", "核心", True),
]


def seed_exercises(session: Session) -> int:
    """寫入預載動作，回傳新增筆數；已存在（任一語言名稱重複）跳過。"""
    existing_zh = set(session.scalars(select(Exercise.name_zh)))
    existing_en = {n.lower() for n in session.scalars(select(Exercise.name_en))}
    created = 0
    for name_zh, name_en, muscle_group, is_bodyweight in DEFAULT_EXERCISES:
        if name_zh in existing_zh or name_en.lower() in existing_en:
            continue
        session.add(
            Exercise(
                name_zh=name_zh,
                name_en=name_en,
                muscle_group=muscle_group,
                is_bodyweight=is_bodyweight,
            )
        )
        created += 1
    session.commit()
    return created
