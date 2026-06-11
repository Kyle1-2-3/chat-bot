import sqlite3
import os

DB_PATH = "db/school.db"

def init_db():
    os.makedirs("db", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")  # enforce FKs while seeding
    cur = conn.cursor()

    # ---------------------------
    # Reset
    # ---------------------------
    cur.executescript("""
        DROP TABLE IF EXISTS Bedtimes;

        DROP TABLE IF EXISTS DormScheduleRules;
        DROP TABLE IF EXISTS DormSchedules;
        DROP TABLE IF EXISTS DormRuleTypes;

        DROP TABLE IF EXISTS Menus;
        DROP TABLE IF EXISTS MealSchedules;
        DROP TABLE IF EXISTS MealTypes;

        DROP TABLE IF EXISTS ScheduleTimeline;
        DROP TABLE IF EXISTS DayTimeline;

        DROP TABLE IF EXISTS Grades;
        DROP TABLE IF EXISTS GradeGroups;
        DROP TABLE IF EXISTS Days;

        CREATE TABLE Days (
            day_id INTEGER PRIMARY KEY,
            day_name TEXT NOT NULL,
            is_weekend INTEGER NOT NULL
        );

        CREATE TABLE GradeGroups (
            group_id INTEGER PRIMARY KEY,
            group_name TEXT NOT NULL
        );

        -- individual grade (8..12) -> Junior/Senior group
        CREATE TABLE Grades (
            grade_id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL,
            FOREIGN KEY (group_id) REFERENCES GradeGroups(group_id)
        );

        CREATE TABLE MealTypes (
            meal_type_id INTEGER PRIMARY KEY,
            type_name TEXT NOT NULL
        );

        -- ✅ 핵심: requires_signin (meal sign-in)
        CREATE TABLE MealSchedules (
            schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            meal_type_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            requires_signin INTEGER NOT NULL DEFAULT 0,
            UNIQUE (day_id, group_id, meal_type_id),
            FOREIGN KEY (day_id) REFERENCES Days(day_id),
            FOREIGN KEY (group_id) REFERENCES GradeGroups(group_id),
            FOREIGN KEY (meal_type_id) REFERENCES MealTypes(meal_type_id)
        );

        CREATE TABLE Menus (
            menu_id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER UNIQUE NOT NULL,
            menu_content TEXT NOT NULL,
            FOREIGN KEY (schedule_id) REFERENCES MealSchedules(schedule_id)
        );

        -- Block schedule, keyed by actual DATE (blocks rotate week to week).
        -- Populated by sync_schedule.py from the MySchool iCal feed, not seeded here.
        CREATE TABLE ScheduleTimeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sched_date TEXT NOT NULL,
            item_type TEXT NOT NULL,
            block_code TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            item_order INTEGER NOT NULL
        );

        CREATE TABLE DormRuleTypes (
            rule_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_name TEXT NOT NULL
        );

        CREATE TABLE DormSchedules (
            dorm_schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            UNIQUE (day_id, group_id),
            FOREIGN KEY (day_id) REFERENCES Days(day_id),
            FOREIGN KEY (group_id) REFERENCES GradeGroups(group_id)
        );

        CREATE TABLE DormScheduleRules (
            rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dorm_schedule_id INTEGER NOT NULL,
            rule_type_id INTEGER NOT NULL,
            start_time TEXT,            -- NULL when the rule has no fixed clock time
            end_time TEXT,
            rule_order INTEGER NOT NULL,
            note TEXT,                  -- human-readable detail for untimed rules
            FOREIGN KEY (dorm_schedule_id) REFERENCES DormSchedules(dorm_schedule_id),
            FOREIGN KEY (rule_type_id) REFERENCES DormRuleTypes(rule_type_id)
        );

        -- Bedtime is per GRADE (not group), per day. bedtime NULL = no set bedtime.
        CREATE TABLE Bedtimes (
            grade_id INTEGER NOT NULL,
            day_id   INTEGER NOT NULL,
            bedtime  TEXT,
            PRIMARY KEY (grade_id, day_id),
            FOREIGN KEY (grade_id) REFERENCES Grades(grade_id),
            FOREIGN KEY (day_id)   REFERENCES Days(day_id)
        );
    """)

    # ---------------------------
    # Base data
    # ---------------------------
    cur.executemany("INSERT INTO Days(day_id, day_name, is_weekend) VALUES (?, ?, ?)", [
        (1, "Monday", 0), (2, "Tuesday", 0), (3, "Wednesday", 0),
        (4, "Thursday", 0), (5, "Friday", 0), (6, "Saturday", 1), (7, "Sunday", 1)
    ])

    cur.executemany("INSERT INTO GradeGroups(group_id, group_name) VALUES (?, ?)", [
        (1, "Junior"), (2, "Senior")
    ])

    # Grades 8-10 = Junior, 11-12 = Senior
    cur.executemany("INSERT INTO Grades(grade_id, group_id) VALUES (?, ?)", [
        (8, 1), (9, 1), (10, 1), (11, 2), (12, 2)
    ])

    # Bedtime per grade (grade 8 doesn't board, grade 12 has none).
    # Mon-Fri (1-5) and Sun (7) share the weekday time; Sat (6) is +1 hour.
    weekday_bedtime = {9: "21:45", 10: "22:00", 11: "22:15", 12: None}
    saturday_bedtime = {9: "22:45", 10: "23:00", 11: "23:15", 12: None}
    bedtimes = []
    for grade in (9, 10, 11, 12):
        for day in (1, 2, 3, 4, 5, 7):
            bedtimes.append((grade, day, weekday_bedtime[grade]))
        bedtimes.append((grade, 6, saturday_bedtime[grade]))
    cur.executemany("INSERT INTO Bedtimes(grade_id, day_id, bedtime) VALUES (?, ?, ?)", bedtimes)

    # ✅ Meal types include Sunday special
    cur.executemany("INSERT INTO MealTypes(meal_type_id, type_name) VALUES (?, ?)", [
        (1, "BREAKFAST"),
        (2, "LUNCH"),
        (3, "DINNER"),
        (4, "BRUNCH"),
        (5, "AFTERNOON_SNACK"),
    ])

    # ---------------------------
    # Meal schedules
    # Rules you described:
    # - Meal sign-in happens at meal time
    # - Breakfast + Dinner: sign-in required
    # - Lunch: no sign-in
    # - Sunday: BRUNCH, AFTERNOON_SNACK, DINNER
    #   - Brunch/snack: no sign-in
    #   - Dinner: sign-in required
    # ---------------------------
    def meal_type_id(name: str) -> int:
        row = cur.execute("SELECT meal_type_id FROM MealTypes WHERE type_name=?", (name,)).fetchone()
        return row[0]

    schedules = []

    for d in range(1, 8):
        for group_id in (1, 2):  # Junior/Senior
            if d == 7:
                # Sunday special meals: BRUNCH / AFTERNOON_SNACK / DINNER
                schedules.append((d, group_id, meal_type_id("BRUNCH"), "10:00", "12:00", 0))
                schedules.append((d, group_id, meal_type_id("AFTERNOON_SNACK"), "13:00", "14:00", 0))
                schedules.append((d, group_id, meal_type_id("DINNER"), "17:15", "18:30", 1))
            else:
                # Mon-Sat: Breakfast / Lunch / Dinner
                # Breakfast times (your old logic)
                bst, bet = ("07:00", "07:40")
                if d in (3, 6):  # Wed + Sat
                    bst, bet = ("08:00", "08:40")

                # Lunch times (no meal sign-in)
                if group_id == 1:
                    lst, let = ("13:00", "13:40")
                else:
                    lst, let = ("13:15", "13:55")

                # Dinner times (sign-in required)
                dst, det = ("17:15", "18:30")

                schedules.append((d, group_id, meal_type_id("BREAKFAST"), bst, bet, 1))
                schedules.append((d, group_id, meal_type_id("LUNCH"), lst, let, 0))
                schedules.append((d, group_id, meal_type_id("DINNER"), dst, det, 1))

    cur.executemany("""
        INSERT INTO MealSchedules(day_id, group_id, meal_type_id, start_time, end_time, requires_signin)
        VALUES (?, ?, ?, ?, ?, ?)
    """, schedules)

    # ---------------------------
    # Menus
    # NOTE: Menus stored per (day, meal_type). We’ll apply same menu to both groups.
    # ---------------------------
    menus_by_day = {
        1: {"BREAKFAST": "Scrambled Eggs, Bacon & Hash Browns", "LUNCH": "Ravioli", "DINNER": "Sweet Chili Chicken"},
        2: {"BREAKFAST": "Fried Eggs & Chorizo", "LUNCH": "Chicken Shawarma Bowl", "DINNER": "Beef Stroganoff"},
        3: {"BREAKFAST": "Brentwood Cakes", "LUNCH": "Pierogies & Bratwurst", "DINNER": "Dumpling Drop"},
        4: {"BREAKFAST": "Western Omelettes", "LUNCH": "Ginger Beef Bowl", "DINNER": "Pesto Chicken"},
        5: {"BREAKFAST": "Cheddar Scramble", "LUNCH": "Greek Orzo Bowl", "DINNER": "Turkey Shepherd's Pie"},
        6: {"BREAKFAST": "French Toast", "LUNCH": "Chef's Choice", "DINNER": "Popcorn Chicken Bowl"},
        7: {"BRUNCH": "Brunch: Pancakes", "AFTERNOON_SNACK": "Afternoon Snack", "DINNER": "Homemade Rotini"},
    }

    for day_id, meals in menus_by_day.items():
        for mtype, content in meals.items():
            # Apply to both groups
            for group_id in (1, 2):
                cur.execute("""
                    INSERT INTO Menus(schedule_id, menu_content)
                    SELECT schedule_id, ?
                    FROM MealSchedules
                    WHERE day_id = ?
                      AND group_id = ?
                      AND meal_type_id = (SELECT meal_type_id FROM MealTypes WHERE type_name = ?)
                """, (content, day_id, group_id, mtype))

    # ScheduleTimeline is left empty here; sync_schedule.py fills it from the
    # live iCal feed (block order rotates by date, so it can't be seeded).

    # ---------------------------
    # Dorm rules
    # Dorm SIGN_IN only = dorm sign-in times
    # - Weekdays: 19:15 (one)
    # - Saturday: 19:15 + 22:00/22:30 (two sign-ins)
    # - Sunday: morning dorm sign-in + 19:15 evening sign-in (and no meal sign-in questions here)
    #   You can adjust morning time to your real data.
    # ---------------------------
    dorm_rule_types = ["SIGN_IN", "PREP", "BEDTIME", "IN_DORM"]
    for rt in dorm_rule_types:
        cur.execute("INSERT INTO DormRuleTypes(type_name) VALUES (?)", (rt,))

    def dorm_rule_type_id(name: str) -> int:
        row = cur.execute("SELECT rule_type_id FROM DormRuleTypes WHERE type_name=?", (name,)).fetchone()
        return row[0]

    SIGN_IN_ID = dorm_rule_type_id("SIGN_IN")
    PREP_ID = dorm_rule_type_id("PREP")
    BEDTIME_ID = dorm_rule_type_id("BEDTIME")
    IN_DORM_ID = dorm_rule_type_id("IN_DORM")  # kept, but not used for sign-in now

    for d in range(1, 8):
        for g in (1, 2):  # 1 junior, 2 senior
            cur.execute("INSERT INTO DormSchedules(day_id, group_id) VALUES (?, ?)", (d, g))
            ds_id = cur.lastrowid

            if d <= 5:
                # Weekdays: one dorm sign-in
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, rule_order)
                    VALUES (?, ?, '19:15', 1)
                """, (ds_id, SIGN_IN_ID))

                # Prep + bedtime
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, end_time, rule_order)
                    VALUES (?, ?, '19:30', '21:00', 2)
                """, (ds_id, PREP_ID))

                bt = "22:00" if g == 1 else "22:15"
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, rule_order)
                    VALUES (?, ?, ?, 3)
                """, (ds_id, BEDTIME_ID, bt))

            elif d == 6:
                # Saturday: two dorm sign-ins
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, rule_order)
                    VALUES (?, ?, '19:15', 1)
                """, (ds_id, SIGN_IN_ID))

                extra = "22:00" if g == 1 else "22:30"
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, rule_order)
                    VALUES (?, ?, ?, 2)
                """, (ds_id, SIGN_IN_ID, extra))

                bt = "23:00" if g == 1 else "23:15"
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, rule_order)
                    VALUES (?, ?, ?, 3)
                """, (ds_id, BEDTIME_ID, bt))

            else:
                # Sunday: an untimed morning sign-in + a night sign-in.
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, rule_order, note)
                    VALUES (?, ?, NULL, 1, 'No set time — sign in any time in the morning')
                """, (ds_id, SIGN_IN_ID))

                night = "20:45" if g == 1 else "21:15"
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, rule_order)
                    VALUES (?, ?, ?, 2)
                """, (ds_id, SIGN_IN_ID, night))

                bt = "22:00" if g == 1 else "22:15"
                cur.execute("""
                    INSERT INTO DormScheduleRules(dorm_schedule_id, rule_type_id, start_time, rule_order)
                    VALUES (?, ?, ?, 3)
                """, (ds_id, BEDTIME_ID, bt))

    conn.commit()
    conn.close()
    print("✨ DB rebuilt with meal-signin + Sunday special meals + dorm-only sign-in!")

if __name__ == "__main__":
    init_db()