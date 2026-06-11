import logging

import app as appmod


def _post(monkeypatch, caplog, intents, message="hello"):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {**appmod.UNKNOWN_REQUEST, "intent": i} for i in intents
    ])
    monkeypatch.setattr(appmod, "generate_answer", lambda *a, **k: "ok")
    monkeypatch.setattr(appmod, "build_result_from_classification",
                        lambda c, m: {"type": c["intent"]})
    with caplog.at_level(logging.INFO, logger="chatbot"):
        appmod.app.test_client().post("/chat", json={"message": message})
    return caplog.records


def test_intents_logged_at_info(monkeypatch, caplog):
    records = _post(monkeypatch, caplog, ["SCHEDULE", "MEAL"])
    assert any("intents" in r.message and "SCHEDULE,MEAL" in r.message
               for r in records)


def test_unknown_logs_the_question(monkeypatch, caplog):
    records = _post(monkeypatch, caplog, ["UNKNOWN"], message="how do laundry work")
    assert any("UNKNOWN" in r.message and "how do laundry work" in r.message
               for r in records)
