import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

import app as appmod
import school_events


@pytest.fixture(autouse=True)
def isolated_events(monkeypatch, tmp_path):
    monkeypatch.setattr(school_events, "load_calendar", lambda: {"events": []})
    monkeypatch.setattr(school_events, "FEATURED_PATH", tmp_path / "featured.json")
    monkeypatch.setattr(appmod, "current_school_time", lambda: clock("2026-09-29T21:00"))


def clock(value):
    return datetime.fromisoformat(value).replace(tzinfo=appmod.SCHOOL_TZ)


def regular(day, title):
    return {"date": day, "end_date": day, "title": title, "start_time": "09:55",
            "end_time": "10:20", "all_day": False, "is_special": False}


def make_db(tmp_path, monkeypatch):
    db = tmp_path / "school.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ScheduleTimeline (
          sched_date TEXT, item_type TEXT, event_name TEXT,
          start_time TEXT, end_time TEXT, all_day INTEGER, item_order INTEGER
        );
        INSERT INTO ScheduleTimeline VALUES
          ('2026-09-28','ASSEMBLY',NULL,'09:55','10:20',0,1),
          ('2026-09-29','EVENT','Private appointment','', '',1,1),
          ('2026-09-30','EVENT','Counselor appointment','13:00', '14:00',0,2),
          ('2026-09-30','TUTORIAL',NULL,'09:55','10:20',0,1),
          ('2026-10-01','ADVISORY',NULL,'09:55','10:20',0,1),
          ('2026-10-02','ASSEMBLY',NULL,'09:55','10:20',0,1),
          ('2026-10-03','BLOCK',NULL,'08:15','09:35',0,1);
    """)
    conn.close()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))


def test_sidebar_shows_only_upcoming_public_events_and_caps(monkeypatch, tmp_path):
    make_db(tmp_path, monkeypatch)
    response = appmod.app.test_client().get("/api/upcoming-events")
    assert response.status_code == 200
    assert response.get_json() == {"events": [
        regular("2026-09-30", "Tutorial"),
        regular("2026-10-01", "Advisory"),
        regular("2026-10-02", "Assembly"),
    ]}


def test_sidebar_omits_private_events_and_blocks(monkeypatch, tmp_path):
    make_db(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "current_school_time", lambda: clock("2026-10-03T08:00"))
    assert appmod.app.test_client().get("/api/upcoming-events").get_json() == {"events": []}


def test_bare_upcoming_events_alias_is_gone():
    # nginx proxies only /api/*, so the bare path never worked in production.
    assert appmod.app.test_client().get("/upcoming-events").status_code != 200


def test_special_events_outrank_earlier_routine_periods(monkeypatch, tmp_path):
    make_db(tmp_path, monkeypatch)
    monkeypatch.setattr(school_events, "load_calendar", lambda: {"events": [
        {"title": "Cabaret", "date": "2026-10-02", "start_time": "17:00", "end_time": "19:00"},
        {"title": "Open House", "date": "2026-10-01", "all_day": True},
    ]})
    events = appmod.app.test_client().get("/api/upcoming-events").get_json()["events"]
    assert [r["title"] for r in events] == ["Open House", "Cabaret", "Tutorial"]
    assert [r["is_special"] for r in events] == [True, True, False]


def test_owner_supplied_powwow_is_first_and_expires(monkeypatch, tmp_path):
    make_db(tmp_path, monkeypatch)
    monkeypatch.setattr(school_events, "FEATURED_PATH", Path(__file__).resolve().parents[1] / "data/featured_events.json")
    client = appmod.app.test_client()
    event = client.get("/api/upcoming-events").get_json()["events"][0]
    assert event == {"date": "2026-09-30", "end_date": "2026-09-30",
                     "title": "South Island Powwow 2026", "start_time": "10:00",
                     "end_time": "14:30", "all_day": False, "is_special": True}
    monkeypatch.setattr(appmod, "current_school_time", lambda: clock("2026-09-30T14:29"))
    assert client.get("/api/upcoming-events").get_json()["events"][0] == event
    monkeypatch.setattr(appmod, "current_school_time", lambda: clock("2026-09-30T14:30"))
    assert [r["title"] for r in client.get("/api/upcoming-events").get_json()["events"]] == ["Advisory", "Assembly"]


def test_ended_routine_period_is_removed_same_day(monkeypatch, tmp_path):
    make_db(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "current_school_time", lambda: clock("2026-09-30T10:20"))
    assert [r["title"] for r in appmod.app.test_client().get("/api/upcoming-events").get_json()["events"]] == ["Advisory", "Assembly"]


def test_ongoing_all_day_events_dedup_and_two_week_window(monkeypatch):
    event = {"title": "Strathcona trip", "date": "2026-09-28", "end_date": "2026-09-30", "all_day": True}
    monkeypatch.setattr(school_events, "load_special_events", lambda: [event, event,
        {"title": "Far future event", "date": "2026-10-14", "all_day": True},
        {"title": "Expired", "date": "2026-09-28", "all_day": True}])
    rows = school_events.upcoming_events(clock("2026-09-29T23:59"), [])
    assert [r["title"] for r in rows] == ["Strathcona trip"]
    assert rows[0]["all_day"] and rows[0]["end_date"] == "2026-09-30"
    assert school_events.upcoming_events(clock("2026-09-30T23:59"), [])[0]["title"] == "Strathcona trip"
    assert all(r["title"] != "Strathcona trip" for r in school_events.upcoming_events(clock("2026-10-01T00:00"), []))
