import sqlite3
from datetime import date

import pytest

import sync_schedule as ss


# Real iCal lines mirror the live feed: UTC DTSTART/DTEND (America/Vancouver = UTC-7 in April).
ICS_MONDAY = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Greater Victoria Performing Arts Festival
DTSTART:20260420T143000Z
DTEND:20260420T220000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:AP Physics 1 Honours 11-GL-D
DTSTART:20260420T151500Z
DTEND:20260420T163500Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Advisor 11-Rogers-MY
DTSTART:20260420T165500Z
DTEND:20260420T172000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Advisor Meeting
DTSTART:20260420T165500Z
DTEND:20260420T172000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Literary Studies 11-SC-E
DTSTART:20260420T172500Z
DTEND:20260420T184500Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:AP Calculus AB 12-JoW-F
DTSTART:20260420T185500Z
DTEND:20260420T201500Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Intermediate Rock Band (1)
DTSTART:20260420T210000Z
DTEND:20260420T220000Z
END:VEVENT
END:VCALENDAR
"""


def test_parse_extracts_blocks_in_order():
    out = ss.parse_ical(ICS_MONDAY)
    rows = out["2026-04-20"]
    blocks = [(r["item_type"], r["block_code"], r["start_time"]) for r in rows if r["item_type"] == "BLOCK"]
    assert blocks == [
        ("BLOCK", "D", "08:15"),
        ("BLOCK", "E", "10:25"),
        ("BLOCK", "F", "11:55"),
    ]


def test_parse_includes_advisory_once_and_in_sequence():
    rows = ss.parse_ical(ICS_MONDAY)["2026-04-20"]
    advisory = [r for r in rows if r["item_type"] == "ADVISORY"]
    assert len(advisory) == 1
    assert advisory[0]["start_time"] == "09:55"
    # item_order is sequential by time across the whole day
    assert [r["item_type"] for r in rows] == ["BLOCK", "ADVISORY", "BLOCK", "BLOCK"]
    assert [r["item_order"] for r in rows] == [1, 2, 3, 4]


def test_parse_excludes_cocurricular_and_events():
    rows = ss.parse_ical(ICS_MONDAY)["2026-04-20"]
    titles = [r["item_type"] for r in rows]
    assert "EVENT" not in titles
    assert all("Rock Band" not in (r.get("block_code") or "") for r in rows)
    assert len(rows) == 4  # 3 blocks + 1 advisory; festival + rock band dropped


def test_parse_maps_named_timeline_items():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Assembly
DTSTART:20260423T165500Z
DTEND:20260423T172500Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Tutorial
DTSTART:20260421T165500Z
DTEND:20260421T172000Z
END:VEVENT
END:VCALENDAR
"""
    out = ss.parse_ical(ics)
    assert out["2026-04-23"][0]["item_type"] == "ASSEMBLY"
    assert out["2026-04-21"][0]["item_type"] == "TUTORIAL"


def test_parse_block_letter_must_be_single_a_to_f():
    # "-MY" or "-Winter" suffixes are not block letters
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Squash - Winter
DTSTART:20260421T210000Z
DTEND:20260421T220000Z
END:VEVENT
END:VCALENDAR
"""
    assert ss.parse_ical(ics).get("2026-04-21", []) == []


# ---------------------------
# apply_schedule
# ---------------------------
@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE ScheduleTimeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sched_date TEXT NOT NULL,
            item_type TEXT NOT NULL,
            block_code TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            item_order INTEGER NOT NULL
        );
    """)
    return c


def rows_for(conn, date):
    return conn.execute(
        "SELECT item_type, block_code, start_time, item_order FROM ScheduleTimeline WHERE sched_date=? ORDER BY item_order",
        (date,),
    ).fetchall()


def test_apply_inserts_rows(conn):
    ss.apply_schedule(conn, ss.parse_ical(ICS_MONDAY))
    assert rows_for(conn, "2026-04-20") == [
        ("BLOCK", "D", "08:15", 1),
        ("ADVISORY", None, "09:55", 2),
        ("BLOCK", "E", "10:25", 3),
        ("BLOCK", "F", "11:55", 4),
    ]


def test_apply_replaces_existing_date(conn):
    ss.apply_schedule(conn, ss.parse_ical(ICS_MONDAY))
    ss.apply_schedule(conn, ss.parse_ical(ICS_MONDAY))  # re-sync same day
    assert len(rows_for(conn, "2026-04-20")) == 4  # not doubled


# ---------------------------
# purge_past + today()
# ---------------------------
def insert_date(conn, d):
    conn.execute(
        "INSERT INTO ScheduleTimeline(sched_date,item_type,block_code,start_time,end_time,item_order)"
        " VALUES (?,?,?,?,?,?)",
        (d, "BLOCK", "A", "08:15", "09:35", 1),
    )


def test_purge_past_keeps_today_and_future(conn):
    for d in ["2026-04-18", "2026-04-19", "2026-04-20", "2026-04-21", "2026-04-25"]:
        insert_date(conn, d)
    deleted = ss.purge_past(conn, date(2026, 4, 20))
    remaining = [r[0] for r in conn.execute(
        "SELECT DISTINCT sched_date FROM ScheduleTimeline ORDER BY sched_date")]
    assert remaining == ["2026-04-20", "2026-04-21", "2026-04-25"]
    assert deleted == 2


def test_today_uses_fake_today(monkeypatch):
    monkeypatch.setenv("FAKE_TODAY", "2026-04-20")
    assert ss.today() == date(2026, 4, 20)


def test_today_ignores_blank_fake_today(monkeypatch):
    monkeypatch.setenv("FAKE_TODAY", "")
    assert isinstance(ss.today(), date)
