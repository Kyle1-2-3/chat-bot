from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from types import SimpleNamespace

import pytest

import app as bot
from usage_limits import UsageStore, DailyBudgetReached, UsageUnavailable

REAL_CLASSIFY = bot.classify_query


def test_store_is_atomic_across_connections_and_survives_restart(tmp_path):
    path = tmp_path / "usage.sqlite3"
    first = UsageStore(path)
    key = first.signing_key()
    assert UsageStore(path).signing_key() == key
    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(
            lambda _: UsageStore(path).reserve([("gemini", 10, 200)], 100), range(32)))
    assert outcomes.count(0) == 10
    assert outcomes.count(100) == 22
    assert UsageStore(path).reserve([("gemini", 10, 200)], 101) == 99
    assert UsageStore(path).reserve([("gemini", 10, 300)], 200) == 0


def test_rejected_group_does_not_spend_other_bucket(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite3")
    assert store.reserve([("ip", 1, 200)], 100) == 0
    assert store.reserve([("browser", 1, 200), ("ip", 1, 200)], 100) == 100
    assert store.reserve([("browser", 1, 200)], 100) == 0


@pytest.fixture
def metered(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "usage_store", UsageStore(tmp_path / "usage.sqlite3"))
    monkeypatch.setattr(bot, "usage_window", lambda: (100, 200))
    monkeypatch.setitem(bot.app.config, "USAGE_LIMITS_ENABLED", True)
    monkeypatch.setitem(bot.app.config, "USER_DAILY_LIMIT", 2)
    monkeypatch.setitem(bot.app.config, "IP_DAILY_LIMIT", 4)
    monkeypatch.setitem(bot.app.config, "GEMINI_DAILY_CALL_LIMIT", 2)
    monkeypatch.setattr(bot, "classify_query", lambda *args: [dict(bot.UNKNOWN_REQUEST)])
    return bot.app.test_client()


def post(client, **kwargs):
    return client.post("/chat", json={"message": "hi"}, **kwargs)


def test_cookie_limit_survives_reconnect_ip_change_and_worker_restart(metered, monkeypatch):
    response = post(metered, headers={"X-Forwarded-Proto": "https"})
    cookie = response.headers["Set-Cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "SameSite=Lax", "Secure"))
    post(metered)
    second = bot.app.test_client()
    second.set_cookie(bot.USAGE_COOKIE, metered.get_cookie(bot.USAGE_COOKIE).value)
    monkeypatch.setattr(bot, "usage_store", UsageStore(bot.usage_store.path))
    response = post(second, environ_overrides={"REMOTE_ADDR": "10.0.0.8"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "100"


def test_new_or_tampered_cookie_cannot_evade_ip_daily_cap(metered):
    post(metered)
    post(metered)
    second = bot.app.test_client()
    second.set_cookie(bot.USAGE_COOKIE, "forged")
    assert post(second).status_code == 200
    assert post(second).status_code == 200
    assert post(bot.app.test_client()).status_code == 429


def test_day_rollover_resets_browser_and_ip_limits(metered, monkeypatch):
    post(metered)
    post(metered)
    assert post(metered).status_code == 429
    monkeypatch.setattr(bot, "usage_window", lambda: (200, 300))
    assert post(metered).status_code == 200


def test_every_model_attempt_including_failures_spends_shared_cap(metered, monkeypatch):
    calls = []

    def failing(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("upstream failed")

    monkeypatch.setattr(bot.client.models, "generate_content", failing)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            bot.call_model(contents="hi")
    monkeypatch.setattr(bot, "usage_store", UsageStore(bot.usage_store.path))
    with pytest.raises(DailyBudgetReached):
        bot.call_model(contents="hi")
    assert len(calls) == 2


@pytest.mark.parametrize("streaming", [False, True])
def test_cap_between_classifier_and_answer_is_explained(metered, monkeypatch, streaming):
    # Use the real classifier and answer path. A one-call budget pays for the
    # classifier, then prevents the second call before it reaches the SDK.
    monkeypatch.setattr(bot, "classify_query", REAL_CLASSIFY)
    monkeypatch.setitem(bot.app.config, "GEMINI_DAILY_CALL_LIMIT", 1)
    calls = []
    monkeypatch.setattr(bot.client.models, "generate_content", lambda **kwargs:
                        calls.append(kwargs) or SimpleNamespace(text=json.dumps(
                            {"requests": [{"intent": "SCHOOL_INFO", "school_query": "Ken Snow"}]})))
    response = metered.post("/chat", json={"message": "Who is Mr Snow?"},
                            headers={"Accept": "text/event-stream"} if streaming else {})
    if streaming:
        assert "event: error" in response.get_data(as_text=True)
        assert json.dumps(bot.BUDGET_REPLY) in response.get_data(as_text=True)
    else:
        assert response.status_code == 429
        assert response.get_json()["reply"] == bot.BUDGET_REPLY
    assert len(calls) == 1


def test_direct_menu_keeps_working_after_global_cap(metered, monkeypatch):
    bot.usage_store.reserve([("gemini", 2, 200)], 100)
    bot.usage_store.reserve([("gemini", 2, 200)], 100)
    monkeypatch.setattr(bot, "classify_query", REAL_CLASSIFY)
    monkeypatch.setattr(bot, "build_result_from_classification", lambda *args: {
        "type": "MEAL", "meal_type": "LUNCH", "day_name": "Thursday", "rows": [
            {"type_name": "Lunch", "menu_content": "Noodles"}]})
    def unexpected(**kwargs):
        raise AssertionError("Direct menu must not call the model")
    monkeypatch.setattr(bot.client.models, "generate_content", unexpected)
    response = metered.post("/chat", json={"message": "What's for lunch today?"})
    assert response.status_code == 200
    assert "Noodles" in response.get_json()["reply"]


def test_dev_path_is_metered_too(metered, monkeypatch):
    monkeypatch.setattr(bot, "DEV_TRIGGER", "/test-dev")
    monkeypatch.setattr(bot.client.models, "generate_content", lambda **kwargs: SimpleNamespace(text="Hello"))
    response = metered.post("/chat", json={"message": "/test-dev hello"})
    assert response.get_json()["reply"] == "Hello"
    with sqlite3.connect(bot.usage_store.path) as conn:
        assert conn.execute("SELECT used FROM counters WHERE bucket='gemini'").fetchone()[0] == 1


def test_counter_failure_never_makes_unmetered_calls(metered, monkeypatch):
    def unavailable(*args):
        raise sqlite3.OperationalError("private database detail")
    monkeypatch.setattr(bot.usage_store, "reserve", unavailable)
    with pytest.raises(UsageUnavailable):
        bot.call_model(contents="hi")
    response = post(metered)
    assert response.status_code == 503
    assert "private database detail" not in response.get_data(as_text=True)


def test_zero_global_cap_explicitly_disables_it(metered, monkeypatch):
    monkeypatch.setitem(bot.app.config, "GEMINI_DAILY_CALL_LIMIT", 0)
    monkeypatch.setattr(bot.client.models, "generate_content", lambda **kwargs: "ok")
    assert bot.call_model(contents="hi") == "ok"
