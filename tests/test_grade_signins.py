from datetime import date

import pytest

import app as appmod
import set_up_db


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    set_up_db.init_db()
    monkeypatch.setattr(appmod, "DB_PATH", set_up_db.DB_PATH)


@pytest.mark.parametrize("grade, night", [(9, "22:00"), (10, "22:00"), (11, "22:30"), (12, "23:00")])
def test_saturday_signin_is_grade_specific(seeded, grade, night):
    rows = appmod.fetch_dorm_signins(6, grade)
    assert [r["start_time"] for r in rows] == ["19:15", night]
    assert all(r["grade_ids"] == [grade] for r in rows)


def test_general_saturday_answer_splits_senior_grades(seeded):
    rows = appmod.fetch_dorm_signins(6)
    assert [(r["group_name"], r["start_time"]) for r in rows if r["rule_order"] == 2] == [
        ("Junior", "22:00"), ("Grade 11", "22:30"), ("Grade 12", "23:00")]
    assert len([r for r in rows if r["group_name"] == "Senior" and r["start_time"] == "19:15"]) == 1


def test_grade_12_override_does_not_change_weekday_or_sunday(seeded):
    assert [r["start_time"] for r in appmod.fetch_dorm_signins(1, 12)] == ["19:15"]
    assert [r["start_time"] for r in appmod.fetch_dorm_signins(7, 12)] == [None, "19:15", "21:15"]


def test_day_student_grade_is_not_added_to_dorm_groups(seeded):
    assert appmod.fetch_dorm_signins(6, 8) == []
    assert all(8 not in row["grade_ids"] for row in appmod.fetch_dorm_signins(6))


def test_signin_result_keeps_only_requested_grade_and_meal_group(seeded, monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 9, 23))
    result = appmod.build_result_from_classification(
        {"intent": "SIGNIN_SUMMARY", "day_ref": "SATURDAY", "grade": 12}, "grade 12 Saturday sign in")
    assert result["grade"] == 12
    assert [r["start_time"] for r in result["dorm_signins"]] == ["19:15", "23:00"]
    assert all(r["group_name"] == "Senior" for r in result["meal_signins"])
