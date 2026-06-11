import pytest

import app as appmod


@pytest.fixture
def rate_limited(monkeypatch):
    """Enable the limiter with a clean slate (conftest disables it for other tests)."""
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        dict(appmod.UNKNOWN_REQUEST),
    ])
    appmod.limiter.reset()
    appmod.limiter.enabled = True
    yield
    appmod.limiter.enabled = False


def test_chat_returns_429_after_limit(rate_limited):
    client = appmod.app.test_client()
    for _ in range(10):
        resp = client.post("/chat", json={"message": "hi"})
        assert resp.status_code == 200
    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 429
    assert "reply" in resp.get_json()  # frontend always reads .reply


def test_separate_ips_get_separate_buckets(rate_limited):
    client = appmod.app.test_client()
    for _ in range(11):
        client.post("/chat", json={"message": "hi"})
    resp = client.post(
        "/chat", json={"message": "hi"},
        environ_overrides={"REMOTE_ADDR": "10.0.0.9"},
    )
    assert resp.status_code == 200


def test_client_ip_uses_last_forwarded_for_entry():
    # nginx appends the real client IP last; the first entry is client-supplied
    # and spoofable, so the key must come from the end of the list.
    with appmod.app.test_request_context(
        headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
    ):
        assert appmod.client_ip() == "5.6.7.8"


def test_client_ip_falls_back_to_remote_addr():
    with appmod.app.test_request_context(environ_overrides={"REMOTE_ADDR": "9.9.9.9"}):
        assert appmod.client_ip() == "9.9.9.9"
