import json
import types as pytypes
from datetime import date

import app as appmod


def patch_llm(monkeypatch, payload: dict):
    """Replace the Gemini client with a fake returning the given JSON payload."""
    fake_response = pytypes.SimpleNamespace(text=json.dumps(payload))
    fake_client = pytypes.SimpleNamespace(
        models=pytypes.SimpleNamespace(generate_content=lambda **kw: fake_response)
    )
    monkeypatch.setattr(appmod, "client", fake_client)


# ---------------------------
# resolve_day_id: DAY_AFTER_TOMORROW
# ---------------------------
def test_day_after_tomorrow_midweek(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 22))  # Wednesday
    assert appmod.resolve_day_id("DAY_AFTER_TOMORROW") == 5  # Friday


def test_day_after_tomorrow_wraps_week(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 25))  # Saturday
    assert appmod.resolve_day_id("DAY_AFTER_TOMORROW") == 1  # Monday


# ---------------------------
# classify_query returns a list of requests
# ---------------------------
def test_classify_query_returns_multiple_requests(monkeypatch):
    patch_llm(monkeypatch, {
        "requests": [
            {"intent": "SCHEDULE", "day_ref": "TOMORROW", "meal_type": None},
            {"intent": "MEAL", "day_ref": "DAY_AFTER_TOMORROW", "meal_type": "BREAKFAST"},
        ]
    })
    out = appmod.classify_query("what is the block order tmr and breakfast the day after tmr")
    assert [r["intent"] for r in out] == ["SCHEDULE", "MEAL"]
    assert out[1]["day_ref"] == "DAY_AFTER_TOMORROW"
    assert out[1]["meal_type"] == "BREAKFAST"


def test_classify_query_accepts_bare_json_array(monkeypatch):
    patch_llm(monkeypatch, [
        {"intent": "SCHEDULE", "day_ref": "TOMORROW", "meal_type": None},
        {"intent": "MEAL", "day_ref": "DAY_AFTER_TOMORROW", "meal_type": "BREAKFAST"},
    ])
    out = appmod.classify_query("block order tmr and breakfast the day after tmr")
    assert [r["intent"] for r in out] == ["SCHEDULE", "MEAL"]


def test_classify_query_validates_each_request(monkeypatch):
    patch_llm(monkeypatch, {
        "requests": [
            {"intent": "BOGUS", "day_ref": "SOMEDAY", "meal_type": "PIZZA"},
        ]
    })
    out = appmod.classify_query("hi")
    assert out == [{"intent": "UNKNOWN", "day_ref": "ANY", "meal_type": None, "grade": None, "event_name": None}]


def test_classify_query_preserves_four_intents(monkeypatch):
    # Real failing case: "lunch today and dinner tmr and block order today and house sign-in"
    patch_llm(monkeypatch, {
        "requests": [
            {"intent": "MEAL", "day_ref": "TODAY", "meal_type": "LUNCH"},
            {"intent": "MEAL", "day_ref": "TOMORROW", "meal_type": "DINNER"},
            {"intent": "SCHEDULE", "day_ref": "TODAY", "meal_type": None},
            {"intent": "SIGNIN_SUMMARY", "day_ref": "TODAY", "meal_type": None},
        ]
    })
    out = appmod.classify_query("lunch today and dinner tmr and blocks today and house sign in")
    assert [r["intent"] for r in out] == ["MEAL", "MEAL", "SCHEDULE", "SIGNIN_SUMMARY"]


def test_classify_query_caps_requests_at_max(monkeypatch):
    patch_llm(monkeypatch, {
        "requests": [
            {"intent": "MEAL", "day_ref": "MONDAY", "meal_type": "LUNCH"}
        ] * 8
    })
    out = appmod.classify_query("lunch x8")
    assert len(out) == appmod.MAX_REQUESTS == 5


def test_classify_query_empty_message():
    out = appmod.classify_query("")
    assert out == [{"intent": "UNKNOWN", "day_ref": "ANY", "meal_type": None, "grade": None, "event_name": None}]


# ---------------------------
# /chat orchestration
# ---------------------------
def test_chat_answers_compound_question(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "SCHEDULE", "day_ref": "THURSDAY", "meal_type": None},
        {"intent": "MEAL", "day_ref": "FRIDAY", "meal_type": "BREAKFAST"},
    ])
    captured = {}

    def fake_generate(user_msg, classifications, results):
        captured["results"] = results
        return "combined answer"

    monkeypatch.setattr(appmod, "generate_answer", fake_generate)

    resp = appmod.app.test_client().post("/chat", json={"message": "block order thu and breakfast fri"})
    assert resp.get_json()["reply"] == "combined answer"
    assert [r["type"] for r in captured["results"]] == ["SCHEDULE", "MEAL"]
    assert captured["results"][0]["day_name"] == "Thursday"
    assert captured["results"][1]["day_name"] == "Friday"


def test_chat_drops_unknown_when_other_intents_present(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "UNKNOWN", "day_ref": "ANY", "meal_type": None, "grade": None},
        {"intent": "SCHEDULE", "day_ref": "MONDAY", "meal_type": None},
    ])
    captured = {}

    def fake_generate(user_msg, classifications, results):
        captured["results"] = results
        return "ok"

    monkeypatch.setattr(appmod, "generate_answer", fake_generate)

    appmod.app.test_client().post("/chat", json={"message": "??? and schedule monday"})
    assert [r["type"] for r in captured["results"]] == ["SCHEDULE"]


def test_chat_all_unknown_falls_back(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "UNKNOWN", "day_ref": "ANY", "meal_type": None, "grade": None},
    ])
    resp = appmod.app.test_client().post("/chat", json={"message": "asdf"})
    assert "not fully sure" in resp.get_json()["reply"]


def test_chat_greeting_only_still_greets(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "GREETING", "day_ref": "ANY", "meal_type": None},
    ])
    captured = {}

    def fake_generate(user_msg, classifications, results):
        captured["results"] = results
        return "hello!"

    monkeypatch.setattr(appmod, "generate_answer", fake_generate)

    resp = appmod.app.test_client().post("/chat", json={"message": "hi"})
    assert resp.get_json()["reply"] == "hello!"
    assert captured["results"] == [{"type": "GREETING"}]
