from datetime import date

import app as appmod


def test_validate_keeps_location_intent():
    out = appmod.validate_request({"intent": "LOCATION"})
    assert out["intent"] == "LOCATION"


def test_build_result_location(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 6, 10))
    res = appmod.build_result_from_classification(
        {"intent": "LOCATION", "day_ref": "ANY", "meal_type": None},
        "where is crooks hall",
    )
    assert res["type"] == "LOCATION"


def test_chat_location_path(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 6, 10))
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "LOCATION", "day_ref": "ANY", "meal_type": None},
    ])
    captured = {}
    monkeypatch.setattr(appmod, "generate_answer",
                        lambda msg, cls, results: captured.setdefault("results", results) or "ok")

    appmod.app.test_client().post("/chat", json={"message": "where is crooks hall"})
    assert captured["results"][0]["type"] == "LOCATION"
