import sqlite3
from datetime import date

import app as appmod


def make_db(tmp_path, monkeypatch):
    db = tmp_path / "school.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ScheduleTimeline (
          sched_date TEXT, item_type TEXT, event_name TEXT,
          start_time TEXT, end_time TEXT, all_day INTEGER, item_order INTEGER
        );
        INSERT INTO ScheduleTimeline VALUES
          ('2026-09-28','ASSEMBLY',NULL,'09:55','10:20',0,1),
          ('2026-09-29','EVENT','Private appointment','', '',1,1),
          ('2026-09-30','TUTORIAL',NULL,'09:55','10:20',0,1),
          ('2026-10-01','ADVISORY',NULL,'09:55','10:20',0,1),
          ('2026-10-02','ASSEMBLY',NULL,'09:55','10:20',0,1),
          ('2026-10-03','BLOCK',NULL,'08:15','09:35',0,1);
    """)
    conn.close()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))


def test_sidebar_shows_only_upcoming_public_events_and_caps(monkeypatch, tmp_path):
    make_db(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 9, 29))
    response = appmod.app.test_client().get("/upcoming-events")
    assert response.status_code == 200
    assert response.get_json() == {"events": [
        {"date": "2026-09-30", "title": "Tutorial", "start_time": "09:55", "end_time": "10:20"},
        {"date": "2026-10-01", "title": "Advisory", "start_time": "09:55", "end_time": "10:20"},
        {"date": "2026-10-02", "title": "Assembly", "start_time": "09:55", "end_time": "10:20"},
    ]}


def test_sidebar_omits_private_events_and_blocks(monkeypatch, tmp_path):
    make_db(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 10, 3))
    assert appmod.app.test_client().get("/upcoming-events").get_json() == {"events": []}
