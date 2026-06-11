import app as appmod


def test_validate_keeps_location_intent():
    out = appmod.validate_request({"intent": "LOCATION"})
    assert out["intent"] == "LOCATION"


def test_build_result_location():
    res = appmod.build_result_from_classification(
        {"intent": "LOCATION"},
        "where is crooks hall",
    )
    assert res["type"] == "LOCATION"


def test_chat_location_skips_answer_llm(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "LOCATION", "day_ref": "ANY", "meal_type": None},
    ])

    def boom(*args, **kwargs):
        raise AssertionError("generate_answer must not be called for pure LOCATION")

    monkeypatch.setattr(appmod, "generate_answer", boom)

    resp = appmod.app.test_client().post(
        "/chat", json={"message": "where is crooks hall"})
    assert resp.status_code == 200
    assert "campus map" in resp.get_json()["reply"]


def test_chat_mixed_location_meal_uses_answer_llm(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "LOCATION", "day_ref": "ANY", "meal_type": None},
        {"intent": "MEAL", "day_ref": "FRIDAY", "meal_type": "LUNCH"},
    ])
    captured = {}

    def fake_answer(msg, cls, results):
        captured["results"] = results
        return "ok"

    monkeypatch.setattr(appmod, "generate_answer", fake_answer)

    resp = appmod.app.test_client().post(
        "/chat", json={"message": "where is the gym and lunch friday?"})
    assert resp.status_code == 200
    assert "ok" in resp.get_json()["reply"]
    types = [r["type"] for r in captured["results"]]
    assert types == ["LOCATION", "MEAL"]
