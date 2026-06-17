from types import SimpleNamespace

import app as appmod

TRIGGER = "/천마리의새가우는소리"


def _capture_llm(monkeypatch, reply="raw gemini reply"):
    calls = []

    def fake(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=reply)

    monkeypatch.setattr(appmod.client.models, "generate_content", fake)
    return calls


def test_trigger_bypasses_pipeline(monkeypatch):
    calls = _capture_llm(monkeypatch)

    def boom(*a, **k):
        raise AssertionError("classifier must not run for dev-trigger messages")

    monkeypatch.setattr(appmod, "classify_query", boom)

    resp = appmod.app.test_client().post(
        "/chat", json={"message": f"{TRIGGER} what model are you?"})
    assert resp.status_code == 200
    assert resp.get_json()["reply"] == "raw gemini reply"
    assert len(calls) == 1  # one direct call, no classify + answer pair


def test_trigger_phrase_stripped_and_no_school_system_prompt(monkeypatch):
    calls = _capture_llm(monkeypatch)
    appmod.app.test_client().post(
        "/chat", json={"message": f"{TRIGGER} tell me a joke"})
    kw = calls[0]
    cfg = kw.get("config")
    assert cfg is None or getattr(cfg, "system_instruction", None) is None
    assert TRIGGER not in kw["contents"]
    assert "tell me a joke" in kw["contents"]


def test_trigger_passes_memory_context(monkeypatch):
    calls = _capture_llm(monkeypatch)
    appmod.app.test_client().post(
        "/chat", json={"message": f"{TRIGGER} and then?", "memory": "User: hi\nBot: hello"})
    assert "User: hi" in calls[0]["contents"]


def test_trigger_answers_in_korean(monkeypatch):
    calls = _capture_llm(monkeypatch)
    appmod.app.test_client().post(
        "/chat", json={"message": f"{TRIGGER} say hi"})
    assert "Korean only" in calls[0]["contents"]


def test_trigger_keeps_deep_memory(monkeypatch):
    calls = _capture_llm(monkeypatch)
    # ~10 Q&A pairs; well past the 1500-char pipeline cap but within RAW_MEMORY_CHARS.
    memory = "\n".join(f"Student: q{i}\nAssistant: a{i} {'x' * 200}" for i in range(10))
    appmod.app.test_client().post(
        "/chat", json={"message": f"{TRIGGER} continue", "memory": memory})
    contents = calls[0]["contents"]
    assert "q0" in contents and "q9" in contents  # oldest and newest both survive


def test_normal_messages_still_use_pipeline(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "GREETING", "day_ref": "ANY", "meal_type": None},
    ])
    monkeypatch.setattr(appmod, "generate_answer", lambda *a, **k: "school bot reply")
    resp = appmod.app.test_client().post("/chat", json={"message": "hello"})
    assert resp.get_json()["reply"] == "school bot reply"
