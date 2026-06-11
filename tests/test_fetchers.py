"""Lock fetcher behavior so the Tier-3 dedup refactor stays behavior-preserving."""
import app as appmod
import set_up_db


def seed(tmp_path, monkeypatch):
    db = tmp_path / "school.db"
    monkeypatch.setattr(set_up_db, "DB_PATH", str(db))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))
    return db


def test_fetch_meal_single_type_both_groups(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    rows = appmod.fetch_meal(1, "LUNCH")  # Monday lunch
    assert [r["group_name"] for r in rows] == ["Junior", "Senior"]
    assert all(r["type_name"] == "LUNCH" for r in rows)


def test_lunch_ends_at_14_00_both_groups(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    rows = appmod.fetch_meal(1, "LUNCH")  # Monday lunch
    by_group = {r["group_name"]: (r["start_time"], r["end_time"]) for r in rows}
    assert by_group["Junior"] == ("13:00", "14:00")
    assert by_group["Senior"] == ("13:15", "14:00")


def test_fetch_day_meals_ordered_by_type_then_group(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    rows = appmod.fetch_day_meals(1)  # Monday: BREAKFAST, LUNCH, DINNER x2 groups
    seen = [(r["type_name"], r["group_name"]) for r in rows]
    assert seen[:4] == [
        ("BREAKFAST", "Junior"), ("BREAKFAST", "Senior"),
        ("LUNCH", "Junior"), ("LUNCH", "Senior"),
    ]


def test_blocks_table_removed(tmp_path, monkeypatch):
    db = seed(tmp_path, monkeypatch)
    import sqlite3
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "Blocks" not in tables
