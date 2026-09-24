"""Refresh both calendars independently, reporting failure without losing either."""
import logging

from school_calendar import sync_calendar
from sync_schedule import main as sync_schedule


def main():
    failures = []
    for name, sync in (("Official leave calendar", sync_calendar), ("MySchool schedule", sync_schedule)):
        try:
            sync()
            print(f"{name}: refreshed")
        except Exception:
            logging.exception("%s sync failed; previous snapshot preserved", name)
            failures.append(name)
    if failures:
        raise RuntimeError("Calendar refresh failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
