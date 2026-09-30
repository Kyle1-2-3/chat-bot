"""Sidebar highlights from the public calendar and explicitly supplied events."""
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from school_calendar import SCHOOL_TZ, load_calendar

FEATURED_PATH = Path(__file__).resolve().parent / "data/featured_events.json"


def load_special_events():
    # Never read general EVENT rows from the personal MySchool calendar here.
    # Additional entries are specific events the owner asked to publish.
    events = list(load_calendar().get("events", []))
    try:
        events.extend(json.loads(FEATURED_PATH.read_text())["events"])
    except FileNotFoundError:
        pass
    return events


def upcoming_events(now: datetime, regular_events: list[dict], limit: int = 3) -> list[dict]:
    """Special events first, then regular periods, within the next 14 days.

    Keep ongoing multi-day/all-day events; remove timed events when they end.
    The list contains event names, not a claim that every student must attend.
    """
    now = now.astimezone(SCHOOL_TZ)
    until = now.date() + timedelta(days=14)
    candidates = [(row, True) for row in load_special_events()]
    candidates.extend((row, False) for row in regular_events)
    selected = {}
    for row, special in candidates:
        start = date.fromisoformat(row["date"])
        end = date.fromisoformat(row.get("end_date") or row["date"])
        all_day = bool(row.get("all_day"))
        end_time = row.get("end_time") or ""
        if all_day or not end_time:
            expires = datetime.combine(end + timedelta(days=1), time(), SCHOOL_TZ)
        else:
            expires = datetime.combine(end, time.fromisoformat(end_time), SCHOOL_TZ)
        if start > until or expires <= now:
            continue
        event = {"date": start.isoformat(), "end_date": end.isoformat(),
                 "title": row["title"], "start_time": row.get("start_time") or "",
                 "end_time": end_time, "all_day": all_day, "is_special": special}
        # A public calendar item may also be explicitly featured; show it once.
        key = (event["date"], " ".join(event["title"].casefold().split()),
               event["start_time"], event["end_date"], event["end_time"])
        if key not in selected or special:
            selected[key] = event
    return sorted(selected.values(), key=lambda e: (
        not e["is_special"], e["date"], e["start_time"], e["title"]
    ))[:limit]
