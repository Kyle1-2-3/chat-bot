import sqlite3

import app as appmod


def _seed(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ScheduleTimeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sched_date TEXT, item_type TEXT, block_code TEXT, event_name TEXT,
            all_day INTEGER NOT NULL DEFAULT 0,
            start_time TEXT, end_time TEXT, item_order INTEGER
        );
        INSERT INTO ScheduleTimeline(sched_date,item_type,block_code,event_name,all_day,start_time,end_time,item_order) VALUES
            ('2026-09-20','EVENT',NULL,'Old Fair',0,'10:00','11:00',1),
            ('2026-09-30','EVENT',NULL,'Clubs Fair',0,'15:30','17:00',1),
            ('2026-09-29','BLOCK','A',NULL,0,'08:30','09:30',1),
            ('2026-10-02','EVENT',NULL,'Terry Fox Run',1,'00:00','23:59',1);
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))
    monkeypatch.setenv("FAKE_TODAY", "2026-09-29")


def test_home_feed_lists_upcoming_events_only(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    resp = appmod.app.test_client().get("/api/home")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["today"] == "2026-09-29"
    names = [e["name"] for e in body["events"]]
    assert names == ["Clubs Fair", "Terry Fox Run"]  # past event and BLOCK rows excluded
    assert body["events"][0]["start_time"] == "15:30"
    assert body["events"][1]["all_day"] is True


def test_home_feed_includes_upcoming_leaves_with_source(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    body = appmod.app.test_client().get("/api/home").get_json()
    assert body["calendar_url"].startswith("https://www.brentwood.ca/")
    assert body["health_centre"] is None  # no structured hours in the data yet
    for leave in body["leaves"]:
        assert leave["start_date"] >= "2026-09-29"
        assert leave["source_url"]
        assert leave["name"]


def test_home_feed_survives_missing_table(tmp_path, monkeypatch):
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))
    monkeypatch.setenv("FAKE_TODAY", "2026-09-29")
    body = appmod.app.test_client().get("/api/home").get_json()
    assert body["events"] == []
