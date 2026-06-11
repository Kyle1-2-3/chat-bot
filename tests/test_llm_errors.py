import logging
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

import app as appmod


def _patch_llm(monkeypatch, effect):
    def fake_generate_content(**kwargs):
        if isinstance(effect, Exception):
            raise effect
        return SimpleNamespace(text=effect)
    monkeypatch.setattr(appmod.client.models, "generate_content",
                        lambda *a, **k: fake_generate_content(**k))


# ---------------------------
# classify_query
# ---------------------------
def test_classify_bad_json_logs_raw_text(monkeypatch, caplog):
    _patch_llm(monkeypatch, "sure! here are the meals you asked for")
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        out = appmod.classify_query("lunch today")
    assert out == [appmod.UNKNOWN_REQUEST]
    assert any("unparseable" in r.message and "sure!" in r.message
               for r in caplog.records)


def test_classify_api_error_logs_status(monkeypatch, caplog):
    _patch_llm(monkeypatch, errors.APIError(429, {"error": {"message": "quota exceeded"}}))
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        out = appmod.classify_query("lunch today")
    assert out == [appmod.UNKNOWN_REQUEST]
    assert any("API error" in r.message and "429" in r.message for r in caplog.records)


def test_classify_timeout_logged_as_timeout(monkeypatch, caplog):
    _patch_llm(monkeypatch, httpx.ReadTimeout("timed out"))
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        out = appmod.classify_query("lunch today")
    assert out == [appmod.UNKNOWN_REQUEST]
    assert any("timed out" in r.message for r in caplog.records)


def test_classify_unexpected_error_still_falls_back(monkeypatch, caplog):
    _patch_llm(monkeypatch, RuntimeError("boom"))
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        out = appmod.classify_query("lunch today")
    assert out == [appmod.UNKNOWN_REQUEST]


# ---------------------------
# generate_answer
# ---------------------------
def test_answer_api_error_logs_status_and_apologizes(monkeypatch, caplog):
    _patch_llm(monkeypatch, errors.APIError(503, {"error": {"message": "overloaded"}}))
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        reply = appmod.generate_answer("hi", [], [])
    assert "Sorry" in reply
    assert any("API error" in r.message and "503" in r.message for r in caplog.records)


def test_answer_timeout_logged_as_timeout(monkeypatch, caplog):
    _patch_llm(monkeypatch, httpx.ReadTimeout("timed out"))
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        reply = appmod.generate_answer("hi", [], [])
    assert "Sorry" in reply
    assert any("timed out" in r.message for r in caplog.records)
