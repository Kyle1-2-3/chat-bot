import copy
import json
from types import SimpleNamespace

import pytest

import app as bot
from answer_prompts import ANSWER_COMMON, ANSWER_RULES, answer_system_for


def timetable():
    return [
        {"item_type": "BLOCK", "block_code": "D", "start_time": "08:15", "end_time": "09:35"},
        {"item_type": "COOKIE_BREAK", "start_time": "09:35", "end_time": "09:55"},
        {"item_type": "ASSEMBLY", "start_time": "09:55", "end_time": "10:20"},
        {"item_type": "BLOCK", "block_code": "E", "start_time": "10:25", "end_time": "11:45"},
        {"item_type": "BLOCK", "block_code": "F", "start_time": "11:55", "end_time": "13:15"},
        {"item_type": "EVENT", "event_name": "XC - Glenora Trails Head Race",
         "start_time": "14:00", "end_time": "16:30"},
    ]


def test_block_order_returns_class_times_and_events_without_model(monkeypatch):
    monkeypatch.setenv("FAKE_TODAY", "2026-10-01")
    monkeypatch.setattr(bot, "fetch_timeline_by_date", lambda _: timetable())
    monkeypatch.setattr(bot, "leave_on", lambda _: None)
    def fail(*args, **kwargs):
        pytest.fail("Simple academic timetable should need no model call")
    monkeypatch.setattr(bot.client.models, "generate_content", fail)
    response = bot.app.test_client().post("/chat", json={"message": "What's the block order today?"})
    assert response.status_code == 200
    reply = response.get_json()["reply"]
    assert "Here's the class timetable for **Thursday**" in reply
    for expected in ("Block D", "Block E", "Block F", "8:15 AM", "1:15 PM", "Cookie Break",
                     "Assembly", "Events", "XC - Glenora Trails Head Race", "4:30 PM"):
        assert expected in reply
    for unasked in ("Sport Day", "Art Day", "MySchool", "6:00 PM", "sign-in"):
        assert unasked not in reply


@pytest.mark.parametrize("scope,include_afternoon", [("ACADEMIC", False), ("SPECIFIC", False), ("FULL_DAY", True)])
def test_schedule_payload_and_rules_have_matching_scope(scope, include_afternoon):
    original = {"type": "SCHEDULE", "rows": timetable(), "afternoon": bot.afternoon_rules(4)}
    before = copy.deepcopy(original)
    result = bot.focused_answer_results([{"schedule_focus": scope}], [original])[0]
    prompt = answer_system_for([result])
    assert ("afternoon" in result) is include_afternoon
    assert (ANSWER_RULES["AFTERNOON"].strip() in prompt) is include_afternoon
    assert ANSWER_RULES["SCHEDULE"].strip() in prompt
    assert original == before


def test_mixed_question_gets_union_of_rules_without_duplicates_or_unrelated_topics():
    prompt = answer_system_for([
        {"type": "MEALS_DAY", "meal_focus": "MENU"}, {"type": "MEAL", "meal_focus": "MENU"},
        {"type": "MEAL_SIGNIN"}, {"type": "SCHEDULE"},
    ])
    for key in ("MEAL", "MEALS_DAY", "MENU_LINKS", "MEAL_SIGNIN", "SCHEDULE"):
        assert prompt.count(ANSWER_RULES[key].strip()) == 1
    for key in ("AFTERNOON", "BEDTIME", "SCHOOL_INFO", "SCHOOL_BREAKS", "SCHOOL_LEAVE"):
        assert ANSWER_RULES[key].strip() not in prompt
    assert prompt.startswith(ANSWER_COMMON.strip())


def test_serving_time_prompt_omits_menu_link_and_signin_instructions():
    prompt = answer_system_for([{"type": "MEAL", "meal_focus": "TIMES"}])
    assert ANSWER_RULES["MEAL"].strip() in prompt
    assert ANSWER_RULES["MENU_LINKS"].strip() not in prompt
    assert ANSWER_RULES["MEAL_SIGNIN"].strip() not in prompt


def test_model_receives_only_selected_rules_and_scoped_data(monkeypatch):
    captured = {}
    def generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text="Here's the timetable for Thursday.")
    monkeypatch.setattr(bot.client.models, "generate_content", generate)
    data = {"type": "SCHEDULE", "day_name": "Thursday", "rows": timetable(),
            "afternoon": bot.afternoon_rules(4)}
    bot.generate_answer("목요일 수업 시간표 알려줘", [{"schedule_focus": "ACADEMIC"}], [data])
    sent = json.loads(captured["contents"])["results"]
    assert "afternoon" not in sent[0]
    assert captured["config"].system_instruction == answer_system_for(sent)
    assert ANSWER_RULES["SCHOOL_INFO"].strip() not in captured["config"].system_instruction


def test_leave_timetable_keeps_qualified_model_response_and_leave_rules(monkeypatch):
    captured = {}
    def generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text="Thursday falls during Winter Break.")
    monkeypatch.setattr(bot.client.models, "generate_content", generate)
    cls = [{"intent": "SCHEDULE", "schedule_focus": "ACADEMIC"}]
    result = {"type": "SCHEDULE", "day_name": "Thursday", "rows": [],
              "school_leave": {"name": "Winter Break", "full_day": True}}
    bot.generate_answer("What's the block order today?", cls, [result])
    assert ANSWER_RULES["SCHOOL_LEAVE"].strip() in captured["config"].system_instruction


def test_empty_timetable_does_not_invent_free_period_or_afternoon():
    reply = bot.render_academic_timetable({"day_name": "Sunday", "rows": []})
    assert "don't have the class timetable" in reply
    assert "free" not in reply.lower()


def test_saturday_inspection_renders_without_model_fallback():
    reply = bot.render_academic_timetable({"day_name": "Saturday", "rows": [
        {"item_type": "INSPECTION", "block_code": None, "start_time": "09:30", "end_time": "10:00"},
        {"item_type": "BLOCK", "block_code": "A", "start_time": "10:15", "end_time": "11:00"},
    ]})
    assert "Inspection:** 9:30 AM – 10:00 AM" in reply
    assert "Block A:** 10:15 AM – 11:00 AM" in reply


def test_all_day_and_missing_event_times_are_not_invented():
    reply = bot.render_academic_timetable({"day_name": "Friday", "rows": [
        {"item_type": "EVENT", "event_name": "Community Day", "all_day": 1},
        {"item_type": "EVENT", "event_name": "Meeting"},
    ]})
    assert "Community Day:** All day" in reply
    assert "Meeting:** Time not listed" in reply


@pytest.mark.parametrize("message,scope", [
    ("What's the block order today?", "ACADEMIC"),
    ("class timetable tomorrow", "ACADEMIC"),
    ("What's the whole school schedule tomorrow?", "FULL_DAY"),
])
def test_fast_schedule_routing_keeps_requested_scope(message, scope):
    assert bot.quick_classify(message)[0]["schedule_focus"] == scope
