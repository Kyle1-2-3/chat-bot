"""Regression tests for the 2026-10 optimization pass."""
from types import SimpleNamespace

import pytest

import app as appmod


def _capture(monkeypatch, text='{"requests":[{"intent":"GREETING","day_ref":"ANY"}]}'):
    calls = []

    def fake(**kw):
        calls.append(kw)
        return SimpleNamespace(text=text)

    monkeypatch.setattr(appmod.client.models, "generate_content", fake)
    return calls


@pytest.mark.parametrize("msg,day_ref", [
    ("What time is sign-in tonight?", "TODAY"),
    ("sign in time saturday", "SATURDAY"),
    ("when is signin tomorrow", "TOMORROW"),
])
def test_signin_card_skips_the_classifier(monkeypatch, msg, day_ref):
    calls = _capture(monkeypatch)
    out = appmod.classify_query(msg)
    assert calls == []
    assert out[0]["intent"] == "SIGNIN_SUMMARY" and out[0]["day_ref"] == day_ref


@pytest.mark.parametrize("msg", ["how do I sign up for rugby", "grade 12 sign in saturday", "sign"])
def test_other_sign_phrases_still_use_the_classifier(msg):
    assert appmod.quick_classify(msg) is None


def test_grade_in_memory_sends_signin_question_to_classifier(monkeypatch):
    calls = _capture(monkeypatch, '{"requests":[{"intent":"SIGNIN_SUMMARY","day_ref":"TODAY","grade":12}]}')
    out = appmod.classify_query("What time is sign-in tonight?", memory="Student: I'm in grade 12")
    assert len(calls) == 1 and out[0]["grade"] == 12


def test_both_gemini_calls_disable_thinking(monkeypatch):
    calls = _capture(monkeypatch)
    appmod.classify_query("hello there friend, how are you doing")
    appmod.generate_answer("hello", [{"intent": "GREETING"}], [{"type": "GREETING"}])
    assert [c["config"].thinking_config.thinking_budget for c in calls] == [0, 0]


def test_gemini_failure_returns_none_and_fallbacks(monkeypatch):
    def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr(appmod.client.models, "generate_content", boom)
    assert appmod.gemini_text("x", model="m", contents="c") is None
    assert appmod.classify_query("is there anything happening later at school") == [dict(appmod.UNKNOWN_REQUEST)]
    assert appmod.generate_answer("hi", [], [{"type": "GREETING"}]) == appmod.LLM_FAILURE_REPLY


def test_school_info_payload_drops_retrieval_fields():
    record = {"title": "Rogers House", "facts": ["f"], "source_url": "u", "keywords": ["k"],
              "id": "r1", "category": "staff", "checked_on": "2026-09-23"}
    out = appmod.focused_answer_results([{"intent": "SCHOOL_INFO"}],
                                        [{"type": "SCHOOL_INFO", "records": [record]}])[0]
    assert out["checked_on"] == "2026-09-23"
    assert out["records"] == [{"title": "Rogers House", "facts": ["f"], "source_url": "u"}]


def test_md_escape_matches_previous_rule():
    assert appmod.md_escape("a_b [c] *d* `e` <f> \\") == r"a\_b \[c\] \*d\* \`e\` \<f\> \\"
