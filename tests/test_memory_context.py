import types as pytypes

import app as appmod


def test_chat_passes_memory_to_classifier(monkeypatch):
    captured = {}

    def fake_classify(user_msg, memory=""):
        captured["msg"] = user_msg
        captured["memory"] = memory
        return [{"intent": "MEAL", "day_ref": "TOMORROW", "meal_type": "LUNCH", "confidence": 0.9}]

    monkeypatch.setattr(appmod, "classify_query", fake_classify)
    monkeypatch.setattr(appmod, "build_result_from_classification", lambda c, m: {"type": "MEAL"})
    monkeypatch.setattr(appmod, "generate_answer", lambda *a: "ok")

    appmod.app.test_client().post("/chat", json={
        "message": "what about tomorrow",
        "memory": "Student: when is lunch\nAssistant: Lunch is at 1pm.",
    })
    assert captured["msg"] == "what about tomorrow"
    assert "when is lunch" in captured["memory"]


def test_classify_query_includes_memory_in_prompt(monkeypatch):
    seen = {}

    def fake_generate(**kw):
        seen["contents"] = kw.get("contents", "")
        return pytypes.SimpleNamespace(
            text='{"requests":[{"intent":"MEAL","day_ref":"TOMORROW","meal_type":"LUNCH","confidence":0.9}]}'
        )

    fake_client = pytypes.SimpleNamespace(
        models=pytypes.SimpleNamespace(generate_content=fake_generate))
    monkeypatch.setattr(appmod, "client", fake_client)

    appmod.classify_query("what about tomorrow", memory="Student: when is lunch\nAssistant: 1pm")
    assert "when is lunch" in seen["contents"]
    assert "what about tomorrow" in seen["contents"]


def test_classify_query_works_without_memory(monkeypatch):
    fake_client = pytypes.SimpleNamespace(models=pytypes.SimpleNamespace(
        generate_content=lambda **kw: pytypes.SimpleNamespace(
            text='{"requests":[{"intent":"GREETING","day_ref":"ANY","meal_type":null,"confidence":0.9}]}')))
    monkeypatch.setattr(appmod, "client", fake_client)
    out = appmod.classify_query("hi")  # no memory arg
    assert out[0]["intent"] == "GREETING"
