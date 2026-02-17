import sqlite3
import os

DB_PATH = "db/school.db"

def init_db():
    if not os.path.exists('db'): os.makedirs('db')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 테이블 초기화 (사용자 요청 리스트 기반)
    cur.executescript("""
        DROP TABLE IF EXISTS DormScheduleRules; DROP TABLE IF EXISTS DormSchedules;
        DROP TABLE IF EXISTS DormRuleTypes; DROP TABLE IF EXISTS Menus;
        DROP TABLE IF EXISTS MealSchedules; DROP TABLE IF EXISTS DayTimeline;
        DROP TABLE IF EXISTS Blocks; DROP TABLE IF EXISTS MealTypes;
        DROP TABLE IF EXISTS Grades; DROP TABLE IF EXISTS GradeGroups;
        DROP TABLE IF EXISTS Days;

        CREATE TABLE Days (day_id INTEGER PRIMARY KEY, day_name TEXT, is_weekend BOOLEAN);
        CREATE TABLE GradeGroups (group_id INTEGER PRIMARY KEY, group_name TEXT);
        CREATE TABLE Grades (grade_id INTEGER PRIMARY KEY, group_id INTEGER);
        CREATE TABLE MealTypes (meal_type_id INTEGER PRIMARY KEY, type_name TEXT);
        CREATE TABLE Blocks (block_id INTEGER PRIMARY KEY AUTOINCREMENT, block_code TEXT);
        CREATE TABLE MealSchedules (
            schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER, group_id INTEGER, meal_type_id INTEGER,
            start_time TEXT, end_time TEXT
        );
        CREATE TABLE Menus (
            menu_id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER UNIQUE, menu_content TEXT
        );
        CREATE TABLE DayTimeline (
            timeline_id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER, item_type TEXT, block_id INTEGER, 
            start_time TEXT, end_time TEXT, item_order REAL
        );
        CREATE TABLE DormRuleTypes (rule_type_id INTEGER PRIMARY KEY AUTOINCREMENT, type_name TEXT);
        CREATE TABLE DormSchedules (dorm_schedule_id INTEGER PRIMARY KEY AUTOINCREMENT, day_id INTEGER, group_id INTEGER);
        CREATE TABLE DormScheduleRules (
            rule_id INTEGER PRIMARY KEY AUTOINCREMENT, dorm_schedule_id INTEGER,
            rule_type_id INTEGER, start_time TEXT, end_time TEXT, rule_order INTEGER
        );
    """)

    # 1. 기초 데이터 (요일, 그룹, 식사타입, 블록)
    cur.executemany("INSERT INTO Days VALUES (?, ?, ?)", [
        (1, "Monday", 0), (2, "Tuesday", 0), (3, "Wednesday", 0),
        (4, "Thursday", 0), (5, "Friday", 0), (6, "Saturday", 1), (7, "Sunday", 1)
    ])
    cur.executemany("INSERT INTO GradeGroups VALUES (?, ?)", [(1, "Junior"), (2, "Senior")])
    cur.executemany("INSERT INTO MealTypes VALUES (?, ?)", [(1, "BREAKFAST"), (2, "LUNCH"), (3, "DINNER")])
    for b in ["A", "B", "C", "D", "E", "F"]:
        cur.execute("INSERT INTO Blocks (block_code) VALUES (?)", (b,))

    # 2. 급식 스케줄 (사용자 제공 로직)
    schedules = []
    for d in range(1, 8):
        # 아침
        st, et = ("07:00", "07:40")
        if d in [3, 6]: st, et = ("08:00", "08:40")
        elif d == 7: st, et = ("10:00", "12:00")
        schedules.extend([(d, 1, 1, st, et), (d, 2, 1, st, et)])
        # 점심
        if d < 7:
            schedules.append((d, 1, 2, "13:00", "13:40")) # Junior
            schedules.append((d, 2, 2, "13:15", "13:55")) # Senior
        else:
            schedules.extend([(7, 1, 2, "13:00", "14:00"), (7, 2, 2, "13:00", "14:00")])
        # 저녁
        schedules.extend([(d, 1, 3, "17:15", "18:30"), (d, 2, 3, "17:15", "18:30")])
    cur.executemany("INSERT INTO MealSchedules (day_id, group_id, meal_type_id, start_time, end_time) VALUES (?, ?, ?, ?, ?)", schedules)

    # 3. 메뉴 (사용자 제공 리스트)
    menus_data = [
        (1, "BREAKFAST", "Scrambled Eggs, Bacon & Hash Browns"), (1, "LUNCH", "Ravioli"), (1, "DINNER", "Sweet Chili Chicken"),
        (2, "BREAKFAST", "Fried Eggs & Chorizo"), (2, "LUNCH", "Chicken Shawarma Bowl"), (2, "DINNER", "Beef Stroganoff"),
        (3, "BREAKFAST", "Brentwood Cakes"), (3, "LUNCH", "Pierogies & Bratwurst"), (3, "DINNER", "Dumpling Drop"),
        (4, "BREAKFAST", "Western Omelettes"), (4, "LUNCH", "Ginger Beef Bowl"), (4, "DINNER", "Pesto Chicken"),
        (5, "BREAKFAST", "Cheddar Scramble"), (5, "LUNCH", "Greek Orzo Bowl"), (5, "DINNER", "Turkey Shepherd's Pie"),
        (6, "BREAKFAST", "French Toast"), (6, "LUNCH", "Chef's Choice"), (6, "DINNER", "Popcorn Chicken Bowl"),
        (7, "BREAKFAST", "Brunch: Pancakes"), (7, "LUNCH", "Afternoon Snack"), (7, "DINNER", "Homemade Rotini")
    ]
    for d_id, m_t, cont in menus_data:
        cur.execute("""
            INSERT INTO Menus (schedule_id, menu_content)
            SELECT schedule_id, ? FROM MealSchedules 
            WHERE day_id=? AND meal_type_id=(SELECT meal_type_id FROM MealTypes WHERE type_name=?)
        """, (cont, d_id, m_t))

    # 4. 타임라인 및 시간 보정 (사용자 제공 로직)
    # 블록 순서 입력
    block_orders = {1:["A","B","C"], 2:["D","E","F"], 3:["C","A","B"], 4:["F","D","E"], 5:["B","C","A"], 6:["D","E","F"]}
    for d_id, b_codes in block_orders.items():
        for i, code in enumerate(b_codes):
            cur.execute("""
                INSERT INTO DayTimeline (day_id, item_type, block_id, start_time, end_time, item_order)
                VALUES (?, 'BLOCK', (SELECT block_id FROM Blocks WHERE block_code=?), '00:00', '00:00', ?)
            """, (d_id, code, i+1))
    
    # 시간 보정 (사용자 UPDATE 구문 반영)
    cur.execute("UPDATE DayTimeline SET start_time='08:15', end_time='09:35' WHERE item_type='BLOCK' AND item_order=1 AND day_id IN (1,2,4,5)")
    cur.execute("UPDATE DayTimeline SET start_time='10:25', end_time='11:45' WHERE item_type='BLOCK' AND item_order=2 AND day_id IN (1,2,4,5)")
    cur.execute("UPDATE DayTimeline SET start_time='11:55', end_time='13:15' WHERE item_type='BLOCK' AND item_order=3 AND day_id IN (1,2,4,5)")
    cur.execute("UPDATE DayTimeline SET start_time='09:30', end_time='10:35' WHERE item_type='BLOCK' AND item_order=1 AND day_id=3")
    cur.execute("UPDATE DayTimeline SET start_time='10:55', end_time='12:00' WHERE item_type='BLOCK' AND item_order=2 AND day_id=3")
    cur.execute("UPDATE DayTimeline SET start_time='12:10', end_time='13:15' WHERE item_type='BLOCK' AND item_order=3 AND day_id=3")
    cur.execute("UPDATE DayTimeline SET start_time='10:15', end_time='11:00' WHERE item_type='BLOCK' AND item_order=1 AND day_id=6")
    cur.execute("UPDATE DayTimeline SET start_time='11:10', end_time='11:55' WHERE item_type='BLOCK' AND item_order=2 AND day_id=6")
    cur.execute("UPDATE DayTimeline SET start_time='12:05', end_time='12:50' WHERE item_type='BLOCK' AND item_order=3 AND day_id=6")

    # 고정 이벤트 (Assembly 등)
    for d in [1, 2, 4, 5]:
        itype = "ADVISORY" if d == 1 else ("ASSEMBLY" if d == 4 else "COOKIE_BREAK")
        cur.execute("INSERT INTO DayTimeline (day_id, item_type, start_time, end_time, item_order) VALUES (?, ?, '09:55', '10:20', 1.5)", (d, itype))
    cur.execute("INSERT INTO DayTimeline (day_id, item_type, start_time, end_time, item_order) VALUES (3, 'COOKIE_BREAK', '10:35', '10:55', 1.5)")

    # 5. 기숙사 규칙 (사용자 제공 로직)
    rt_list = ["SIGN_IN", "PREP", "BEDTIME", "IN_DORM"]
    for rt in rt_list: cur.execute("INSERT INTO DormRuleTypes (type_name) VALUES (?)", (rt,))
    
    for d in range(1, 8):
        for g in [1, 2]:
            cur.execute("INSERT INTO DormSchedules (day_id, group_id) VALUES (?, ?)", (d, g))
            ds_id = cur.lastrowid
            # 공통 Sign-in
            cur.execute("INSERT INTO DormScheduleRules (dorm_schedule_id, rule_type_id, start_time, rule_order) VALUES (?, 1, '19:15', 1)", (ds_id,))
            if d <= 5: # 평일
                cur.execute("INSERT INTO DormScheduleRules (dorm_schedule_id, rule_type_id, start_time, end_time, rule_order) VALUES (?, 2, '19:30', '21:00', 2)", (ds_id,))
                bt = "22:00" if g == 1 else "22:15"
                cur.execute("INSERT INTO DormScheduleRules (dorm_schedule_id, rule_type_id, start_time, rule_order) VALUES (?, 3, ?, 3)", (ds_id, bt))
            elif d == 6: # 토요일
                cur.execute("INSERT INTO DormScheduleRules (dorm_schedule_id, rule_type_id, start_time, rule_order) VALUES (?, 4, ?, 2)", (ds_id, "22:00" if g==1 else "22:30"))
                cur.execute("INSERT INTO DormScheduleRules (dorm_schedule_id, rule_type_id, start_time, rule_order) VALUES (?, 3, ?, 3)", (ds_id, "23:00" if g==1 else "23:15"))
            elif d == 7: # 일요일
                cur.execute("INSERT INTO DormScheduleRules (dorm_schedule_id, rule_type_id, start_time, rule_order) VALUES (?, 4, ?, 2)", (ds_id, "20:45" if g==1 else "21:15"))
                cur.execute("INSERT INTO DormScheduleRules (dorm_schedule_id, rule_type_id, start_time, rule_order) VALUES (?, 3, ?, 3)", (ds_id, "22:00" if g==1 else "22:15"))

    conn.commit()
    conn.close()
    print("✨ 모든 데이터 설정 완료!")

if __name__ == "__main__":
    init_db()