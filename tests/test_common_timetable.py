from copy import deepcopy
from datetime import date

import pytest

import app as appmod
import set_up_db
import sync_schedule as ss


def block(letter, start, end):
    return {"item_type": "BLOCK", "block_code": letter,
            "start_time": start, "end_time": end}


@pytest.mark.parametrize("day, observed, expected", [
    ("2026-09-24", [("D", "10:25", "11:45"), ("E", "11:55", "13:15")],
     [("F", "08:15", "09:35"), ("D", "10:25", "11:45"), ("E", "11:55", "13:15")]),
    ("2026-09-28", [("E", "08:15", "09:35"), ("D", "11:55", "13:15")],
     [("E", "08:15", "09:35"), ("F", "10:25", "11:45"), ("D", "11:55", "13:15")]),
    ("2026-09-22", [("D", "08:15", "09:35"), ("E", "10:25", "11:45")],
     [("D", "08:15", "09:35"), ("E", "10:25", "11:45"), ("F", "11:55", "13:15")]),
    ("2026-10-07", [("E", "09:30", "10:35"), ("D", "12:10", "13:15")],
     [("E", "09:30", "10:35"), ("F", "10:55", "12:00"), ("D", "12:10", "13:15")]),
    ("2026-10-03", [("D", "10:15", "11:00"), ("E", "11:10", "11:55")],
     [("D", "10:15", "11:00"), ("E", "11:10", "11:55"), ("F", "12:05", "12:50")]),
    ("2026-09-21", [("A", "08:15", "09:35"), ("C", "11:55", "13:15")],
     [("A", "08:15", "09:35"), ("B", "10:25", "11:45"), ("C", "11:55", "13:15")]),
])
def test_free_period_completed_from_dated_observations(day, observed, expected):
    rows = {day: [block(*b) for b in observed]}
    assert ss.complete_common_timetable(rows) == 1
    assert [(r["block_code"], r["start_time"], r["end_time"])
            for r in rows[day] if r["item_type"] == "BLOCK"] == expected


@pytest.mark.parametrize("day, rows", [
    ("2026-09-24", []),
    ("2026-09-24", [block("D", "10:25", "11:45")]),
    ("2026-09-24", [block("D", "10:30", "11:00"), block("E", "11:10", "11:40")]),
    ("2026-09-24", [block("A", "10:25", "11:45"), block("E", "11:55", "13:15")]),
    ("2026-09-24", [block("D", "10:25", "11:45"), block("E", "10:25", "11:45")]),
    ("2026-09-27", [block("D", "10:25", "11:45"), block("E", "11:55", "13:15")]),
    ("2026-09-26", [block("F", "10:15", "11:00"), block("D", "11:10", "11:55")]),
])
def test_unconfirmed_or_exception_days_are_not_filled(day, rows):
    data = {day: rows}
    before = deepcopy(data)
    assert ss.complete_common_timetable(data) == 0
    assert data == before


def test_event_only_days_do_not_create_blocks_or_advance_rotation():
    data = {"2026-09-30": [{"item_type": "EVENT", "block_code": None,
                           "event_name": "Special day", "start_time": "", "end_time": "", "all_day": 1}]}
    before = deepcopy(data)
    ss.complete_common_timetable(data)
    ss.add_fixed_timeline_items(data)
    assert data == before


def test_named_periods_and_breaks_are_idempotent_and_preserve_explicit_times():
    data = {"2026-09-24": [block("D", "10:25", "11:45"), block("E", "11:55", "13:15"),
            {"item_type": "ASSEMBLY", "block_code": None, "start_time": "09:55", "end_time": "10:25"}]}
    for _ in range(2):
        ss.complete_common_timetable(data)
        ss.add_fixed_timeline_items(data)
    assert len(data["2026-09-24"]) == 5
    assembly = [r for r in data["2026-09-24"] if r["item_type"] == "ASSEMBLY"]
    assert len(assembly) == 1 and assembly[0]["end_time"] == "10:25"


def test_sync_pipeline_persists_complete_school_timeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "school.db"
    monkeypatch.setattr(set_up_db, "DB_PATH", str(path))
    set_up_db.init_db()
    monkeypatch.setattr(ss, "DB_PATH", str(path))
    monkeypatch.setattr(ss, "today", lambda: date(2026, 9, 23))
    monkeypatch.setenv("MSM_ICAL_URL", "local-fixture")
    monkeypatch.setattr(ss, "fetch_ical", lambda _: """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Course-D
DTSTART:20260924T172500Z
DTEND:20260924T184500Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Course-E
DTSTART:20260924T185500Z
DTEND:20260924T201500Z
END:VEVENT
END:VCALENDAR""")
    ss.main()
    ss.main()
    monkeypatch.setattr(appmod, "DB_PATH", str(path))
    rows = appmod.fetch_timeline_by_date("2026-09-24")
    assert [(r["item_type"], r["block_code"]) for r in rows] == [
        ("BLOCK", "F"), ("COOKIE_BREAK", None), ("ASSEMBLY", None), ("BLOCK", "D"), ("BLOCK", "E")]
    assert rows[0]["start_time"] == "08:15"


def test_personal_event_in_a_free_period_does_not_remove_the_common_block():
    data = {"2026-10-07": [block("E", "09:30", "10:35"), block("D", "12:10", "13:15"),
        {"item_type": "EVENT", "block_code": None, "event_name": "University Counselling-F1",
         "start_time": "10:55", "end_time": "12:00"}]}
    ss.complete_common_timetable(data)
    assert [r["block_code"] for r in data["2026-10-07"] if r["item_type"] == "BLOCK"] == ["E", "F", "D"]
    assert sum(r["item_type"] == "EVENT" for r in data["2026-10-07"]) == 1
