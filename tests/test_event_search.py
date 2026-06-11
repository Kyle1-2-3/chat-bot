import sqlite3
from datetime import date

import app as appmod


# ---------------------------
# validate_request keeps EVENT_SEARCH + event_name
# ---------------------------
def test_validate_keeps_event_name():
    out = appmod.validate_request({"intent": "EVENT_SEARCH", "event_name": "assembly"})
    assert out["intent"] == "EVENT_SEARCH"
    assert out["event_name"] == "ASSEMBLY"  # normalized to upper


def test_validate_nulls_invalid_event_name():
    out = appmod.validate_request({"intent": "EVENT_SEARCH", "event_name": "lunch"})
    assert out["intent"] == "EVENT_SEARCH"
    assert out["event_name"] is None


def test_validate_non_event_intent_has_null_event_name():
    out = appmod.validate_request({"intent": "MEAL", "meal_type": "LUNCH"})
    assert out["event_name"] is None


# ---------------------------
# fetch_next_event: nearest upcoming, past excluded
# ---------------------------
def _seed(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ScheduleTimeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sched_date TEXT, item_type TEXT, block_code TEXT,
            start_time TEXT, end_time TEXT, item_order INTEGER
        );
        INSERT INTO ScheduleTimeline(sched_date,item_type,block_code,start_time,end_time,item_order) VALUES
            ('2026-04-13','ASSEMBLY',NULL,'09:00','09:30',2),
            ('2026-04-22','ASSEMBLY',NULL,'09:00','09:30',2),
            ('2026-04-29','ASSEMBLY',NULL,'09:00','09:30',2),
            ('2026-04-23','TUTORIAL',NULL,'13:00','13:40',5);
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))


def test_fetch_next_event_returns_nearest_upcoming(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    rows = appmod.fetch_next_event("ASSEMBLY", "2026-04-20")  # 04-13 is past, 04-22 is next
    assert len(rows) == 1
    assert rows[0]["sched_date"] == "2026-04-22"
    assert rows[0]["start_time"] == "09:00"


def test_fetch_next_event_includes_today(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    rows = appmod.fetch_next_event("ASSEMBLY", "2026-04-22")  # today counts
    assert rows[0]["sched_date"] == "2026-04-22"


def test_fetch_next_event_none_when_no_upcoming(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert appmod.fetch_next_event("ASSEMBLY", "2026-05-01") == []


# ---------------------------
# build_result_from_classification EVENT_SEARCH branch
# ---------------------------
def test_build_result_event_search(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 20))
    res = appmod.build_result_from_classification(
        {"intent": "EVENT_SEARCH", "event_name": "TUTORIAL"}, "when is tutorial"
    )
    assert res["type"] == "EVENT_SEARCH"
    assert res["event_name"] == "TUTORIAL"
    assert res["rows"][0]["date"] == "2026-04-23"
    assert res["rows"][0]["day_name"] == "Thursday"
    assert res["rows"][0]["start_time"] == "13:00"


def test_build_result_event_search_no_event_name(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 20))
    res = appmod.build_result_from_classification(
        {"intent": "EVENT_SEARCH", "event_name": None}, "when is it"
    )
    assert res["type"] == "EVENT_SEARCH"
    assert res["rows"] == []


# ---------------------------
# /chat EVENT_SEARCH path
# ---------------------------
def test_chat_event_search_path(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 20))
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "EVENT_SEARCH", "event_name": "ASSEMBLY", "day_ref": "ANY", "meal_type": None},
    ])
    monkeypatch.setattr(appmod, "fetch_next_event",
                        lambda item_type, from_date: [{"sched_date": "2026-04-22", "start_time": "09:00", "end_time": "09:30"}])
    captured = {}
    monkeypatch.setattr(appmod, "generate_answer",
                        lambda msg, cls, results: captured.setdefault("results", results) or "ok")

    appmod.app.test_client().post("/chat", json={"message": "when is assembly"})
    ev = captured["results"][0]
    assert ev["type"] == "EVENT_SEARCH"
    assert ev["event_name"] == "ASSEMBLY"
    assert ev["rows"][0]["day_name"] == "Wednesday"
    assert ev["rows"][0]["start_time"] == "09:00"
