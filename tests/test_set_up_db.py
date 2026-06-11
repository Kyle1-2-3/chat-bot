import sqlite3

import pytest

import set_up_db


def _build(tmp_path, monkeypatch):
    db = tmp_path / "school.db"
    monkeypatch.setattr(set_up_db, "DB_PATH", str(db))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    return db


def _conn(db):
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def test_meal_schedule_unique_constraint(tmp_path, monkeypatch):
    db = _build(tmp_path, monkeypatch)
    conn = _conn(db)
    # Monday(1) / Junior(1) / BREAKFAST(1) is already seeded — a duplicate must fail.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO MealSchedules(day_id,group_id,meal_type_id,start_time,end_time)"
                     " VALUES (1,1,1,'07:00','07:40')")


def test_foreign_key_enforced(tmp_path, monkeypatch):
    db = _build(tmp_path, monkeypatch)
    conn = _conn(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO MealSchedules(day_id,group_id,meal_type_id,start_time,end_time)"
                     " VALUES (1,999,1,'07:00','07:40')")  # group_id 999 doesn't exist


def test_dorm_rules_are_signin_only(tmp_path, monkeypatch):
    """Only SIGN_IN is surfaced; the old made-up PREP/BEDTIME/IN_DORM rows are gone."""
    db = _build(tmp_path, monkeypatch)
    conn = sqlite3.connect(db)
    types_with_rows = {r[0] for r in conn.execute("""
        SELECT DISTINCT rt.type_name
        FROM DormScheduleRules dsr JOIN DormRuleTypes rt ON dsr.rule_type_id = rt.rule_type_id
    """)}
    assert types_with_rows == {"SIGN_IN"}
    all_types = {r[0] for r in conn.execute("SELECT type_name FROM DormRuleTypes")}
    assert all_types == {"SIGN_IN"}


def test_bedtimes(tmp_path, monkeypatch):
    db = _build(tmp_path, monkeypatch)
    conn = sqlite3.connect(db)

    def bt(grade, day):
        r = conn.execute(
            "SELECT bedtime FROM Bedtimes WHERE grade_id=? AND day_id=?", (grade, day)
        ).fetchone()
        return r[0] if r else "NO_ROW"

    # weekday (Mon=1), Saturday=6 (+1h), Sunday=7 (= weekday)
    assert bt(9, 1) == "21:45" and bt(9, 6) == "22:45" and bt(9, 7) == "21:45"
    assert bt(10, 1) == "22:00" and bt(10, 6) == "23:00"
    assert bt(11, 1) == "22:15" and bt(11, 6) == "23:15" and bt(11, 7) == "22:15"
    assert bt(12, 1) is None and bt(12, 6) is None  # grade 12: no set bedtime
    assert bt(8, 1) == "NO_ROW"  # grade 8 not a boarder
    assert conn.execute("SELECT count(*) FROM Bedtimes").fetchone()[0] == 28  # 4 grades x 7 days


def test_grades_mapping(tmp_path, monkeypatch):
    db = _build(tmp_path, monkeypatch)
    conn = sqlite3.connect(db)
    rows = conn.execute("""
        SELECT g.grade_id, gg.group_name
        FROM Grades g JOIN GradeGroups gg ON g.group_id = gg.group_id
        ORDER BY g.grade_id
    """).fetchall()
    assert rows == [
        (8, "Junior"), (9, "Junior"), (10, "Junior"),
        (11, "Senior"), (12, "Senior"),
    ]


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    """set_up_db must be safe to re-run (deploy reseeds every push)."""
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    set_up_db.init_db()  # second run must not raise "table already exists"


def test_sunday_dorm_signins(tmp_path, monkeypatch):
    """Sunday: morning (untimed) + common 19:15 + a night sign-in (jr 20:45 / sr 21:15)."""
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()

    import sqlite3
    conn = sqlite3.connect(tmp_path / "school.db")
    def signins(group_id):
        return conn.execute("""
            SELECT dsr.start_time, dsr.note
            FROM DormScheduleRules dsr
            JOIN DormSchedules ds ON dsr.dorm_schedule_id = ds.dorm_schedule_id
            JOIN DormRuleTypes rt ON dsr.rule_type_id = rt.rule_type_id
            WHERE ds.day_id = 7 AND ds.group_id = ? AND rt.type_name='SIGN_IN'
            ORDER BY dsr.rule_order
        """, (group_id,)).fetchall()

    jr = signins(1)
    assert jr[0][0] is None and "morning" in jr[0][1].lower()  # untimed morning sign-in
    assert jr[1] == ("19:15", None)
    assert jr[2] == ("20:45", None)
    sr = signins(2)
    assert sr[0][0] is None and "morning" in sr[0][1].lower()
    assert sr[1] == ("19:15", None)
    assert sr[2] == ("21:15", None)


def test_init_db_creates_core_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(set_up_db, "DB_PATH", str(tmp_path / "school.db"))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()

    import sqlite3
    conn = sqlite3.connect(tmp_path / "school.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"Days", "MealSchedules", "Menus", "DormScheduleRules", "ScheduleTimeline"} <= tables
    assert conn.execute("SELECT count(*) FROM Days").fetchone()[0] == 7
