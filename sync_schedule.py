"""Sync the academic block schedule from the school's MySchool iCal feed.

The MySchool calendar exposes a tokenized, login-free iCal feed (the "Get iCal"
link on calendar.php): a personal schedule URL that needs no auth, perfect for
a daily cron. Block order is school-wide, so any one account's feed gives it.

Blocks rotate week to week, so the schedule is stored keyed by actual DATE
(not weekday). Each academic course's title ends in its block letter
("... 11-GL-D" -> block D); named items (Assembly, Tutorial, Advisor) pass
through; special events retain their names. Regular co-curricular classes and
seasonal sports are excluded. No block is inferred for an empty personal slot.

Set MSM_ICAL_URL in .env. Run from the repo root: python sync_schedule.py
"""
import os
import re
import ssl
import sqlite3
import urllib.request
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo

import certifi
from dotenv import load_dotenv

from net_retry import with_retry

load_dotenv()

DB_PATH = os.path.join("db", "school.db")
SCHOOL_TZ = ZoneInfo("America/Vancouver")

BLOCK_SUFFIX = re.compile(r"-([A-F])$")
COCURRICULAR = re.compile(
    r"Attendance Blk| - (?:Fall|Winter|Spring|Summer)$|Rock Band \(\d+\)$", re.I
)


def today() -> date:
    """Current date, FAKE_TODAY-aware — must match app.today() so the off-term
    demo's fixture dates aren't treated as past and purged."""
    override = (os.getenv("FAKE_TODAY") or "").strip()
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()
    return datetime.now(SCHOOL_TZ).date()


def _named_item(summary: str) -> str | None:
    if summary == "Assembly":
        return "ASSEMBLY"
    if summary == "Tutorial":
        return "TUTORIAL"
    if summary.startswith("Advisor"):
        return "ADVISORY"
    return None


def _parse_dt(value: str, tzid: str | None = None) -> datetime:
    """Parse UTC or TZID/floating timestamps into school local time."""
    utc = value.endswith("Z")
    dt = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    dt = dt.replace(tzinfo=timezone.utc if utc else ZoneInfo(tzid) if tzid else SCHOOL_TZ)
    return dt.astimezone(SCHOOL_TZ)


def _unescape(value: str) -> str:
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1] in "nN" else m[1], value)


def parse_ical(text: str) -> dict[str, list[dict]]:
    """iCal text -> {YYYY-MM-DD: [timeline rows sorted by time, with item_order]}."""
    text = re.sub(r"\r?\n[ \t]", "", text)  # RFC 5545 line folding
    events = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S)
    by_date: dict[str, list[dict]] = {}
    seen: set[tuple] = set()

    for body in events:
        fields, params = {}, {}
        for line in body.strip().splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                key, *attrs = key.strip().split(";")
                fields[key] = val.strip()
                params[key] = dict(a.split("=", 1) for a in attrs if "=" in a)

        summary = _unescape(fields.get("SUMMARY", ""))
        dtstart = fields.get("DTSTART", "")
        dtend = fields.get("DTEND", "")
        if not summary or not dtstart or fields.get("STATUS") == "CANCELLED":
            continue

        m = BLOCK_SUFFIX.search(summary)
        if m:
            item_type, block_code = "BLOCK", m.group(1)
        else:
            item_type = _named_item(summary)
            block_code = None
            if item_type is None:
                if COCURRICULAR.search(summary):
                    continue
                item_type = "EVENT"

        all_day = params.get("DTSTART", {}).get("VALUE") == "DATE" or len(dtstart) == 8
        if all_day:
            first = datetime.strptime(dtstart, "%Y%m%d").date()
            until = datetime.strptime(dtend, "%Y%m%d").date() if dtend else first + timedelta(days=1)
            dates = [first + timedelta(days=i) for i in range(max((until - first).days, 1))]
            start_time = end_time = ""
        else:
            start_local = _parse_dt(dtstart, params.get("DTSTART", {}).get("TZID"))
            end_local = _parse_dt(dtend, params.get("DTEND", {}).get("TZID")) if dtend else start_local
            dates = [start_local.date()]
            start_time, end_time = start_local.strftime("%H:%M"), end_local.strftime("%H:%M")

        for event_date in dates:
            date_key = event_date.isoformat()
            event_name = summary if item_type == "EVENT" else None
            dedup = (date_key, item_type, block_code, event_name, start_time)
            if dedup in seen:
                continue
            seen.add(dedup)
            by_date.setdefault(date_key, []).append({
                "item_type": item_type, "block_code": block_code,
                "event_name": event_name, "all_day": int(all_day),
                "start_time": start_time, "end_time": end_time,
            })

    for date_key, rows in by_date.items():
        rows.sort(key=lambda r: r["start_time"])
        for i, r in enumerate(rows, start=1):
            r["item_order"] = i

    return by_date


# Weekday-recurring timeline items the iCal feed omits. weekday (Mon=0 .. Sun=6)
# -> list of (item_type, start_time, end_time). Blocks still come from the feed.
FIXED_TIMELINE_ITEMS = {
    0: [("COOKIE_BREAK", "09:35", "09:55")],  # Monday
    1: [("COOKIE_BREAK", "09:35", "09:55")],  # Tuesday
    2: [("COOKIE_BREAK", "10:35", "10:55")],  # Wednesday
    3: [("COOKIE_BREAK", "09:35", "09:55")],  # Thursday
    4: [("COOKIE_BREAK", "09:35", "09:55")],  # Friday (same as Tuesday)
    5: [("INSPECTION", "09:30", "10:00")],    # Saturday
}


def add_fixed_timeline_items(by_date: dict[str, list[dict]]) -> None:
    """Inject weekday-recurring items the iCal feed omits (cookie break,
    Saturday inspection). Only school days already in the feed get them; each
    affected day is then renumbered by time so item_order stays sequential."""
    for date_key, rows in by_date.items():
        if not any(r["item_type"] == "BLOCK" for r in rows):
            continue  # an event-only day must not invent a normal school timetable
        items = FIXED_TIMELINE_ITEMS.get(date.fromisoformat(date_key).weekday())
        if not items:
            continue
        for item_type, start, end in items:
            rows.append({
                "item_type": item_type,
                "block_code": None,
                "start_time": start,
                "end_time": end,
            })
        rows.sort(key=lambda r: r["start_time"])
        for i, r in enumerate(rows, start=1):
            r["item_order"] = i


def apply_schedule(conn: sqlite3.Connection, by_date: dict[str, list[dict]],
                   from_date: date | None = None) -> dict:
    """Atomically replace the feed snapshot; remove cancelled/removed future rows."""
    stats = {"dates": 0, "rows": 0}
    with conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ScheduleTimeline)")}
        for name, definition in [("event_name", "TEXT"), ("all_day", "INTEGER NOT NULL DEFAULT 0")]:
            if name not in columns:
                conn.execute(f"ALTER TABLE ScheduleTimeline ADD COLUMN {name} {definition}")
        if from_date:
            conn.execute("DELETE FROM ScheduleTimeline WHERE sched_date >= ?", (from_date.isoformat(),))
        for date_key, rows in by_date.items():
            if from_date and date_key < from_date.isoformat():
                continue
            conn.execute("DELETE FROM ScheduleTimeline WHERE sched_date = ?", (date_key,))
            for r in rows:
                conn.execute("""
                    INSERT INTO ScheduleTimeline(sched_date, item_type, block_code, start_time, end_time, item_order, event_name, all_day)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (date_key, r["item_type"], r["block_code"], r["start_time"], r["end_time"], r["item_order"], r.get("event_name"), r.get("all_day", 0)))
                stats["rows"] += 1
            stats["dates"] += 1
    return stats


def purge_past(conn: sqlite3.Connection, today_date: date) -> int:
    """Delete schedule rows before today — the bot only needs the upcoming week."""
    cur = conn.cursor()
    cur.execute("DELETE FROM ScheduleTimeline WHERE sched_date < ?", (today_date.isoformat(),))
    conn.commit()
    return cur.rowcount


def fetch_ical(source: str) -> str:
    if source.startswith("http"):
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(source, timeout=30, context=ctx) as resp:
            return resp.read().decode("utf-8")
    with open(source, encoding="utf-8") as f:
        return f.read()


def main():
    source = os.getenv("MSM_ICAL_URL")
    if not source:
        raise SystemExit("MSM_ICAL_URL not set in .env")
    text = with_retry(lambda: fetch_ical(source))
    if "BEGIN:VCALENDAR" not in text or "END:VCALENDAR" not in text:
        raise ValueError("MySchool did not return an iCalendar feed; existing schedule preserved")
    by_date = parse_ical(text)
    add_fixed_timeline_items(by_date)
    conn = sqlite3.connect(DB_PATH)
    stats = apply_schedule(conn, by_date, from_date=today())
    purged = purge_past(conn, today())
    conn.close()
    print(f"Schedule sync done: {stats['rows']} rows across {stats['dates']} dates, {purged} past rows purged")


if __name__ == "__main__":
    main()
