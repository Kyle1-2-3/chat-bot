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


def test_chat_location_path(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "LOCATION", "day_ref": "ANY", "meal_type": None},
    ])
    captured = {}

    def fake_answer(msg, cls, results):
        captured["results"] = results
        return "ok"

    monkeypatch.setattr(appmod, "generate_answer", fake_answer)

    resp = appmod.app.test_client().post(
        "/chat", json={"message": "where is crooks hall"})
    assert resp.status_code == 200
    assert "ok" in resp.get_json()["reply"]
    assert captured["results"][0]["type"] == "LOCATION"
