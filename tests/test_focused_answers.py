import copy
import json
from types import SimpleNamespace

import pytest

import app as bot


def row(meal="Lunch", menu="Fish Taco Bowl", grades=None, **extra):
    return {"type_name": meal, "menu_content": menu, "menu_items": bot.menu_search_items(menu),
            "group_name": "Senior", "grade_ids": grades or [11],
            "start_time": "13:15", "end_time": "14:00", "requires_signin": 1, **extra}


def result(rows, kind="MEAL"):
    return {"type": kind, "day_name": "Friday", "meal_type": "LUNCH", "rows": rows}


@pytest.mark.parametrize("message", ["What's for lunch today?", "What are tomorrow's meals?"])
def test_menu_request_needs_no_model_and_omits_unasked_details(monkeypatch, message):
    def fail(*args, **kwargs):
        pytest.fail("A simple menu lookup must not call Gemini")
    monkeypatch.setattr(bot.client.models, "generate_content", fail)
    monkeypatch.setattr(bot, "fetch_meal", lambda *args: [row(), row(grades=[12], requires_signin=0)])
    monkeypatch.setattr(bot, "fetch_day_meals", lambda *args: [
        row("Breakfast", "Scrambled Eggs"), row(), row(grades=[12], requires_signin=0),
        row("Dinner", "Shepherd's Pie")])
    response = bot.app.test_client().post("/chat", json={"message": message})
    assert response.status_code == 200
    reply = response.get_json()["reply"]
    assert reply.count("[Fish Taco Bowl]") == 1
    assert "https://www.google.com/search?tbm=isch&q=Fish+Taco+Bowl" in reply
    for unasked in ("sign-in", "sign in", "13:15", "1:15", "Grade", "Senior", "serving"):
        assert unasked not in reply
    if "tomorrow" in message:
        assert "Breakfast" in reply and "Dinner" in reply


@pytest.mark.parametrize("focus,allowed,absent", [
    ("MENU", {"menu_items", "menu_content"}, {"start_time", "end_time", "requires_signin"}),
    ("TIMES", {"start_time", "end_time"}, {"menu_items", "menu_content", "requires_signin"}),
    ("MENU_AND_TIMES", {"menu_items", "start_time"}, {"requires_signin"}),
])
def test_meal_payload_contains_only_requested_details(focus, allowed, absent):
    original = result([row()])
    before = copy.deepcopy(original)
    actual = bot.focused_answer_results([{"meal_focus": focus}], [original])[0]
    assert allowed <= actual["rows"][0].keys()
    assert not absent.intersection(actual["rows"][0])
    assert original == before


def test_compound_menu_and_signin_keeps_each_answer_scoped(monkeypatch):
    captured = {}
    def generate(**kwargs):
        captured.update(json.loads(kwargs["contents"]))
        return SimpleNamespace(text="Dinner: fish. Grade 12: no sign-in required.")
    monkeypatch.setattr(bot.client.models, "generate_content", generate)
    cls = [{"intent": "MEAL", "meal_focus": "MENU"}, {"intent": "MEAL_SIGNIN", "grade": 12}]
    data = [result([row()]), result([row(grades=[12], requires_signin=0)], "MEAL_SIGNIN")]
    bot.generate_answer("What's for dinner and do grade 12s sign in?", cls, data)
    menu, signin = captured["results"]
    assert "requires_signin" not in menu["rows"][0]
    assert "start_time" not in menu["rows"][0]
    assert "menu_items" not in signin["rows"][0] and "menu_content" not in signin["rows"][0]
    assert signin["rows"][0]["requires_signin"] == 0


def test_time_question_still_uses_model_with_time_data(monkeypatch):
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(text=json.dumps({"requests": [{"intent": "MEAL", "day_ref": "TODAY",
                "meal_type": "LUNCH", "meal_focus": "TIMES"}]}))
        return SimpleNamespace(text="Lunch: 1:15–2:00 PM.")
    monkeypatch.setattr(bot.client.models, "generate_content", generate)
    monkeypatch.setattr(bot, "fetch_meal", lambda *args: [row()])
    response = bot.app.test_client().post("/chat", json={"message": "What time is lunch today?"})
    assert response.status_code == 200
    sent = json.loads(calls[1]["contents"])["results"][0]
    assert sent["meal_focus"] == "TIMES"
    assert sent["rows"][0]["start_time"] == "13:15"
    assert "menu_content" not in sent["rows"][0] and "requires_signin" not in sent["rows"][0]


def test_missing_and_different_group_menus_are_not_invented_or_merged():
    missing = bot.render_menu_answer([result([])])
    assert "don't have the lunch menu for Friday yet" in missing
    different = bot.render_menu_answer([result([row(menu="Fish", grades=[11]), row(menu=None, grades=[12])])])
    assert "Grade 11" in different and "Grade 12" in different
    assert "[Fish]" in different and "Menu unavailable" in different


def test_invalid_meal_focus_defaults_to_menu():
    assert bot.validate_request({"intent": "MEAL", "meal_focus": "EVERYTHING"})["meal_focus"] == "MENU"
