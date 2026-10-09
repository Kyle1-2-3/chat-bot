import types as pytypes
from datetime import datetime

import app as appmod


def test_chat_passes_memory_to_classifier(monkeypatch):
    captured = {}

    def fake_classify(user_msg, memory=""):
        captured["msg"] = user_msg
        captured["memory"] = memory
        return [{"intent": "MEAL", "day_ref": "TOMORROW", "meal_type": "LUNCH"}]

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
            text='{"requests":[{"intent":"MEAL","day_ref":"TOMORROW","meal_type":"LUNCH"}]}'
        )

    fake_client = pytypes.SimpleNamespace(
        models=pytypes.SimpleNamespace(generate_content=fake_generate))
    monkeypatch.setattr(appmod, "client", fake_client)

    appmod.classify_query("what about tomorrow", memory="Student: when is lunch\nAssistant: 1pm")
    assert "when is lunch" in seen["contents"]
    assert "what about tomorrow" in seen["contents"]


def test_classify_query_truncation_keeps_newest_turns(monkeypatch):
    seen = {}
    fake_client = pytypes.SimpleNamespace(models=pytypes.SimpleNamespace(
        generate_content=lambda **kw: seen.update(kw) or pytypes.SimpleNamespace(
            text='{"requests":[{"intent":"MEAL","day_ref":"TOMORROW","meal_type":"LUNCH"}]}')))
    monkeypatch.setattr(appmod, "client", fake_client)
    memory = "Student: old question\nAssistant: " + "x" * 1600 + "\nStudent: when is lunch\nAssistant: 1pm"
    appmod.classify_query("and tomorrow?", memory=memory)
    assert "when is lunch" in seen["contents"]  # the newest turn survives the cap
    assert "old question" not in seen["contents"]


def test_classify_query_works_without_memory(monkeypatch):
    fake_client = pytypes.SimpleNamespace(models=pytypes.SimpleNamespace(
        generate_content=lambda **kw: pytypes.SimpleNamespace(
            text='{"requests":[{"intent":"GREETING","day_ref":"ANY","meal_type":null}]}')))
    monkeypatch.setattr(appmod, "client", fake_client)
    out = appmod.classify_query("hi")  # no memory arg
    assert out[0]["intent"] == "GREETING"


def test_current_clock_is_in_system_instructions_on_each_turn(monkeypatch):
    calls = []
    monkeypatch.setattr(appmod.client.models, "generate_content", lambda **kwargs:
                        calls.append(kwargs) or pytypes.SimpleNamespace(text='{"intent":"GREETING"}'))
    for stamp in ["2026-10-08T23:59:00-07:00", "2026-10-09T00:01:00-07:00"]:
        clock = datetime.fromisoformat(stamp)
        monkeypatch.setattr(appmod, "current_school_time", lambda: clock)
        appmod.classify_query("What about tomorrow?", memory="Today is January 1.")
        appmod.generate_answer("And tomorrow?", [], [{"type": "GREETING"}])
        for call in calls[-2:]:
            prompt = call["config"].system_instruction
            assert clock.isoformat(timespec="minutes") in prompt
            assert "America/Vancouver" in prompt
            assert "Today is January 1" not in prompt
