"""F10 自訂動作（使用者新增）：POST /api/exercises 的選填欄位與重複擋下。

acceptance：中文名必填；英文名、部位選填；自體重勾選；重複（zh 或 en 任一）擋下並提示。
英文名留空 → 後端以中文名鏡射填入（避開 name_en unique 非空欄位的 nullable 重建）。
部位留空 → 預設「其他」。重複比對走正規化（strip+lower）語意，與 log_workout 名稱解析一致。
"""

from fastapi.testclient import TestClient


def test_create_with_only_name_zh_mirrors_en_and_defaults_group(client: TestClient) -> None:
    resp = client.post("/api/exercises", json={"name_zh": "保加利亞分腿蹲"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name_zh"] == "保加利亞分腿蹲"
    assert body["name_en"] == "保加利亞分腿蹲"  # 英文名留空 → 鏡射中文名
    assert body["muscle_group"] == "其他"  # 部位留空 → 預設
    assert body["is_bodyweight"] is False


def test_create_with_all_fields_preserved(client: TestClient) -> None:
    resp = client.post(
        "/api/exercises",
        json={
            "name_zh": "引體向上",
            "name_en": "Pull Up",
            "muscle_group": "背",
            "is_bodyweight": True,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name_zh"] == "引體向上"
    assert body["name_en"] == "Pull Up"
    assert body["muscle_group"] == "背"
    assert body["is_bodyweight"] is True


def test_create_missing_name_zh_rejected(client: TestClient) -> None:
    resp = client.post("/api/exercises", json={"name_en": "Only English"})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_create_blank_name_zh_rejected(client: TestClient) -> None:
    resp = client.post("/api/exercises", json={"name_zh": "   "})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_duplicate_name_zh_blocked(client: TestClient, exercise_id: int) -> None:
    # exercise_id fixture 已建「深蹲 / Squat / 腿」；帶齊選填欄位，確保 400 只可能來自重複
    resp = client.post(
        "/api/exercises",
        json={"name_zh": "深蹲", "name_en": "Back Squat", "muscle_group": "腿"},
    )
    assert resp.status_code == 400
    assert "exists" in resp.json()["error"]


def test_duplicate_name_en_blocked(client: TestClient, exercise_id: int) -> None:
    resp = client.post(
        "/api/exercises",
        json={"name_zh": "後蹲", "name_en": "Squat", "muscle_group": "腿"},
    )
    assert resp.status_code == 400
    assert "exists" in resp.json()["error"]


def test_duplicate_normalized_case_and_whitespace_blocked(
    client: TestClient, exercise_id: int
) -> None:
    # 既有 en「Squat」；新動作 en「  squat 」正規化後相同 → 擋下（DB 精確比對擋不到，靠前置檢查）
    resp = client.post(
        "/api/exercises",
        json={"name_zh": "深蹲變化", "name_en": "  squat ", "muscle_group": "腿"},
    )
    assert resp.status_code == 400
    assert "exists" in resp.json()["error"]


def test_created_exercise_appears_in_search(client: TestClient) -> None:
    client.post(
        "/api/exercises",
        json={"name_zh": "面拉", "name_en": "Face Pull", "muscle_group": "肩"},
    )
    resp = client.get("/api/exercises")
    assert resp.status_code == 200
    names = [e["name_zh"] for e in resp.json()]
    assert "面拉" in names


def test_name_zh_trimmed_on_create(client: TestClient) -> None:
    resp = client.post("/api/exercises", json={"name_zh": "  硬舉  ", "name_en": "  Deadlift "})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name_zh"] == "硬舉"
    assert body["name_en"] == "Deadlift"
