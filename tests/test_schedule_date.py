import sqlite3
from datetime import date

import pytest

import app as appmod


# ---------------------------
# today() honors FAKE_TODAY
# ---------------------------
def test_today_uses_fake_today(monkeypatch):
    monkeypatch.setenv("FAKE_TODAY", "2026-04-20")
    assert appmod.today() == date(2026, 4, 20)


def test_today_ignores_blank_fake_today(monkeypatch):
    monkeypatch.setenv("FAKE_TODAY", "")
    assert isinstance(appmod.today(), date)  # falls back to real date


# ---------------------------
# resolve_date
# ---------------------------
@pytest.fixture
def fake_monday(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 20))  # a Monday


def test_resolve_date_today(fake_monday):
    assert appmod.resolve_date("TODAY", "") == date(2026, 4, 20)


def test_resolve_date_tomorrow(fake_monday):
    assert appmod.resolve_date("TOMORROW", "") == date(2026, 4, 21)


def test_resolve_date_day_after_tomorrow(fake_monday):
    assert appmod.resolve_date("DAY_AFTER_TOMORROW", "") == date(2026, 4, 22)


def test_resolve_date_named_weekday_picks_upcoming(fake_monday):
    # Thursday from a Monday -> same week's Thursday
    assert appmod.resolve_date("THURSDAY", "") == date(2026, 4, 23)


def test_resolve_date_named_weekday_today_returns_today(fake_monday):
    assert appmod.resolve_date("MONDAY", "") == date(2026, 4, 20)


# ---------------------------
# fetch_timeline_by_date
# ---------------------------
def test_fetch_timeline_by_date(monkeypatch, tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ScheduleTimeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sched_date TEXT, item_type TEXT, block_code TEXT,
            start_time TEXT, end_time TEXT, item_order INTEGER
        );
        INSERT INTO ScheduleTimeline(sched_date,item_type,block_code,start_time,end_time,item_order) VALUES
            ('2026-04-20','BLOCK','D','08:15','09:35',1),
            ('2026-04-20','ADVISORY',NULL,'09:55','10:20',2);
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))

    rows = appmod.fetch_timeline_by_date("2026-04-20")
    assert [(r["item_type"], r["block_code"], r["start_time"]) for r in rows] == [
        ("BLOCK", "D", "08:15"),
        ("ADVISORY", None, "09:55"),
    ]
    assert appmod.fetch_timeline_by_date("2026-12-25") == []


# ---------------------------
# /chat SCHEDULE path uses dates
# ---------------------------
def test_chat_schedule_uses_resolved_date(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 4, 20))
    monkeypatch.setattr(appmod, "classify_query", lambda msg: [
        {"intent": "SCHEDULE", "day_ref": "TOMORROW", "meal_type": None, "confidence": 0.9},
    ])
    monkeypatch.setattr(appmod, "fetch_timeline_by_date",
                        lambda d: [{"item_type": "BLOCK", "block_code": "C", "start_time": "08:15", "end_time": "09:35", "item_order": 1}])
    captured = {}
    monkeypatch.setattr(appmod, "generate_answer",
                        lambda msg, cls, results: captured.setdefault("results", results) or "ok")

    appmod.app.test_client().post("/chat", json={"message": "blocks tomorrow"})
    sched = captured["results"][0]
    assert sched["type"] == "SCHEDULE"
    assert sched["date"] == "2026-04-21"
    assert sched["day_name"] == "Tuesday"
    assert sched["rows"][0]["block_code"] == "C"
