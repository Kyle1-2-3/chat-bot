"""Answer feedback queue: student reports, automatic capture, admin review."""
import sqlite3

import pytest

import app as appmod
from feedback import FeedbackStore


@pytest.fixture
def store(monkeypatch, tmp_path):
    s = FeedbackStore(tmp_path / "feedback.sqlite3")
    monkeypatch.setattr(appmod, "feedback_store", s)
    return s


def rows(store):
    keys = ("question", "answer", "issue_type", "details", "source", "status", "request_id")
    return [tuple(r[k] for k in keys) for r in reversed(store.list("all"))]


def test_student_report_is_saved(store):
    response = appmod.app.test_client().post("/api/feedback", json={
        "question": "When is lunch?", "answer": "At noon.", "issue_type": "incorrect",
        "details": "It starts at 1:00.", "request_id": "abc123",
    })
    assert response.status_code == 201
    assert rows(store) == [("When is lunch?", "At noon.", "incorrect", "It starts at 1:00.",
                            "student", "open", "abc123")]


@pytest.mark.parametrize("body", [
    [], {"question": "", "issue_type": "incorrect"}, {"question": "x" * 501, "issue_type": "incorrect"},
    {"question": "q", "issue_type": "spam"}, {"question": "q", "issue_type": "other", "details": "d" * 1501},
    {"question": 5, "issue_type": "other"},
])
def test_invalid_reports_are_rejected(store, body):
    response = appmod.app.test_client().post("/api/feedback", json=body)
    assert response.status_code == 400
    assert rows(store) == []


def test_unknown_question_is_captured_automatically(store, monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda message, memory="": [dict(appmod.UNKNOWN_REQUEST)])
    response = appmod.app.test_client().post("/chat", json={"message": "Can I borrow a kayak?"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["request_id"]
    assert [(q, t, s) for q, _, t, _, s, _, _ in rows(store)] == [("Can I borrow a kayak?", "unanswered", "automatic")]
    assert rows(store)[0][6] == data["request_id"]


def test_capture_failure_never_breaks_the_reply(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda message, memory="": [dict(appmod.UNKNOWN_REQUEST)])
    def broken(**kw):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(appmod.feedback_store, "add", broken)
    response = appmod.app.test_client().post("/chat", json={"message": "Can I borrow a kayak?"})
    assert response.status_code == 200 and response.get_json()["reply"]


def test_answered_replies_carry_a_request_id(store, monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda message, memory="": [{"intent": "LOCATION", "day_ref": "ANY"}])
    data = appmod.app.test_client().post("/chat", json={"message": "where is the gym"}).get_json()
    assert data["reply"] == appmod.LOCATION_REPLY and len(data["request_id"]) == 8
    assert rows(store) == []


def test_stream_reply_carries_request_id(store, monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda message, memory="": [{"intent": "LOCATION", "day_ref": "ANY"}])
    body = appmod.app.test_client().post(
        "/chat", json={"message": "where is the gym"}, headers={"Accept": "text/event-stream"}
    ).get_data(as_text=True)
    assert '"request_id"' in body


def test_queue_requires_the_admin_token(store, monkeypatch):
    client = appmod.app.test_client()
    monkeypatch.delenv("FEEDBACK_ADMIN_TOKEN", raising=False)
    assert client.get("/api/feedback", headers={"X-Admin-Token": ""}).status_code == 401  # unset = closed
    monkeypatch.setenv("FEEDBACK_ADMIN_TOKEN", "test-secret")
    assert client.get("/api/feedback").status_code == 401
    assert client.get("/api/feedback", headers={"X-Admin-Token": "wrong"}).status_code == 401
    ok = client.get("/api/feedback", headers={"Authorization": "Bearer test-secret"})
    assert ok.status_code == 200 and ok.get_json() == {"feedback": []}


def test_admin_lists_filters_and_resolves(store, monkeypatch):
    monkeypatch.setenv("FEEDBACK_ADMIN_TOKEN", "test-secret")
    headers = {"X-Admin-Token": "test-secret"}
    client = appmod.app.test_client()
    first = store.add(question="One", issue_type="unclear", source="student")
    store.add(question="Two", issue_type="incorrect", source="student")

    listed = client.get("/api/feedback?status=open", headers=headers).get_json()["feedback"]
    assert [r["question"] for r in listed] == ["Two", "One"]

    patched = client.patch(f"/api/feedback/{first}", headers=headers,
                           json={"status": "resolved", "resolution_notes": "Added a new intent."})
    assert patched.status_code == 200
    assert [r["question"] for r in client.get("/api/feedback?status=open", headers=headers).get_json()["feedback"]] == ["Two"]
    resolved = client.get("/api/feedback?status=resolved", headers=headers).get_json()["feedback"]
    assert resolved[0]["resolution_notes"] == "Added a new intent."

    assert client.patch("/api/feedback/999", headers=headers, json={"status": "resolved"}).status_code == 404
    assert client.patch(f"/api/feedback/{first}", headers=headers, json={"status": "bogus"}).status_code == 400
    assert client.get("/api/feedback?status=bogus", headers=headers).status_code == 400


def test_store_lives_outside_the_reseeded_school_db():
    assert "school.db" not in str(appmod.feedback_store.path)
