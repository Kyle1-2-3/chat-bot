"""Natural-language routing for the home-page prompts.

The quick-action cards / chips send fixed phrasings. These must resolve to the
same SCHEDULE / MEAL / MEALS_DAY handlers as the older shorthand ("block order
tmr", "meal tmr") without needing the Gemini classifier.
"""
import sqlite3

import pytest

import app as appmod


@pytest.fixture
def no_llm(monkeypatch):
    """Fail loudly if anything reaches Gemini — the fast path must handle it."""
    def boom(*a, **k):
        raise AssertionError("Gemini classifier must not be called for this prompt")
    monkeypatch.setattr(appmod.client.models, "generate_content", boom)


# ---------------------------
# Block order -> SCHEDULE
# ---------------------------
@pytest.mark.parametrize("msg,day_ref", [
    ("What’s the block order today?", "TODAY"),
    ("What is the block order today?", "TODAY"),
    ("What’s the block order tomorrow?", "TOMORROW"),
    ("What is the block order tomorrow?", "TOMORROW"),
    ("block order today", "TODAY"),
    ("block order tomorrow", "TOMORROW"),
    ("block order tmr", "TOMORROW"),
    ("whats the block order tmr", "TOMORROW"),
    ("what blocks do we have today?", "TODAY"),
    ("what blocks do we have tomorrow?", "TOMORROW"),
    ("what blocks are tomorrow?", "TOMORROW"),
    ("what’s happening with blocks today?", "TODAY"),
    ("what’s the school schedule today?", "TODAY"),
    ("block order", "ANY"),            # no day -> existing default (ANY = today)
    ("block order friday", "FRIDAY"),
])
def test_block_order_prompts_route_to_schedule(no_llm, msg, day_ref):
    out = appmod.classify_query(msg)
    assert len(out) == 1
    assert out[0]["intent"] == "SCHEDULE"
    assert out[0]["day_ref"] == day_ref
    assert out[0]["meal_type"] is None and out[0]["grade"] is None


# ---------------------------
# Dining -> MEAL / MEALS_DAY
# ---------------------------
@pytest.mark.parametrize("msg,intent,meal_type,day_ref", [
    ("What’s for lunch today?", "MEAL", "LUNCH", "TODAY"),
    ("What’s for lunch tomorrow?", "MEAL", "LUNCH", "TOMORROW"),
    ("What’s for dinner today?", "MEAL", "DINNER", "TODAY"),
    ("What’s for dinner tomorrow?", "MEAL", "DINNER", "TOMORROW"),
    ("What’s for breakfast today?", "MEAL", "BREAKFAST", "TODAY"),
    ("What’s for breakfast tomorrow?", "MEAL", "BREAKFAST", "TOMORROW"),
    ("What are the meals today?", "MEALS_DAY", None, "TODAY"),
    ("What are the meals tomorrow?", "MEALS_DAY", None, "TOMORROW"),
    ("meal today", "MEALS_DAY", None, "TODAY"),
    ("meal tomorrow", "MEALS_DAY", None, "TOMORROW"),
    ("meal tmr", "MEALS_DAY", None, "TOMORROW"),
    ("lunch today", "MEAL", "LUNCH", "TODAY"),
    ("lunch tomorrow", "MEAL", "LUNCH", "TOMORROW"),
    ("dinner tmr", "MEAL", "DINNER", "TOMORROW"),
    ("breakfast tomorrow", "MEAL", "BREAKFAST", "TOMORROW"),
    ("what are we eating today?", "MEALS_DAY", None, "TODAY"),
    ("what are we eating tomorrow?", "MEALS_DAY", None, "TOMORROW"),
    ("What's for lunch?", "MEAL", "LUNCH", "ANY"),
    ("food", "MEALS_DAY", None, "ANY"),
])
def test_meal_prompts_route_to_meal_handlers(no_llm, msg, intent, meal_type, day_ref):
    out = appmod.classify_query(msg)
    assert len(out) == 1
    assert out[0]["intent"] == intent
    assert out[0]["meal_type"] == meal_type
    assert out[0]["day_ref"] == day_ref


# ---------------------------
# Everything else still goes to the Gemini classifier
# ---------------------------
@pytest.mark.parametrize("msg", [
    "lunch today and dinner tmr",             # compound -> LLM splits it
    "I'm gr12, do I sign in for dinner?",     # grade / sign-in
    "what about tomorrow",                    # follow-up needs memory
    "when is lunch today",                    # time question, not a menu
    "내일 점심 뭐야",                            # Korean
    "who is my math teacher",
    "afternoon schedule monday",
    "meal schedule",
    "lunch x8",
    "block order today and tomorrow",
])
def test_other_prompts_fall_through_to_llm(monkeypatch, msg):
    assert appmod.quick_classify(msg) is None
    calls = []
    def fake(*a, **k):
        calls.append(k)
        class R: text = '{"requests":[{"intent":"UNKNOWN","day_ref":"ANY"}]}'
        return R()
    monkeypatch.setattr(appmod.client.models, "generate_content", fake)
    appmod.classify_query(msg)
    assert len(calls) == 1


# ---------------------------
# End-to-end: same handler + same result as the older shorthand
# ---------------------------
def _seed_timeline(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ScheduleTimeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sched_date TEXT, item_type TEXT, block_code TEXT, event_name TEXT,
            all_day INTEGER NOT NULL DEFAULT 0,
            start_time TEXT, end_time TEXT, item_order INTEGER
        );
        INSERT INTO ScheduleTimeline(sched_date,item_type,block_code,start_time,end_time,item_order) VALUES
            ('2026-09-29','BLOCK','A','08:15','09:35',1),
            ('2026-09-29','COOKIE_BREAK',NULL,'09:35','09:55',2),
            ('2026-09-30','BLOCK','D','08:15','09:35',1);
    """)
    conn.commit(); conn.close()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))
    monkeypatch.setenv("FAKE_TODAY", "2026-09-29")


def _capture_answer(monkeypatch):
    seen = {}
    def fake_answer(user_msg, classifications, results):
        seen["classifications"] = classifications
        seen["results"] = results
        return "ok"
    monkeypatch.setattr(appmod, "generate_answer", fake_answer)
    return seen


def test_block_order_card_prompt_uses_schedule_handler(tmp_path, monkeypatch, no_llm):
    _seed_timeline(tmp_path, monkeypatch)
    seen = _capture_answer(monkeypatch)
    resp = appmod.app.test_client().post("/chat", json={"message": "What’s the block order today?"})
    assert resp.status_code == 200 and resp.get_json()["reply"] == "ok"
    (r,) = seen["results"]
    assert r["type"] == "SCHEDULE" and r["date"] == "2026-09-29"
    assert [x["block_code"] for x in r["rows"] if x["item_type"] == "BLOCK"] == ["A"]


def test_natural_and_shorthand_block_order_give_identical_results(tmp_path, monkeypatch, no_llm):
    _seed_timeline(tmp_path, monkeypatch)
    seen = _capture_answer(monkeypatch)
    client = appmod.app.test_client()
    client.post("/chat", json={"message": "whats the block order tmr"})
    shorthand = seen["results"]
    client.post("/chat", json={"message": "What’s the block order tomorrow?"})
    natural = seen["results"]
    assert shorthand == natural
    assert natural[0]["type"] == "SCHEDULE" and natural[0]["date"] == "2026-09-30"


def test_natural_and_shorthand_meals_give_identical_results(monkeypatch, no_llm):
    # Uses the seeded db/school.db (built by set_up_db.py) like the other meal tests.
    monkeypatch.setenv("FAKE_TODAY", "2026-09-29")
    seen = _capture_answer(monkeypatch)
    client = appmod.app.test_client()
    client.post("/chat", json={"message": "meal tmr"})
    shorthand = seen["results"]
    client.post("/chat", json={"message": "What are we eating tomorrow?"})
    natural = seen["results"]
    assert shorthand == natural
    assert natural[0]["type"] == "MEALS_DAY" and natural[0]["day_name"] == "Wednesday"
    assert natural[0]["rows"], "seeded DB should have Wednesday meals"

    client.post("/chat", json={"message": "What’s for lunch tomorrow?"})
    lunch = seen["results"][0]
    assert lunch["type"] == "MEAL" and lunch["meal_type"] == "LUNCH" and lunch["day_name"] == "Wednesday"


def test_general_question_still_uses_regular_chat_flow(monkeypatch):
    calls = []
    def fake(*a, **k):
        calls.append(k)
        class R: text = '{"requests":[{"intent":"SCHOOL_INFO","school_query":"clubs"}]}'
        return R()
    monkeypatch.setattr(appmod.client.models, "generate_content", fake)
    seen = _capture_answer(monkeypatch)
    resp = appmod.app.test_client().post("/chat", json={"message": "Tell me about clubs."})
    assert resp.status_code == 200
    assert calls, "general questions go through the Gemini classifier"
    assert seen["results"][0]["type"] == "SCHOOL_INFO"
