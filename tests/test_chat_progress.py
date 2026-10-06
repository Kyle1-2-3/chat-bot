import json

import app as appmod

STREAM_HEADERS = {"Accept": "text/event-stream"}


def decode(chunk):
    lines = chunk.decode().strip().splitlines()
    return lines[0].split(": ", 1)[1], json.loads(lines[1].split(": ", 1)[1])


def test_progress_is_sent_before_each_real_stage(monkeypatch):
    calls = []

    def classify(*args):
        calls.append("classify")
        return [{"intent": "MEAL"}]

    def build(*args):
        calls.append("build")
        return {"type": "MEAL"}

    def answer(*args):
        calls.append("answer")
        return "점심 메뉴입니다.\nEnjoy!"

    monkeypatch.setattr(appmod, "classify_query", classify)
    monkeypatch.setattr(appmod, "build_result_from_classification", build)
    monkeypatch.setattr(appmod, "generate_answer", answer)
    response = appmod.app.test_client().post(
        "/chat", json={"message": "lunch"}, headers=STREAM_HEADERS, buffered=False)
    events = iter(response.response)
    assert decode(next(events)) == ("status", {"stage": "understanding"})
    assert calls == []
    assert decode(next(events)) == ("status", {"stage": "checking"})
    assert calls == ["classify"]
    assert decode(next(events)) == ("status", {"stage": "writing"})
    assert calls == ["classify", "build"]
    assert decode(next(events)) == ("reply", {"reply": "점심 메뉴입니다.\nEnjoy!"})
    assert calls == ["classify", "build", "answer"]
    assert list(events) == []
    assert response.mimetype == "text/event-stream"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert "no-transform" in response.headers["Cache-Control"]
    response.close()


def test_greeting_does_not_claim_to_search(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda *a: [{"intent": "GREETING"}])
    monkeypatch.setattr(appmod, "generate_answer", lambda *a: "Hi!")
    response = appmod.app.test_client().post("/chat", json={"message": "hi"}, headers=STREAM_HEADERS)
    events = [decode(chunk) for chunk in response.response]
    assert events == [("status", {"stage": "understanding"}),
                      ("status", {"stage": "writing"}), ("reply", {"reply": "Hi!"})]


def test_stream_and_json_use_identical_answer_pipeline(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda *a: [{"intent": "PERSONAL_ACTIVITY"}])
    client = appmod.app.test_client()
    ordinary = client.post("/chat", json={"message": "my art"})
    streamed = client.post("/chat", json={"message": "my art"}, headers=STREAM_HEADERS)
    event, payload = [decode(chunk) for chunk in streamed.response][-1]
    assert event == "reply"
    assert payload == ordinary.get_json() == {"reply": appmod.PERSONAL_ACTIVITY_REPLY}


def test_data_failure_terminates_with_error_event(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda *a: [{"intent": "MEAL"}])

    def fail(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(appmod, "build_result_from_classification", fail)
    client = appmod.app.test_client()
    response = client.post("/chat", json={"message": "lunch"}, headers=STREAM_HEADERS)
    events = [decode(chunk) for chunk in response.response]
    assert events[-1][0] == "error"
    assert not any(event == "reply" for event, _ in events)
    assert client.post("/chat", json={"message": "lunch"}).status_code == 500


def test_unexpected_stream_failure_is_reported_without_exception_details(monkeypatch):
    def fail(*args):
        raise RuntimeError("private diagnostic detail")

    monkeypatch.setattr(appmod, "classify_query", fail)
    response = appmod.app.test_client().post("/chat", json={"message": "hi"}, headers=STREAM_HEADERS)
    content = response.get_data(as_text=True)
    assert "event: error" in content
    assert "private diagnostic detail" not in content


def test_stream_still_enforces_message_limit():
    response = appmod.app.test_client().post("/chat", json={"message": "x" * 501}, headers=STREAM_HEADERS)
    assert response.status_code == 400
    assert response.is_json
