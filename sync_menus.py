"""Sync this week's menus from the school's public Firestore doc into the local DB.

food.brentwood.ca stores the weekly menu in a public Firestore document
(readable without auth; the API key below is the site's own public web key).
The doc is one week, overwritten in place, shaped day -> {Breakfast, Lunch, Dinner}.

Run from the repo root: python sync_menus.py
"""
import json
import sqlite3
import ssl
import urllib.request

import certifi

from net_retry import with_retry

DB_PATH = "db/school.db"

FIRESTORE_URL = (
    "https://firestore.googleapis.com/v1/projects/brentwood-food-menu/databases/(default)/documents/"
    "artifacts/1:644774431045:web:a52e05cc6bfeca7fdb562c/public/data/menu/weeklyMenu"
    "?key=AIzaSyBN39f7GdaCsXwXGt5b2YJ-IYBVVj8G5Uo"
)

DAY_IDS = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4,
    "Friday": 5, "Saturday": 6, "Sunday": 7,
}

WEEKDAY_MEAL_KEYS = {"Breakfast": "BREAKFAST", "Lunch": "LUNCH", "Dinner": "DINNER"}


def parse_menu_doc(doc: dict) -> dict[int, dict[str, str]]:
    """Firestore doc -> {day_id: {MEAL_TYPE: menu_text}}. Empty text means "clear".

    Sunday is special: the school serves brunch, so its Breakfast/Lunch entries
    map onto our BRUNCH slot (joined if both are filled).
    """
    out: dict[int, dict[str, str]] = {}
    for day_name, day_val in (doc.get("fields") or {}).items():
        day_id = DAY_IDS.get(day_name)
        if day_id is None:
            continue
        fields = day_val.get("mapValue", {}).get("fields", {})
        meals = {k: (v.get("stringValue") or "").strip() for k, v in fields.items()}

        if day_id == 7:
            mapped = {}
            if "Breakfast" in meals or "Lunch" in meals:
                parts = [meals.get(k, "") for k in ("Breakfast", "Lunch")]
                mapped["BRUNCH"] = "\n\n".join(p for p in parts if p)
            if "Dinner" in meals:
                mapped["DINNER"] = meals["Dinner"]
        else:
            mapped = {
                WEEKDAY_MEAL_KEYS[k]: v
                for k, v in meals.items() if k in WEEKDAY_MEAL_KEYS
            }

        out[day_id] = mapped
    return out


def apply_menus(conn: sqlite3.Connection, menus: dict[int, dict[str, str]]) -> dict:
    """Upsert non-empty menus into Menus (all grade groups); delete rows for empty ones."""
    cur = conn.cursor()
    stats = {"set": 0, "cleared": 0, "skipped": 0}

    for day_id, meals in menus.items():
        for type_name, text in meals.items():
            schedule_ids = [r[0] for r in cur.execute("""
                SELECT ms.schedule_id
                FROM MealSchedules ms
                JOIN MealTypes mt ON mt.meal_type_id = ms.meal_type_id
                WHERE ms.day_id = ? AND mt.type_name = ?
            """, (day_id, type_name))]

            if not schedule_ids:
                stats["skipped"] += 1
                continue

            for sid in schedule_ids:
                if text:
                    cur.execute("""
                        INSERT INTO Menus(schedule_id, menu_content) VALUES (?, ?)
                        ON CONFLICT(schedule_id) DO UPDATE SET menu_content = excluded.menu_content
                    """, (sid, text))
                    stats["set"] += 1
                else:
                    cur.execute("DELETE FROM Menus WHERE schedule_id = ?", (sid,))
                    stats["cleared"] += 1

    conn.commit()
    return stats


def fetch_menu_doc() -> dict:
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(FIRESTORE_URL, timeout=30, context=ctx) as resp:
        return json.load(resp)


def main():
    doc = with_retry(lambda: fetch_menu_doc())
    menus = parse_menu_doc(doc)
    conn = sqlite3.connect(DB_PATH)
    stats = apply_menus(conn, menus)
    conn.close()
    print(f"Menu sync done: {stats['set']} set, {stats['cleared']} cleared, {stats['skipped']} skipped")


if __name__ == "__main__":
    main()
