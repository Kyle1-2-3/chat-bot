from datetime import date, datetime, timezone
import sqlite3

import pytest

import app as appmod
import set_up_db
import sync_schedule as ss


def calendar(*events):
    return "BEGIN:VCALENDAR\n" + "\n".join(
        "BEGIN:VEVENT\n" + event + "\nEND:VEVENT" for event in events
    ) + "\nEND:VCALENDAR"


def test_folded_escaped_event_names_and_simultaneous_events():
    events = calendar(
        "SUMMARY:Science\\, learning and\n community\nDTSTART:20260923T160000Z\nDTEND:20260923T200000Z",
        "SUMMARY:Assembly rehearsal\nDTSTART:20260923T160000Z\nDTEND:20260923T170000Z",
    )
    rows = ss.parse_ical(events)["2026-09-23"]
    assert [r["event_name"] for r in rows] == ["Science, learning andcommunity", "Assembly rehearsal"]
    assert rows[0]["start_time"] == "09:00"


def test_cancelled_event_is_omitted():
    assert ss.parse_ical(calendar(
        "SUMMARY:Cancelled trip\nSTATUS:CANCELLED\nDTSTART:20260923T160000Z"
    )) == {}


def test_all_day_events_respect_exclusive_end_and_have_no_fixed_breaks():
    rows = ss.parse_ical(calendar(
        "SUMMARY:Midterm break\nDTSTART;VALUE=DATE:20261009\nDTEND;VALUE=DATE:20261012"
    ))
    ss.add_fixed_timeline_items(rows)
    assert list(rows) == ["2026-10-09", "2026-10-10", "2026-10-11"]
    assert all(len(day) == 1 and day[0]["all_day"] == 1 and day[0]["start_time"] == "" for day in rows.values())


def test_tzid_and_vancouver_permanent_utc_minus_seven():
    rows = ss.parse_ical(calendar(
        "SUMMARY:Local event\nDTSTART;TZID=America/Vancouver:20261102T090000\nDTEND;TZID=America/Vancouver:20261102T100000",
        "SUMMARY:UTC event\nDTSTART:20261102T160000Z\nDTEND:20261102T170000Z",
    ))["2026-11-02"]
    assert [r["start_time"] for r in rows] == ["09:00", "09:00"]


@pytest.mark.parametrize("title", ["Cross Country - Fall", "Robotics (Attendance Blk 1)", "Advanced Rock Band (Attendance Blk 2)"])
def test_regular_activities_are_excluded(title):
    assert ss.parse_ical(calendar(f"SUMMARY:{title}\nDTSTART:20260923T210000Z")) == {}


def test_counselling_is_an_event_not_an_invented_f_block():
    row = ss.parse_ical(calendar(
        "SUMMARY:University Counselling-F1\nDTSTART:20261007T175500Z"
    ))["2026-10-07"][0]
    assert row["item_type"] == "EVENT"
    assert row["block_code"] is None
    assert row["event_name"] == "University Counselling-F1"


def legacy_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ScheduleTimeline (sched_date TEXT, item_type TEXT, block_code TEXT, start_time TEXT NOT NULL, end_time TEXT NOT NULL, item_order INTEGER)")
    conn.execute("INSERT INTO ScheduleTimeline VALUES ('2026-09-24','BLOCK','A','08:15','09:35',1)")
    conn.commit()
    return conn


def test_migration_event_roundtrip_and_removed_dates(tmp_path, monkeypatch):
    path = tmp_path / "school.db"
    with legacy_db(path) as conn:
        rows = ss.parse_ical(calendar("SUMMARY:School event\nDTSTART:20260925T160000Z"))
        ss.apply_schedule(conn, rows, from_date=date(2026, 9, 23))
        ss.apply_schedule(conn, rows, from_date=date(2026, 9, 23))
        assert conn.execute("SELECT COUNT(*) FROM ScheduleTimeline").fetchone()[0] == 1
    monkeypatch.setattr(appmod, "DB_PATH", str(path))
    assert appmod.fetch_timeline_by_date("2026-09-24") == []
    row = appmod.fetch_timeline_by_date("2026-09-25")[0]
    assert row["event_name"] == "School event" and row["all_day"] == 0


def test_failed_snapshot_write_rolls_back_old_schedule(tmp_path):
    with legacy_db(tmp_path / "school.db") as conn:
        rows = ss.parse_ical(calendar("SUMMARY:School event\nDTSTART:20260925T160000Z"))
        rows["2026-09-25"][0]["start_time"] = None
        with pytest.raises(sqlite3.IntegrityError):
            ss.apply_schedule(conn, rows, from_date=date(2026, 9, 23))
        assert conn.execute("SELECT sched_date FROM ScheduleTimeline").fetchone()[0] == "2026-09-24"


def test_non_calendar_response_preserves_schedule(tmp_path, monkeypatch):
    path = tmp_path / "school.db"
    legacy_db(path).close()
    monkeypatch.setattr(ss, "DB_PATH", str(path))
    monkeypatch.setenv("MSM_ICAL_URL", "https://example.test/calendar")
    monkeypatch.setattr(ss, "fetch_ical", lambda _: "<html>Login required</html>")
    with pytest.raises(ValueError, match="existing schedule preserved"):
        ss.main()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ScheduleTimeline").fetchone()[0] == 1


@pytest.mark.parametrize("module", [ss, appmod])
def test_school_date_stays_on_previous_day_before_vancouver_midnight(module, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            now = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.delenv("FAKE_TODAY", raising=False)
    monkeypatch.setattr(module, "datetime", Clock)
    assert module.today() == date(2026, 9, 23)


def test_seed_schema_supports_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    set_up_db.init_db()
    with sqlite3.connect(set_up_db.DB_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ScheduleTimeline)")}
        assert {"event_name", "all_day"} <= columns
