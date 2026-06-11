from datetime import date

import app as appmod
import set_up_db


def seed(tmp_path, monkeypatch):
    db = tmp_path / "school.db"
    monkeypatch.setattr(set_up_db, "DB_PATH", str(db))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))


# ---------------------------
# fetch_bedtime
# ---------------------------
def test_fetch_bedtime_weekday_and_saturday(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    assert appmod.fetch_bedtime(11, 1) == {"has_rule": True, "bedtime": "22:15"}  # Mon
    assert appmod.fetch_bedtime(11, 6) == {"has_rule": True, "bedtime": "23:15"}  # Sat +1h


def test_fetch_bedtime_grade12_no_bedtime(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    assert appmod.fetch_bedtime(12, 1) == {"has_rule": True, "bedtime": None}


def test_fetch_bedtime_grade8_no_rule(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    assert appmod.fetch_bedtime(8, 1) == {"has_rule": False, "bedtime": None}


# ---------------------------
# build_result for BEDTIME
# ---------------------------
def test_build_result_bedtime(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 20))  # Monday
    res = appmod.build_result_from_classification(
        {"intent": "BEDTIME", "grade": 10, "day_ref": "SATURDAY", "meal_type": None}, "")
    assert res["type"] == "BEDTIME"
    assert res["grade"] == 10
    assert res["day_name"] == "Saturday"
    assert res["bedtime"] == "23:00"
    assert res["has_rule"] is True


def test_build_result_bedtime_missing_grade(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    res = appmod.build_result_from_classification(
        {"intent": "BEDTIME", "grade": None, "day_ref": "ANY", "meal_type": None}, "")
    assert res["type"] == "BEDTIME"
    assert res["grade"] is None
    assert res["has_rule"] is False


# ---------------------------
# /chat end-to-end (classifier mocked)
# ---------------------------
def test_chat_bedtime(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 20))  # Monday
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "BEDTIME", "grade": 9, "day_ref": "TODAY", "meal_type": None}])
    captured = {}
    monkeypatch.setattr(appmod, "generate_answer",
                        lambda msg, cls, results: captured.setdefault("r", results) or "ok")
    appmod.app.test_client().post("/chat", json={"message": "grade 9 bedtime tonight?"})
    assert captured["r"][0]["bedtime"] == "21:45"
    assert captured["r"][0]["day_name"] == "Monday"
