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


def test_grade_12_signin_result_has_only_house_signins(seeded, monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 9, 23))
    result = appmod.build_result_from_classification(
        {"intent": "SIGNIN_SUMMARY", "day_ref": "SATURDAY", "grade": 12}, "grade 12 Saturday sign in")
    assert result["grade"] == 12
    assert [r["start_time"] for r in result["dorm_signins"]] == ["19:15", "23:00"]
    assert result["meal_signins"] == []
    assert result["meal_signin_exempt_grades"] == [12]


@pytest.mark.parametrize("day", range(1, 8))
def test_grade_12_never_has_meal_signins_and_keeps_serving_times(seeded, day):
    grade12 = appmod.fetch_day_meals(day, 12)
    grade11 = appmod.fetch_day_meals(day, 11)
    assert grade12 and all(r["requires_signin"] == 0 for r in grade12)
    assert all(r["grade_ids"] == [12] for r in grade12)
    assert [(r["type_name"], r["start_time"], r["end_time"], r["menu_content"]) for r in grade12] == [
        (r["type_name"], r["start_time"], r["end_time"], r["menu_content"]) for r in grade11]
    assert {r["type_name"] for r in grade11 if r["requires_signin"]} == (
        {"DINNER"} if day == 7 else {"BREAKFAST", "DINNER"})


@pytest.mark.parametrize("grade", [9, 10, 11])
def test_other_grades_keep_their_meal_requirements(seeded, grade):
    rows = appmod.fetch_day_meals(1, grade)
    assert {r["type_name"]: r["requires_signin"] for r in rows} == {
        "BREAKFAST": 1, "LUNCH": 0, "DINNER": 1}


@pytest.mark.parametrize("meal", ["BREAKFAST", "DINNER", None])
def test_direct_meal_signin_answer_respects_grade_12_exemption(seeded, meal):
    result = appmod.build_result_from_classification(
        {"intent": "MEAL_SIGNIN", "grade": 12, "meal_type": meal, "day_ref": "MONDAY"}, "gr12 meal sign in")
    assert result["grade"] == 12 and result["rows"]
    assert all(r["requires_signin"] == 0 and r["grade_ids"] == [12] for r in result["rows"])


def test_general_summary_does_not_apply_grade_11_meal_rules_to_grade_12(seeded):
    result = appmod.build_result_from_classification(
        {"intent": "SIGNIN_SUMMARY", "day_ref": "SATURDAY"}, "Saturday sign-ins")
    assert result["meal_signins"]
    assert all(12 not in r["grade_ids"] for r in result["meal_signins"])
    assert any(r["grade_ids"] == [11] and r["type_name"] == "DINNER" for r in result["meal_signins"])
    assert any(r["grade_ids"] == [12] and r["start_time"] == "23:00" for r in result["dorm_signins"])


@pytest.mark.parametrize("intent", ["MEAL", "MEALS_DAY"])
def test_menu_answers_also_use_the_correct_grade_rule(seeded, intent):
    result = appmod.build_result_from_classification(
        {"intent": intent, "grade": 12, "day_ref": "MONDAY", "meal_type": "DINNER"}, "gr12 meals")
    assert result["grade"] == 12 and result["rows"]
    assert all(r["requires_signin"] == 0 and r["grade_ids"] == [12] for r in result["rows"])
