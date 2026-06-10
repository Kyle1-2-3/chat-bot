import sqlite3

import pytest

import sync_menus as sm


def fs_doc(days: dict) -> dict:
    """Build a Firestore-document-shaped dict: {day: {meal: text}}."""
    return {
        "fields": {
            day: {"mapValue": {"fields": {
                meal: {"stringValue": txt} for meal, txt in meals.items()
            }}}
            for day, meals in days.items()
        }
    }


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE MealTypes (meal_type_id INTEGER PRIMARY KEY, type_name TEXT NOT NULL);
        CREATE TABLE MealSchedules (
            schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER, group_id INTEGER, meal_type_id INTEGER,
            start_time TEXT, end_time TEXT, requires_signin INTEGER DEFAULT 0
        );
        CREATE TABLE Menus (
            menu_id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER UNIQUE NOT NULL,
            menu_content TEXT NOT NULL
        );
        INSERT INTO MealTypes VALUES
            (1,'BREAKFAST'),(2,'LUNCH'),(3,'DINNER'),(4,'BRUNCH'),(5,'AFTERNOON_SNACK');
    """)
    for g in (1, 2):
        c.execute("INSERT INTO MealSchedules(day_id,group_id,meal_type_id,start_time,end_time) VALUES (1,?,1,'07:00','07:40')", (g,))
        c.execute("INSERT INTO MealSchedules(day_id,group_id,meal_type_id,start_time,end_time) VALUES (1,?,3,'17:15','18:30')", (g,))
        c.execute("INSERT INTO MealSchedules(day_id,group_id,meal_type_id,start_time,end_time) VALUES (7,?,4,'10:00','12:00')", (g,))
    return c


# ---------------------------
# parse_menu_doc
# ---------------------------
def test_parse_maps_weekday_meals():
    doc = fs_doc({"Monday": {"Breakfast": "Eggs", "Lunch": "Soup", "Dinner": "Pasta"}})
    assert sm.parse_menu_doc(doc) == {1: {"BREAKFAST": "Eggs", "LUNCH": "Soup", "DINNER": "Pasta"}}


def test_parse_strips_whitespace_to_empty():
    doc = fs_doc({"Saturday": {"Dinner": "\n", "Lunch": "  Chef's Choice "}})
    assert sm.parse_menu_doc(doc) == {6: {"DINNER": "", "LUNCH": "Chef's Choice"}}


def test_parse_sunday_lunch_becomes_brunch():
    doc = fs_doc({"Sunday": {"Breakfast": "", "Lunch": "Chef's Choice", "Dinner": "Roast"}})
    assert sm.parse_menu_doc(doc) == {7: {"BRUNCH": "Chef's Choice", "DINNER": "Roast"}}


def test_parse_sunday_combines_breakfast_and_lunch_into_brunch():
    doc = fs_doc({"Sunday": {"Breakfast": "Pancakes", "Lunch": "Chef's Choice", "Dinner": ""}})
    assert sm.parse_menu_doc(doc)[7]["BRUNCH"] == "Pancakes\n\nChef's Choice"


def test_parse_ignores_unknown_days_and_meals():
    doc = fs_doc({"Funday": {"Lunch": "X"}, "Monday": {"Teatime": "Y"}})
    assert sm.parse_menu_doc(doc) == {1: {}}


# ---------------------------
# apply_menus
# ---------------------------
def all_menus(conn):
    return conn.execute("""
        SELECT ms.group_id, m.menu_content
        FROM Menus m JOIN MealSchedules ms ON ms.schedule_id = m.schedule_id
        ORDER BY ms.group_id
    """).fetchall()


def test_apply_inserts_menu_for_all_groups(conn):
    sm.apply_menus(conn, {1: {"BREAKFAST": "Eggs"}})
    assert all_menus(conn) == [(1, "Eggs"), (2, "Eggs")]


def test_apply_updates_existing_menu_without_duplicating(conn):
    sm.apply_menus(conn, {1: {"BREAKFAST": "Eggs"}})
    sm.apply_menus(conn, {1: {"BREAKFAST": "Waffles"}})
    assert all_menus(conn) == [(1, "Waffles"), (2, "Waffles")]


def test_apply_empty_text_clears_menu(conn):
    sm.apply_menus(conn, {1: {"BREAKFAST": "Eggs"}})
    sm.apply_menus(conn, {1: {"BREAKFAST": ""}})
    assert all_menus(conn) == []


def test_apply_skips_meal_without_schedule(conn):
    stats = sm.apply_menus(conn, {1: {"LUNCH": "Soup"}})  # fixture has no Monday LUNCH rows
    assert all_menus(conn) == []
    assert stats["skipped"] == 1


def test_apply_sunday_brunch(conn):
    sm.apply_menus(conn, {7: {"BRUNCH": "Chef's Choice"}})
    assert all_menus(conn) == [(1, "Chef's Choice"), (2, "Chef's Choice")]
