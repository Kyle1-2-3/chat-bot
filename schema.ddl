-- =========================
-- 공통 기준 테이블
-- =========================

-- 학년 그룹 (Junior / Senior)
CREATE TABLE GradeGroups (
    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL UNIQUE
);

-- 개별 학년 (9,10,11,12)
CREATE TABLE Grades (
    grade_id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL,
    FOREIGN KEY (group_id) REFERENCES GradeGroups(group_id)
);

-- 요일
CREATE TABLE Days (
    day_id INTEGER PRIMARY KEY, -- 1=MON ... 7=SUN
    day_name TEXT NOT NULL UNIQUE,
    is_sleep_in BOOLEAN DEFAULT FALSE
);

-- =========================
-- 급식 (Meals)
-- =========================

-- 식사 타입
CREATE TABLE MealTypes (
    meal_type_id INTEGER PRIMARY KEY,
    type_name TEXT NOT NULL UNIQUE -- BREAKFAST, LUNCH, DINNER
);

-- 급식 시간 스케줄
CREATE TABLE MealSchedules (
    schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    meal_type_id INTEGER NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,

    UNIQUE (day_id, group_id, meal_type_id),

    FOREIGN KEY (day_id) REFERENCES Days(day_id),
    FOREIGN KEY (group_id) REFERENCES GradeGroups(group_id),
    FOREIGN KEY (meal_type_id) REFERENCES MealTypes(meal_type_id)
);

-- 실제 메뉴 (현재 유효한 메뉴)
CREATE TABLE Menus (
    menu_id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL UNIQUE,
    menu_content TEXT NOT NULL,

    FOREIGN KEY (schedule_id) REFERENCES MealSchedules(schedule_id)
);

-- =========================
-- 시간표 (Timetable)
-- =========================

-- 블록 정의 (A~F)
CREATE TABLE Blocks (
    block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_code TEXT NOT NULL UNIQUE
);

-- 하루 타임라인
CREATE TABLE DayTimeline (
    timeline_id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id INTEGER NOT NULL,

    item_type TEXT NOT NULL,
    -- BLOCK, COOKIE_BREAK, ADVISORY, TUTORIAL, ASSEMBLY

    block_id INTEGER, -- BLOCK일 때만 사용
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    item_order INTEGER NOT NULL,

    UNIQUE (day_id, item_order),

    FOREIGN KEY (day_id) REFERENCES Days(day_id),
    FOREIGN KEY (block_id) REFERENCES Blocks(block_id)
);

-- =========================
-- 기숙사 (Dormitory)
-- =========================

-- 기숙사 스케줄 (요일/학년그룹 단위)
CREATE TABLE DormSchedules (
    dorm_schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,

    UNIQUE (day_id, group_id),

    FOREIGN KEY (day_id) REFERENCES Days(day_id),
    FOREIGN KEY (group_id) REFERENCES GradeGroups(group_id)
);

-- 기숙사 규칙 종류
CREATE TABLE DormRuleTypes (
    rule_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name TEXT NOT NULL UNIQUE
    -- PREP, SIGN_IN, BEDTIME, FREE_TIME 등
);

-- 기숙사 세부 규칙 (시간/행동)
CREATE TABLE DormScheduleRules (
    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dorm_schedule_id INTEGER NOT NULL,
    rule_type_id INTEGER NOT NULL,

    rule_order INTEGER NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME,
    turn_in_phone BOOLEAN DEFAULT FALSE,

    UNIQUE (dorm_schedule_id, rule_type_id, rule_order),

    FOREIGN KEY (dorm_schedule_id) REFERENCES DormSchedules(dorm_schedule_id),
    FOREIGN KEY (rule_type_id) REFERENCES DormRuleTypes(rule_type_id)
);