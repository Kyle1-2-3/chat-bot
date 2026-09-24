"""Official school-wide leaves, independent of any student's MySchool feed."""
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from net_retry import with_retry
from sync_schedule import fetch_ical, _unescape

ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT / "db/school_calendar.json"
SEED_PATH = ROOT / "data/school_calendar.json"
SOURCE_URL = "https://www.brentwood.ca/calendar/"
FEED_URL = ("https://calendar.google.com/calendar/ical/"
            "brentwood.ca_3pgnmrpebak3vo7npopp05gp1c%40group.calendar.google.com/public/basic.ics")
SCHOOL_TZ = ZoneInfo("America/Vancouver")
LEAVE_NAMES = {
    "Thanksgiving Leave", "Fall Midterm Break", "Winter Break",
    "Winter Midterm Break", "Spring Break", "Spring Break/Easter Break",
    "May Midterm Break", "Student Depart for Summer Break",
}


def _event_date(value, attrs):
    if len(value) == 8:
        return datetime.strptime(value, "%Y%m%d").date(), None
    tz = timezone.utc if value.endswith("Z") else ZoneInfo(attrs.get("TZID", "America/Vancouver"))
    dt = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=tz).astimezone(SCHOOL_TZ)
    return dt.date(), dt.strftime("%H:%M")


def parse_calendar(text, reference_date):
    """Read explicitly named, non-recurring leaves; all-day DTEND is exclusive.

    Public holidays, rowing camps and faculty-only leaves are not school breaks.
    Unexpected recurrence or ambiguous periods abort before replacing the cache.
    """
    if "BEGIN:VCALENDAR" not in text or "END:VCALENDAR" not in text:
        raise ValueError("Official calendar response is not iCalendar")
    text = re.sub(r"\r?\n[ \t]", "", text)
    year = reference_date.year - (reference_date.month < 8)
    first, until = date(year, 8, 1), date(year + 2, 8, 1)
    events = {}
    for body in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        fields, params = {}, {}
        for line in body.strip().splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key, *attrs = key.split(";")
            fields[key] = val.strip()
            params[key] = dict(a.split("=", 1) for a in attrs if "=" in a)
        uid = fields.get("UID", body)
        revision = (int(fields.get("SEQUENCE", 0)), fields.get("LAST-MODIFIED", ""))
        if uid not in events or revision > events[uid][0]:
            events[uid] = (revision, fields, params)

    leaves, resumes = [], set()
    for _, fields, params in events.values():
        if fields.get("STATUS") == "CANCELLED":
            continue
        title = " ".join(_unescape(fields.get("SUMMARY", "")).split())
        match = re.fullmatch(r"(?:(\d{1,2})(am|pm) )?(.+)", title, re.I)
        if not match:
            continue
        hour, meridiem, name = match.groups()
        is_resume = bool(re.fullmatch(r"(?:Fall|Winter|Spring) Term classes (?:resume|commence)", name))
        if name not in LEAVE_NAMES and not is_resume:
            continue
        start, start_time = _event_date(fields["DTSTART"], params.get("DTSTART", {}))
        if not first <= start < until:
            continue
        if "RRULE" in fields or "RECURRENCE-ID" in fields or "RDATE" in fields:
            raise ValueError("Recurring school leave needs review")
        if is_resume:
            resumes.add(start.isoformat())
            continue
        if hour:
            start_time = f"{int(hour) % 12 + (12 if meridiem.lower() == 'pm' else 0):02}:00"
        summer = name == "Student Depart for Summer Break"
        if summer:
            end = None  # Event DTEND is the departure window, NOT the end of summer.
        else:
            if len(fields.get("DTEND", "")) != 8 or start_time is None:
                raise ValueError("School leave has unsupported date/time format")
            end = _event_date(fields["DTEND"], params.get("DTEND", {}))[0]
            if not 1 <= (end - start).days <= 60:
                raise ValueError("School leave interval needs review")
        sy = start.year - (start.month < 8)
        leaves.append({
            "name": "Summer Break" if summer else name,
            "academic_year": f"{sy}–{sy + 1}",
            "start_date": start.isoformat(), "start_time": start_time,
            "last_leave_date": (end - timedelta(days=1)).isoformat() if end else None,
            "classes_resume_date": None,
            "source_url": SOURCE_URL,
            "source_title": title,
        })
    if not leaves:
        raise ValueError("No recognized current school leaves; preserving existing snapshot")
    leaves.sort(key=lambda r: r["start_date"])
    seen = set()
    for row in leaves:
        if row["start_date"] in seen:
            raise ValueError("Conflicting school leave dates")
        seen.add(row["start_date"])
        if row["last_leave_date"]:
            next_day = (date.fromisoformat(row["last_leave_date"]) + timedelta(days=1)).isoformat()
            if next_day in resumes:
                row["classes_resume_date"] = next_day
    return {"checked_on": reference_date.isoformat(), "source_url": SOURCE_URL, "leaves": leaves}


def load_calendar():
    for path in (SNAPSHOT_PATH, SEED_PATH):
        try:
            data = json.loads(path.read_text())
            if isinstance(data.get("leaves"), list) and data["leaves"]:
                return data
        except (OSError, ValueError):
            continue
    return {"checked_on": None, "source_url": SOURCE_URL, "leaves": []}


def calendar_result(reference_date):
    data = load_calendar()
    year = reference_date.year - (reference_date.month < 8)
    first = date(year, 8, 1).isoformat()
    rows = [{**r, "days_until_start": (date.fromisoformat(r["start_date"]) - reference_date).days}
            for r in data["leaves"] if r["start_date"] >= first]
    return {**data, "leaves": rows, "today": reference_date.isoformat()}


def leave_on(day):
    for row in load_calendar()["leaves"]:
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["last_leave_date"]) if row["last_leave_date"] else start
        if start <= day <= end:
            return {**row, "full_day": day > start or bool(row["start_time"] and row["start_time"] < "08:00")}
        if row["name"] == "Summer Break" and start < day <= date(start.year, 8, 31):
            # A departure event does not publish a return date. Suppress the
            # unconfirmed weekly pattern, but do not assert a no-class interval.
            return {**row, "full_day": False, "return_date_unknown": True}
    return None


def sync_calendar(reference_date=None, output_path=None):
    reference_date = reference_date or datetime.now(SCHOOL_TZ).date()
    data = parse_calendar(with_retry(lambda: fetch_ical(FEED_URL)), reference_date)
    # Return-to-campus dates were separately checked on the official Travel site.
    # Keep that corroboration only while BOTH live boundaries still match it.
    seed = json.loads(SEED_PATH.read_text())
    for row in data["leaves"]:
        old = next((r for r in seed["leaves"] if all(r[k] == row[k] for k in
                    ("name", "start_date", "last_leave_date"))), {})
        for key in ("return_date", "travel_source_url", "travel_checked_on", "source_note"):
            if key in old:
                row[key] = old[key]
    output_path = Path(output_path or SNAPSHOT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=output_path.parent, delete=False) as f:
            temporary = f.name
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temporary, output_path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return data


if __name__ == "__main__":
    snapshot = sync_calendar()
    print(f"Official school calendar synced: {len(snapshot['leaves'])} leaves")
