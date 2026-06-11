"""Sync the academic block schedule from the school's MySchool iCal feed.

The MySchool calendar exposes a tokenized, login-free iCal feed (the "Get iCal"
link on calendar.php): a personal schedule URL that needs no auth, perfect for
a daily cron. Block order is school-wide, so any one account's feed gives it.

Blocks rotate week to week, so the schedule is stored keyed by actual DATE
(not weekday). Each academic course's title ends in its block letter
("... 11-GL-D" -> block D); named items (Assembly, Tutorial, Advisor) pass
through; co-curricular activities, sport, and one-off events are ignored.

Set MSM_ICAL_URL in .env. Run from the repo root: python sync_schedule.py
"""
import os
import re
import ssl
import sqlite3
import urllib.request
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

import certifi
from dotenv import load_dotenv

from net_retry import with_retry

load_dotenv()

DB_PATH = os.path.join("db", "school.db")
SCHOOL_TZ = ZoneInfo("America/Vancouver")

BLOCK_SUFFIX = re.compile(r"-([A-F])$")


def today() -> date:
    """Current date, FAKE_TODAY-aware — must match app.today() so the off-term
    demo's fixture dates aren't treated as past and purged."""
    override = (os.getenv("FAKE_TODAY") or "").strip()
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()
    return datetime.now().date()


def _named_item(summary: str) -> str | None:
    if summary == "Assembly":
        return "ASSEMBLY"
    if summary == "Tutorial":
        return "TUTORIAL"
    if summary.startswith("Advisor"):
        return "ADVISORY"
    return None


def _parse_dt(value: str) -> datetime:
    """Parse an iCal UTC timestamp (YYYYMMDDTHHMMSSZ) into school local time."""
    dt = datetime.strptime(value.strip(), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(SCHOOL_TZ)


def parse_ical(text: str) -> dict[str, list[dict]]:
    """iCal text -> {YYYY-MM-DD: [timeline rows sorted by time, with item_order]}."""
    events = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S)
    by_date: dict[str, list[dict]] = {}
    seen: set[tuple] = set()

    for body in events:
        fields = {}
        for line in body.strip().splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                fields[key.strip()] = val.strip()

        summary = fields.get("SUMMARY", "")
        dtstart = fields.get("DTSTART", "")
        dtend = fields.get("DTEND", "")
        if not summary or "Z" not in dtstart:
            continue

        m = BLOCK_SUFFIX.search(summary)
        if m:
            item_type, block_code = "BLOCK", m.group(1)
        else:
            item_type = _named_item(summary)
            block_code = None
            if item_type is None:
                continue

        start_local = _parse_dt(dtstart)
        end_local = _parse_dt(dtend) if "Z" in dtend else start_local
        date_key = start_local.strftime("%Y-%m-%d")

        dedup = (date_key, item_type, block_code, start_local.strftime("%H:%M"))
        if dedup in seen:
            continue
        seen.add(dedup)

        by_date.setdefault(date_key, []).append({
            "item_type": item_type,
            "block_code": block_code,
            "start_time": start_local.strftime("%H:%M"),
            "end_time": end_local.strftime("%H:%M"),
            "_sort": start_local,
        })

    for date_key, rows in by_date.items():
        rows.sort(key=lambda r: r["_sort"])
        for i, r in enumerate(rows, start=1):
            r["item_order"] = i
            del r["_sort"]

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


def apply_schedule(conn: sqlite3.Connection, by_date: dict[str, list[dict]]) -> dict:
    """Replace each synced date's timeline rows with the parsed ones."""
    cur = conn.cursor()
    stats = {"dates": 0, "rows": 0}
    for date_key, rows in by_date.items():
        cur.execute("DELETE FROM ScheduleTimeline WHERE sched_date = ?", (date_key,))
        for r in rows:
            cur.execute("""
                INSERT INTO ScheduleTimeline(sched_date, item_type, block_code, start_time, end_time, item_order)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (date_key, r["item_type"], r["block_code"], r["start_time"], r["end_time"], r["item_order"]))
            stats["rows"] += 1
        stats["dates"] += 1
    conn.commit()
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
    by_date = parse_ical(text)
    add_fixed_timeline_items(by_date)
    conn = sqlite3.connect(DB_PATH)
    stats = apply_schedule(conn, by_date)
    purged = purge_past(conn, today())
    conn.close()
    print(f"Schedule sync done: {stats['rows']} rows across {stats['dates']} dates, {purged} past rows purged")


if __name__ == "__main__":
    main()
