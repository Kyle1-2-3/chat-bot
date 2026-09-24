from datetime import date

import pytest

import app as appmod


@pytest.mark.parametrize("day", [1, 3, 5])
def test_art_days_have_four_one_hour_slots(day):
    pattern = appmod.afternoon_rules(day)["patterns"][0]
    assert pattern["kind"] == "ART"
    assert [(b["block"], b["start_time"], b["end_time"]) for b in pattern["blocks"]] == [
        (1, "14:00", "15:00"), (2, "15:00", "16:00"),
        (3, "16:00", "17:00"), (4, "17:00", "18:00"),
    ]
    assert (pattern["arts_per_student_min"], pattern["arts_per_student_max"]) == (2, 4)


@pytest.mark.parametrize("day", [2, 4, 6])
def test_sport_days_have_a_window_not_an_assigned_time(day):
    pattern = appmod.afternoon_rules(day)["patterns"][0]
    assert pattern["kind"] == "SPORT"
    assert (pattern["window_start"], pattern["window_end"]) == ("14:00", "18:00")
    assert pattern["times_vary_by_sport"] is True
    assert "blocks" not in pattern


def test_sunday_has_no_invented_pattern():
    rules = appmod.afternoon_rules(7)
    assert rules["patterns"] == []
    assert rules["personal_schedule_url"] == appmod.MYSCHOOL_URL


def test_general_art_block_question_does_not_assume_today(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 9, 24))  # Sport Day
    result = appmod.build_result_from_classification(
        {"intent": "AFTERNOON", "day_ref": "ANY"}, "When is art block 2?"
    )
    assert "day_name" not in result
    assert [p["kind"] for p in result["patterns"]] == ["ART", "SPORT"]


def test_tomorrow_afternoon_uses_school_date(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 9, 23))
    result = appmod.build_result_from_classification(
        {"intent": "AFTERNOON", "day_ref": "TOMORROW"}, "Tomorrow afternoon?"
    )
    assert result["date"] == "2026-09-24" and result["day_name"] == "Thursday"
    assert result["patterns"][0]["kind"] == "SPORT"


def test_full_day_includes_shared_afternoon_without_polluting_academic_blocks(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 9, 23))
    timeline = [{"item_type": "BLOCK", "block_code": "A", "start_time": "08:15"}]
    monkeypatch.setattr(appmod, "fetch_timeline_by_date", lambda _: timeline)
    result = appmod.build_result_from_classification({"intent": "SCHEDULE", "day_ref": "TODAY"}, "Today's schedule")
    assert result["rows"] == timeline
    assert result["afternoon"]["patterns"][0]["kind"] == "ART"


@pytest.mark.parametrize("message", ["What art do I have?", "When is my rugby?", "Which art block am I in?"])
def test_personal_activity_uses_static_redirect_without_looking_up_another_student(monkeypatch, message):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "PERSONAL_ACTIVITY", "day_ref": "ANY"}
    ])
    def unexpected(*args, **kwargs):
        raise AssertionError("Personal activity requests must use only the static redirect")
    monkeypatch.setattr(appmod, "query", unexpected)
    monkeypatch.setattr(appmod, "generate_answer", unexpected)
    response = appmod.app.test_client().post("/chat", json={"message": message})
    assert response.status_code == 200
    assert response.get_json()["reply"] == appmod.PERSONAL_ACTIVITY_REPLY


def test_mixed_question_keeps_personal_redirect_and_other_answer(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "PERSONAL_ACTIVITY", "day_ref": "ANY"},
        {"intent": "AFTERNOON", "day_ref": "MONDAY"},
    ])
    captured = {}
    def generate(message, classifications, results):
        captured["results"] = results
        return "combined answer"
    monkeypatch.setattr(appmod, "generate_answer", generate)
    response = appmod.app.test_client().post("/chat", json={"message": "What art do I have, and what is Monday afternoon like?"})
    assert response.status_code == 200
    assert captured["results"][0] == {"type": "PERSONAL_ACTIVITY", "reply": appmod.PERSONAL_ACTIVITY_REPLY}
    assert captured["results"][1]["patterns"][0]["kind"] == "ART"


@pytest.mark.parametrize("intent", ["AFTERNOON", "PERSONAL_ACTIVITY"])
def test_classifier_result_accepts_afternoon_intents(intent):
    assert appmod.validate_request({"intent": intent})["intent"] == intent
