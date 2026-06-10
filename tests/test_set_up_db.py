import importlib

import set_up_db


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    """set_up_db must be safe to re-run (deploy reseeds every push)."""
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    set_up_db.init_db()  # second run must not raise "table already exists"


def test_sunday_dorm_signins(tmp_path, monkeypatch):
    """Sunday: a morning sign-in (no set time) + a night sign-in (jr 20:45 / sr 21:15)."""
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()

    import sqlite3
    conn = sqlite3.connect(tmp_path / "school.db")
    def signins(group_id):
        return [r[0] for r in conn.execute("""
            SELECT dsr.start_time
            FROM DormScheduleRules dsr
            JOIN DormSchedules ds ON dsr.dorm_schedule_id = ds.dorm_schedule_id
            JOIN DormRuleTypes rt ON dsr.rule_type_id = rt.rule_type_id
            WHERE ds.day_id = 7 AND ds.group_id = ? AND rt.type_name='SIGN_IN'
            ORDER BY dsr.rule_order
        """, (group_id,))]
    assert signins(1) == ["morning", "20:45"]
    assert signins(2) == ["morning", "21:15"]


def test_init_db_creates_core_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()

    import sqlite3
    conn = sqlite3.connect(tmp_path / "school.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"Days", "MealSchedules", "Menus", "DormScheduleRules", "ScheduleTimeline"} <= tables
    assert conn.execute("SELECT count(*) FROM Days").fetchone()[0] == 7
