import app as appmod
import set_up_db


def seed(tmp_path, monkeypatch):
    db = tmp_path / "school.db"
    monkeypatch.setattr(set_up_db, "DB_PATH", str(db))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))


# ---------------------------
# fetch_grade_group
# ---------------------------
def test_fetch_grade_group_maps_grades(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    assert appmod.fetch_grade_group(8) == "Junior"
    assert appmod.fetch_grade_group(10) == "Junior"
    assert appmod.fetch_grade_group(11) == "Senior"
    assert appmod.fetch_grade_group(12) == "Senior"


def test_fetch_grade_group_unknown_grade(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    assert appmod.fetch_grade_group(7) is None
    assert appmod.fetch_grade_group(99) is None


# ---------------------------
# validate_request keeps a valid grade, drops junk
# ---------------------------
def test_validate_request_grade():
    assert appmod.validate_request({"intent": "GRADE_GROUP", "grade": 11})["grade"] == 11
    assert appmod.validate_request({"intent": "GRADE_GROUP", "grade": "eleven"})["grade"] is None
    assert appmod.validate_request({"intent": "MEAL", "day_ref": "TODAY"})["grade"] is None


# ---------------------------
# build_result for GRADE_GROUP
# ---------------------------
def test_build_result_grade_group(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    res = appmod.build_result_from_classification(
        {"intent": "GRADE_GROUP", "grade": 11, "day_ref": "ANY", "meal_type": None}, "")
    assert res["type"] == "GRADE_GROUP"
    assert res["grade"] == 11
    assert res["group_name"] == "Senior"


def test_build_result_grade_group_missing_grade(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    res = appmod.build_result_from_classification(
        {"intent": "GRADE_GROUP", "grade": None, "day_ref": "ANY", "meal_type": None}, "")
    assert res["type"] == "GRADE_GROUP"
    assert res["group_name"] is None  # answer should then ask for the grade


# ---------------------------
# /chat end-to-end (classifier mocked)
# ---------------------------
def test_chat_grade_group(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "GRADE_GROUP", "grade": 11, "day_ref": "ANY", "meal_type": None}])
    captured = {}
    monkeypatch.setattr(appmod, "generate_answer",
                        lambda msg, cls, results: captured.setdefault("r", results) or "ok")
    appmod.app.test_client().post("/chat", json={"message": "I'm grade 11, junior or senior?"})
    assert captured["r"][0] == {"type": "GRADE_GROUP", "grade": 11, "group_name": "Senior"}
