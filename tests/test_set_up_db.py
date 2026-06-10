import importlib

import set_up_db


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    """set_up_db must be safe to re-run (deploy reseeds every push)."""
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    set_up_db.init_db()  # second run must not raise "table already exists"


def test_init_db_creates_core_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()

    import sqlite3
    conn = sqlite3.connect(tmp_path / "school.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"Days", "MealSchedules", "Menus", "DormScheduleRules", "ScheduleTimeline"} <= tables
    assert conn.execute("SELECT count(*) FROM Days").fetchone()[0] == 7
