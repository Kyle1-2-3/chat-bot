import json
from datetime import date

import pytest

import app as appmod
import school_calendar as cal
import sync_school_data as sync


def event(title, start="20261211", end="20270105", extra="", uid="leave"):
    return (f"BEGIN:VEVENT\nUID:{uid}\nDTSTART;VALUE=DATE:{start}\n"
            f"DTEND;VALUE=DATE:{end}\nSUMMARY:{title}\n{extra}\nEND:VEVENT\n")


def feed(*events):
    return "BEGIN:VCALENDAR\n" + "".join(events) + "END:VCALENDAR\n"


@pytest.fixture
def seed(monkeypatch, tmp_path):
    monkeypatch.setattr(cal, "SNAPSHOT_PATH", tmp_path / "calendar.json")
    return cal.load_calendar()


def test_exclusive_end_and_explicit_resume_not_inferred():
    text = feed(event("3am Winter Break"), event("Winter Term classes commence", "20270105", "20270106", uid="resume"))
    row = cal.parse_calendar(text, date(2026, 9, 23))["leaves"][0]
    assert (row["last_leave_date"], row["classes_resume_date"]) == ("2027-01-04", "2027-01-05")
    assert row["start_time"] == "03:00"
    row = cal.parse_calendar(feed(event("3am Winter Break")), date(2026, 9, 23))["leaves"][0]
    assert row["classes_resume_date"] is None


def test_only_whole_school_leaves_are_selected():
    text = feed(event("3am Winter Break"),
                event("Rowing: Spring Break Camp", uid="camp"),
                event("Faculty Holiday (Thanksgiving Leave)", uid="faculty"),
                event("Christmas Day", uid="holiday"), event("Break for Space", uid="other"))
    assert len(cal.parse_calendar(text, date(2026, 9, 23))["leaves"]) == 1


def test_latest_cancellation_overrides_old_event():
    text = feed(event("3am Winter Break"),
                event("3am Winter Break", extra="SEQUENCE:2\nSTATUS:CANCELLED"),
                event("3am Spring Break", "20270312", "20270331", uid="spring"))
    assert [r["name"] for r in cal.parse_calendar(text, date(2026, 9, 23))["leaves"]] == ["Spring Break"]


@pytest.mark.parametrize("text", ["<html>error</html>", feed(), feed(event("3am Winter Break", extra="RRULE:FREQ=YEARLY")),
                                  feed(event("3am Winter Break", end="20271231"))])
def test_bad_refresh_preserves_existing_file(monkeypatch, tmp_path, text):
    path = tmp_path / "snapshot.json"
    path.write_text("previous snapshot")
    monkeypatch.setattr(cal, "fetch_ical", lambda _: text)
    with pytest.raises(ValueError):
        cal.sync_calendar(date(2026, 9, 23), path)
    assert path.read_text() == "previous snapshot"


def test_changed_leave_clears_stale_travel_return_date(monkeypatch, tmp_path):
    path = tmp_path / "snapshot.json"
    monkeypatch.setattr(cal, "fetch_ical", lambda _: feed(event("3am Winter Break")))
    assert cal.sync_calendar(date(2026, 9, 23), path)["leaves"][0]["return_date"] == "2027-01-04"
    monkeypatch.setattr(cal, "fetch_ical", lambda _: feed(event("3am Winter Break", end="20270106")))
    result = cal.sync_calendar(date(2026, 9, 23), path)
    assert "return_date" not in result["leaves"][0]
    assert json.loads(path.read_text()) == result


def test_summer_departure_end_is_not_summer_return():
    text = feed("BEGIN:VEVENT\nUID:summer\nDTSTART:20270611T223000Z\nDTEND:20270612T063000Z\n"
                "SUMMARY: Student Depart for Summer Break\nEND:VEVENT\n")
    row = cal.parse_calendar(text, date(2026, 9, 23))["leaves"][0]
    assert (row["start_date"], row["start_time"]) == ("2027-06-11", "15:30")
    assert row["last_leave_date"] is None and row["classes_resume_date"] is None


def test_all_seven_verified_leaves_and_countdown(seed):
    result = cal.calendar_result(date(2026, 9, 23))
    assert len(result["leaves"]) == 7
    assert result["leaves"][0]["days_until_start"] == 16
    assert result["leaves"][4]["return_date"] == "2027-03-30"
    assert result["leaves"][4]["classes_resume_date"] == "2027-03-31"


def test_no_past_year_dates_reused(seed):
    assert cal.calendar_result(date(2027, 9, 23))["leaves"] == []
    assert cal.leave_on(date(2027, 12, 25)) is None


def test_break_schedule_omits_normal_blocks_but_keeps_events(seed, monkeypatch):
    rows = [{"item_type": "BLOCK", "block_code": "A"}, {"item_type": "COOKIE_BREAK"},
            {"item_type": "EVENT", "event_name": "Optional camp"}]
    monkeypatch.setattr(appmod, "fetch_timeline_by_date", lambda _: rows)
    result = appmod.build_result_from_classification(
        {"intent": "SCHEDULE", "calendar_date": "2026-12-25"}, "Schedule December 25")
    assert result["school_leave"]["name"] == "Winter Break"
    assert result["rows"] == [rows[-1]] and result["afternoon"]["patterns"] == []


def test_partial_leave_keeps_morning_schedule(seed, monkeypatch):
    rows = [{"item_type": "BLOCK", "block_code": "A", "start_time": "08:15", "end_time": "09:35"}]
    monkeypatch.setattr(appmod, "fetch_timeline_by_date", lambda _: rows)
    result = appmod.build_result_from_classification(
        {"intent": "SCHEDULE", "calendar_date": "2026-10-09"}, "October 9 schedule")
    assert result["rows"] == rows and result["school_leave"]["full_day"] is False
    assert result["afternoon"]["patterns"] == []


@pytest.mark.parametrize("day", ["2026-12-11", "2027-01-04", "2027-07-05"])
def test_no_regular_afternoon_during_leave(seed, day):
    result = appmod.build_result_from_classification({"intent": "AFTERNOON", "calendar_date": day}, "afternoon")
    assert result["patterns"] == [] and result["school_leave"]
    if day == "2027-07-05":
        assert result["school_leave"]["return_date_unknown"] is True


def test_resume_day_uses_regular_pattern_again(seed):
    assert cal.leave_on(date(2027, 1, 5)) is None
    result = appmod.build_result_from_classification(
        {"intent": "AFTERNOON", "calendar_date": "2027-01-05"}, "afternoon")
    assert result["patterns"][0]["kind"] == "SPORT"


def test_classifier_validates_calendar_date_and_accepts_new_intent():
    assert appmod.validate_request({"intent": "SCHOOL_BREAKS"})["intent"] == "SCHOOL_BREAKS"
    assert appmod.validate_request({"intent": "SCHEDULE", "calendar_date": "2027-02-01"})["calendar_date"] == "2027-02-01"
    for invalid in ("2027-02-30", 7, "next Friday"):
        assert "calendar_date" not in appmod.validate_request({"intent": "SCHEDULE", "calendar_date": invalid})


def test_refreshes_are_independent_and_failures_visible(monkeypatch):
    calls = []
    def failed():
        calls.append("public")
        raise ValueError("network unavailable")
    monkeypatch.setattr(sync, "sync_calendar", failed)
    monkeypatch.setattr(sync, "sync_schedule", lambda: calls.append("personal"))
    with pytest.raises(RuntimeError, match="Official leave calendar"):
        sync.main()
    assert calls == ["public", "personal"]
