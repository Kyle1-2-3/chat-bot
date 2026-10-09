from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
import httpx
import os
import sqlite3
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import calendar
import json
import logging
import re
import uuid
import urllib.parse
from contextlib import closing
from school_knowledge import search_school_knowledge
from school_calendar import calendar_result, leave_on
from school_events import upcoming_events as prioritize_upcoming_events
from answer_prompts import answer_system_for

load_dotenv()

# ---------------------------
# Settings
# ---------------------------
DEBUG = False
SERVER_TAG = ""
DB_PATH = os.path.join("db", "school.db")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TIMEOUT_MS = 15000  # cap each LLM call so a hung request can't tie up a worker
SCHOOL_TZ = ZoneInfo("America/Vancouver")

logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger("chatbot")

app = Flask(__name__, static_url_path="", static_folder="static")

def client_ip() -> str:
    """Rate-limit key. Behind nginx the socket peer is always localhost, so use
    X-Forwarded-For — its LAST entry (nginx appends the real client IP; earlier
    entries are client-supplied and spoofable)."""
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[-1].strip()
    return get_remote_address()

limiter = Limiter(client_ip, app=app, storage_uri="memory://")

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"reply": "You're sending messages a bit fast — give it a moment and try again 🙂"}), 429

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
)

# ---------------------------
# DB
# ---------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read query and return rows as dicts; closes the connection even on error."""
    with closing(get_db()) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

# ---------------------------
# Day helpers
# ---------------------------
DAYREF_MAP = {
    "MONDAY": 1, "TUESDAY": 2, "WEDNESDAY": 3, "THURSDAY": 4,
    "FRIDAY": 5, "SATURDAY": 6, "SUNDAY": 7
}

def today() -> date:
    """Current date, overridable via FAKE_TODAY (YYYY-MM-DD) for testing."""
    override = (os.getenv("FAKE_TODAY") or "").strip()
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()
    return datetime.now(SCHOOL_TZ).date()

def resolve_date(day_ref: str, user_msg: str = "") -> date:
    """Resolve a day_ref to an actual calendar date (blocks rotate, so dates matter)."""
    base = today()
    d = (day_ref or "").upper().strip()

    if d == "TODAY" or d == "ANY":
        return base
    if d == "TOMORROW":
        return base + timedelta(days=1)
    if d == "DAY_AFTER_TOMORROW":
        return base + timedelta(days=2)

    if d in DAYREF_MAP:
        target = DAYREF_MAP[d]  # 1=Mon .. 7=Sun
        delta = (target - base.isoweekday()) % 7
        return base + timedelta(days=delta)

    # fallback keyword search
    m = (user_msg or "").lower()
    for name, did in DAYREF_MAP.items():
        if name.lower() in m:
            delta = (did - base.isoweekday()) % 7
            return base + timedelta(days=delta)

    return base

def resolve_day_id(day_ref: str | None, user_msg: str = "") -> int:
    """Weekday id (1=Mon..7=Sun) for meals/sign-in — derived from the resolved date."""
    return resolve_date(day_ref or "", user_msg).isoweekday()

# Common afternoon rules are maintained separately from any student's iCal.
MYSCHOOL_URL = "https://brentwood.msm.io/saml/login"
PERSONAL_ACTIVITY_REPLY = (
    "Your arts and sports selections and exact schedule are individual. "
    f"Please check [MySchool]({MYSCHOOL_URL}) → My Schedule."
)
PERSONAL_SCHOOL_REPLY = (
    "Your assigned teachers, classes, house, advisor, and student records are personal. "
    f"Please check [MySchool]({MYSCHOOL_URL}) for your details."
)
ART_DAYS = (1, 3, 5)
SPORT_DAYS = (2, 4, 6)


def afternoon_rules(day_id: int | None = None) -> dict:
    """Return shared weekly rules, never a student's assigned activities."""
    art = {
        "kind": "ART", "label": "Art Day",
        "days": ["Monday", "Wednesday", "Friday"],
        "start_time": "14:00", "end_time": "18:00",
        "blocks": [
            {"block": n, "start_time": f"{13+n}:00", "end_time": f"{14+n}:00"}
            for n in range(1, 5)
        ],
        "arts_per_student_min": 2, "arts_per_student_max": 4,
    }
    sport = {
        "kind": "SPORT", "label": "Sport Day",
        "days": ["Tuesday", "Thursday", "Saturday"],
        "window_start": "14:00", "window_end": "18:00",
        "times_vary_by_sport": True,
    }
    patterns = [art, sport] if day_id is None else (
        [art] if day_id in ART_DAYS else [sport] if day_id in SPORT_DAYS else []
    )
    return {
        "patterns": patterns, "regular_weekly_pattern": True,
        "personal_schedule_url": MYSCHOOL_URL,
        "personal_schedule_instruction": PERSONAL_ACTIVITY_REPLY,
    }

# ---------------------------
# DB Fetchers
# ---------------------------
_MEAL_SELECT = """
    SELECT mt.type_name, gg.group_name, ms.start_time, ms.end_time,
           ms.requires_signin, m.menu_content
    FROM MealSchedules ms
    JOIN MealTypes mt ON ms.meal_type_id = mt.meal_type_id
    JOIN GradeGroups gg ON ms.group_id = gg.group_id
    LEFT JOIN Menus m ON m.schedule_id = ms.schedule_id
    WHERE ms.day_id = ?
"""
# meal_type_id is constant when filtering to one type, so this ORDER BY also
# yields the per-group ordering fetch_meal needs.
_MEAL_ORDER = " ORDER BY mt.meal_type_id, gg.group_id"

# School rule supplied by the project owner on 2026-09-27: Grade 12 has
# house sign-ins only. Shared Senior meal times/menus still apply.
MEAL_SIGNIN_EXEMPT_GRADES = {12}


def fetch_grade_rows(boarding_only: bool = False) -> list[dict]:
    """Each grade with its Junior/Senior group name; boarding_only drops Grade 8 (day students)."""
    return query("""
        SELECT g.grade_id, gg.group_name FROM Grades g
        JOIN GradeGroups gg ON gg.group_id = g.group_id
        WHERE g.grade_id >= ? ORDER BY g.grade_id
    """, (9 if boarding_only else 0,))


def apply_meal_grade_rules(rows: list[dict], grade: int | None = None) -> list[dict]:
    """Split a shared meal row only where grades have different sign-in rules."""
    grade_rows = fetch_grade_rows()
    result = []
    for row in rows:
        group_grades = [g["grade_id"] for g in grade_rows if g["group_name"] == row["group_name"]]
        relevant = [g for g in group_grades if grade is None or g == grade]
        by_requirement = {}
        for grade_id in relevant:
            required = int(bool(row["requires_signin"]) and grade_id not in MEAL_SIGNIN_EXEMPT_GRADES)
            by_requirement.setdefault(required, []).append(grade_id)
        for required, grades in by_requirement.items():
            label = row["group_name"] if grades == group_grades else "Grade " + ", ".join(map(str, grades))
            result.append({**row, "group_name": label, "grade_ids": grades, "requires_signin": required})
    return result


def fetch_meal(day_id: int, meal_type: str, grade: int | None = None) -> list[dict]:
    return apply_meal_grade_rules(query(
        _MEAL_SELECT + " AND UPPER(mt.type_name) = ?" + _MEAL_ORDER,
        (day_id, meal_type.upper()),
    ), grade)

def fetch_day_meals(day_id: int, grade: int | None = None) -> list[dict]:
    return apply_meal_grade_rules(query(_MEAL_SELECT + _MEAL_ORDER, (day_id,)), grade)

def fetch_dorm_signins(day_id: int, grade: int | None = None) -> list[dict]:
    rows = query("""
        SELECT gg.group_name, dsr.start_time, dsr.note, dsr.rule_order
        FROM DormScheduleRules dsr
        JOIN DormSchedules ds ON dsr.dorm_schedule_id = ds.dorm_schedule_id
        JOIN DormRuleTypes rt ON dsr.rule_type_id = rt.rule_type_id
        JOIN GradeGroups gg ON ds.group_id = gg.group_id
        WHERE ds.day_id = ? AND rt.type_name = 'SIGN_IN'
        ORDER BY gg.group_id, dsr.rule_order
    """, (day_id,))
    grade_rows = fetch_grade_rows(boarding_only=True)
    overrides = {(r["grade_id"], r["rule_order"]): r["start_time"] for r in query(
        "SELECT grade_id, rule_order, start_time FROM DormSigninOverrides WHERE day_id = ?", (day_id,))}
    result = []
    for row in rows:
        group_grades = [g["grade_id"] for g in grade_rows if g["group_name"] == row["group_name"]]
        relevant = [g for g in group_grades if grade is None or g == grade]
        by_time = {}
        for grade_id in relevant:
            start = overrides.get((grade_id, row["rule_order"]), row["start_time"])
            by_time.setdefault(start, []).append(grade_id)
        for start, grades in by_time.items():
            label = row["group_name"] if grades == group_grades else "Grade " + ", ".join(map(str, grades))
            result.append({**row, "group_name": label, "grade_ids": grades, "start_time": start})
    return result

def fetch_timeline_by_date(sched_date: str) -> list[dict]:
    return query("""
        SELECT item_type, block_code, start_time, end_time, item_order, event_name, all_day
        FROM ScheduleTimeline
        WHERE sched_date = ?
        ORDER BY item_order
    """, (sched_date,))

def fetch_next_event(item_type: str, from_date: str) -> list[dict]:
    """Nearest upcoming occurrence (on/after from_date) of a named timeline event."""
    return query("""
        SELECT sched_date, start_time, end_time
        FROM ScheduleTimeline
        WHERE item_type = ? AND sched_date >= ?
        ORDER BY sched_date, start_time
        LIMIT 1
    """, (item_type, from_date))


def fetch_upcoming_school_events(now: datetime, limit: int = 3) -> list[dict]:
    """Public highlights first, then common school events for the UI sidebar.

    Deliberately exclude EVENT rows: those can come from a student's personal
    calendar and do not belong in a globally visible interface.
    """
    rows = query("""
        SELECT sched_date, item_type, start_time, end_time
        FROM ScheduleTimeline
        WHERE sched_date BETWEEN ? AND ?
          AND item_type IN ('ASSEMBLY', 'TUTORIAL', 'ADVISORY')
        ORDER BY sched_date, start_time, item_order
    """, (now.date().isoformat(), (now.date() + timedelta(days=14)).isoformat()))
    labels = {"ASSEMBLY": "Assembly", "TUTORIAL": "Tutorial", "ADVISORY": "Advisory"}
    regular = [{"date": row["sched_date"], "title": labels[row["item_type"]],
                "start_time": row["start_time"], "end_time": row["end_time"]} for row in rows]
    return prioritize_upcoming_events(now, regular, limit)


def current_school_time():
    """Vancouver clock, retaining the existing FAKE_TODAY demo override."""
    return datetime.combine(today(), datetime.now(SCHOOL_TZ).time(), SCHOOL_TZ)

def fetch_grade_group(grade: int) -> str | None:
    rows = query("""
        SELECT gg.group_name
        FROM Grades g JOIN GradeGroups gg ON g.group_id = gg.group_id
        WHERE g.grade_id = ?
    """, (grade,))
    return rows[0]["group_name"] if rows else None

def fetch_bedtime(grade: int, day_id: int) -> dict:
    """has_rule distinguishes 'no bedtime' (row, bedtime NULL) from 'no data' (no row)."""
    rows = query("SELECT bedtime FROM Bedtimes WHERE grade_id = ? AND day_id = ?", (grade, day_id))
    if not rows:
        return {"has_rule": False, "bedtime": None}
    return {"has_rule": True, "bedtime": rows[0]["bedtime"]}

# ---------------------------
# LLM Classifier
# ---------------------------
MAX_REQUESTS = 5  # most intents we answer in one compound question

CLASSIFIER_SYSTEM = """
You are an intent classifier for a school chatbot.

Return ONLY valid JSON.
No markdown.
No explanations.

The user message may ask one thing or several things at once.
Output one request object per thing asked, in the order asked (max {MAX_REQUESTS}).

Schema:
{
  "requests": [
    {
      "intent": "GREETING" | "MEAL" | "MEALS_DAY" | "SCHEDULE" | "AFTERNOON" | "PERSONAL_ACTIVITY" | "PERSONAL_SCHOOL" | "SCHOOL_INFO" | "SCHOOL_BREAKS" | "MEAL_SIGNIN" | "SIGNIN_SUMMARY" | "GRADE_GROUP" | "BEDTIME" | "EVENT_SEARCH" | "LOCATION" | "UNKNOWN",
      "day_ref": "TODAY" | "TOMORROW" | "DAY_AFTER_TOMORROW" | "MONDAY" | "TUESDAY" | "WEDNESDAY" | "THURSDAY" | "FRIDAY" | "SATURDAY" | "SUNDAY" | "ANY",
      "meal_type": "BREAKFAST" | "LUNCH" | "DINNER" | "BRUNCH" | "AFTERNOON_SNACK" | null,
      "meal_focus": "MENU" | "TIMES" | "MENU_AND_TIMES",
      "schedule_focus": "ACADEMIC" | "FULL_DAY" | "SPECIFIC",
      "grade": <integer 8-12 or null>,
      "event_name": "ASSEMBLY" | "TUTORIAL" | "ADVISORY" | null,
      "school_query": <concise English topic for SCHOOL_INFO/SCHOOL_BREAKS, otherwise null>,
      "calendar_date": <YYYY-MM-DD for an explicit date in SCHEDULE/AFTERNOON, otherwise null>
    }
  ]
}

Rules for each request:
- Classify only what was actually asked; never add related questions or intents.
- Greeting/small talk only => GREETING
- School vacations, holidays, leave dates, midterm breaks, next break, days until
  a break, and returning to campus or resuming classes after a break => SCHOOL_BREAKS.
  Examples: "when is winter break", "다음 방학 언제야", "봄방학 며칠 남았어",
  "when do we come back", "all breaks this year", "summer holiday dates".
  Set school_query to the requested break, year and question, resolving recent
  follow-ups: after asking about winter break, "when do we come back" becomes
  "Winter Break return to campus and classes resume".
  Cookie break is a daily timetable item, NOT SCHOOL_BREAKS.
- For a schedule/afternoon on an explicit calendar date (e.g. "December 25",
  "10월 9일 시간표"), set calendar_date to YYYY-MM-DD. Use the current date
  provided below to resolve an omitted year to the next such date. Never turn
  an explicit date into a weekday-only query. Relative days use day_ref as usual.
- Public school facts about named staff, houseparents, facilities, services,
  support, courses, programs, admissions, or school life => SCHOOL_INFO.
  school_query must contain the specific entity and topic in English, resolving
  follow-ups from recent conversation, preserving names, and correcting typos.
  Examples: "who is rogers hiuse parent" => "Rogers houseparent";
  "로저스 사감 누구야" => "Rogers houseparent";
  "what does Mr Snow teach" => "Ken Snow teacher";
  "what is in the Foote Centre" => "Foote Centre facilities";
  "how do I get help with my laptop" => "Innovations IT repair support".
  "who teaches math" asks for public faculty, not an individual assignment.
- A student's assigned teacher, advisor, class/room/house, grades, reports,
  roommate, or enrolment => PERSONAL_SCHOOL. "Who is my math teacher?",
  "내 수학 선생님 누구야", "who is my advisor", "which house am I in" are
  PERSONAL_SCHOOL. Never infer personal assignments from public directories,
  schedules, or conversation history. "Who is my houseparent" without a named
  house is personal; "I'm in Rogers, who is my houseparent" is SCHOOL_INFO
  because it asks for the public role at an explicitly named house.
  "What about mine?" after a public teacher list becomes PERSONAL_SCHOOL.
  Personal art/sport assignments stay PERSONAL_ACTIVITY.
  Keep timetable/meal/sign-in/bedtime questions in their existing intents;
  website background descriptions must not override the live schedule.
- "today's meals", "what are meals today" => MEALS_DAY
- "what's for lunch friday" => MEAL
- For MEAL/MEALS_DAY, meal_focus is MENU by default. "What's for lunch?",
  "tomorrow's meals", "내일 점심 뭐야" ask only for food, not serving times or sign-in.
  "When is lunch?", "what time is dinner?", "점심 몇 시야" => meal_focus TIMES.
  "What's for lunch and when is it served?" => meal_focus MENU_AND_TIMES.
  Use MEALS_DAY for all meal times when no individual meal is specified.
  Sign-in is a separate MEAL_SIGNIN request ONLY if explicitly asked about it.
  Resolve follow-ups from context: "and tomorrow?" keeps the prior meal_focus;
  "what time?" after a menu question changes meal_focus to TIMES.
- "schedule for monday", "what blocks tomorrow" => SCHEDULE
- For SCHEDULE, block order/class timetable means schedule_focus ACADEMIC:
  academic blocks with times, breaks, Assembly/Advisory/Tutorial and special events.
  It does NOT ask for afternoon arts/sports. A general whole-day schedule is
  FULL_DAY. A particular block, event or break question is SPECIFIC.
  Follow-ups such as "and tomorrow?" keep the previous schedule_focus.
- General afternoon rules, art/sport days, the common ART blocks 1–4 or the
  general number of arts per student => AFTERNOON. Examples: "afternoon schedule
  Monday", "is tomorrow art or sport day", "when is art block 2", "how many
  arts do students have", "월요일 오후 일정", "아트 블록 4 몇 시야".
  Use day_ref=ANY for the general weekly pattern when no day is specified.
  Numbered art blocks 1–4 are NOT academic letter blocks A–F.
- Personal arts/sports choices, assigned blocks, or the time of a particular
  student's art or a named sport/activity => PERSONAL_ACTIVITY. Examples:
  "what art do I have", "when is my art", "which art block am I in", "my sport
  time", "when is rugby", "what time is robotics", "내 아트 뭐야", "내 스포츠
  몇 시야". Never infer a personal assignment from the shared calendar or memory.
  "What time is art block 2" is a general fixed-slot question => AFTERNOON;
  "do I have art block 2" is about an assignment => PERSONAL_ACTIVITY.
  A follow-up such as "what about mine" after a general art/sport question
  becomes PERSONAL_ACTIVITY. Treat "sprot" as "sport".
- "special events tomorrow", "any events today", "내일 특별 행사" => SCHEDULE
  with the requested day_ref; special events are included in the date's timeline.
- A block and the cookie break are daily timeline items. A question about WHEN
  one happens on a given day — "when is the D block today", "when is the cookie
  break today", "cookie break time tomorrow" => SCHEDULE for that day (day_ref
  from the day mentioned, default TODAY). The whole day's timeline is returned
  and the specific item is read from it. (This is NOT EVENT_SEARCH; EVENT_SEARCH
  is only for assembly/tutorial/advisory when no day is given.)
- If user asks whether a specific meal or meals in general require sign-in,
  classify as MEAL_SIGNIN. Leave meal_type null for meals in general.
- For MEAL, MEALS_DAY, MEAL_SIGNIN and SIGNIN_SUMMARY, extract the stated grade
  (including "gr12", "grade 12", "12학년") and carry it over from recent
  conversation when referring to that student. Never infer grade from Senior.
  "I'm gr12, do I sign in for dinner?" => MEAL_SIGNIN, grade=12, meal_type=DINNER.
- If user asks general sign-in time, dorm sign-in, curfew, residence sign-in, or
  "sign in time for saturday", classify as SIGNIN_SUMMARY. Extract the stated
  grade into grade (including a grade established in recent conversation).
  "grade 12 Saturday sign in" => SIGNIN_SUMMARY, grade=12, day_ref=SATURDAY.
- If user asks whether a grade is Junior or Senior, or which group a grade is in
  (e.g. "I'm grade 11, am I junior or senior?"), classify as GRADE_GROUP and put
  the grade number in "grade" (null if no grade is stated)
- If user asks about bedtime / lights-out / what time they go to bed, classify as
  BEDTIME; put the grade in "grade" (null if not stated) and the day in day_ref
  (bedtime varies by grade and day)
- If the user names a school event (Assembly, Tutorial, Advisory) and asks WHEN it
  happens — "when is assembly", "what day is tutorial", "what time is advisory",
  "조회 언제야", "튜토리얼 무슨 요일" — classify as EVENT_SEARCH and put the event in
  "event_name" (ASSEMBLY / TUTORIAL / ADVISORY). This is a reverse lookup: the user
  gives the event and wants its date/day/time. (A request for a whole day's schedule
  stays SCHEDULE.)
- If the user asks WHERE a building or place on campus is, or how to find/get to
  one — "where is Crooks Hall", "how do I get to the gym", "크룩스홀 어디야" —
  classify as LOCATION. (Asking WHEN something happens is NOT LOCATION.)
- If the request is unclear => UNKNOWN
- Use meal_type only when relevant
- Use day_ref=ANY if no day is specified
- "tmr" means tomorrow; "the day after tmr/tomorrow" => DAY_AFTER_TOMORROW
- If [Recent conversation] is given, use it to resolve follow-ups: a vague
  message like "what about tomorrow" or "and dinner?" carries over the
  previous intent and meal_type, changing only what the user newly specified.
- Compound example: "block order tmr and breakfast the day after tmr"
  => requests: [ {intent SCHEDULE, day_ref TOMORROW}, {intent MEAL, meal_type BREAKFAST, day_ref DAY_AFTER_TOMORROW} ]
""".replace("{MAX_REQUESTS}", str(MAX_REQUESTS))

UNKNOWN_REQUEST = {
    "intent": "UNKNOWN",
    "day_ref": "ANY",
    "meal_type": None,
    "grade": None,
    "event_name": None,
}

VALID_INTENTS = {
    "GREETING", "MEAL", "MEALS_DAY", "SCHEDULE", "AFTERNOON", "PERSONAL_ACTIVITY",
    "PERSONAL_SCHOOL", "SCHOOL_INFO", "SCHOOL_BREAKS",
    "MEAL_SIGNIN", "SIGNIN_SUMMARY", "GRADE_GROUP", "BEDTIME",
    "EVENT_SEARCH", "LOCATION", "UNKNOWN"
}
VALID_EVENTS = {"ASSEMBLY", "TUTORIAL", "ADVISORY"}
VALID_DAYS = {
    "TODAY", "TOMORROW", "DAY_AFTER_TOMORROW", "MONDAY", "TUESDAY",
    "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY", "ANY"
}
VALID_MEALS = {"BREAKFAST", "LUNCH", "DINNER", "BRUNCH", "AFTERNOON_SNACK"}

def validate_request(obj: dict) -> dict:
    intent = str(obj.get("intent", "UNKNOWN")).upper()
    day_ref = str(obj.get("day_ref", "ANY")).upper()
    meal_type = obj.get("meal_type", None)

    if isinstance(meal_type, str):
        meal_type = meal_type.upper()

    grade = obj.get("grade")
    if not isinstance(grade, int) or isinstance(grade, bool):
        grade = None

    event_name = obj.get("event_name")
    if isinstance(event_name, str):
        event_name = event_name.upper()

    if intent not in VALID_INTENTS:
        intent = "UNKNOWN"
    if day_ref not in VALID_DAYS:
        day_ref = "ANY"
    if meal_type is not None and meal_type not in VALID_MEALS:
        meal_type = None
    if event_name not in VALID_EVENTS:
        event_name = None

    validated = {
        "intent": intent,
        "day_ref": day_ref,
        "meal_type": meal_type,
        "grade": grade,
        "event_name": event_name,
    }
    if intent in {"MEAL", "MEALS_DAY"}:
        focus = str(obj.get("meal_focus", "MENU")).upper()
        validated["meal_focus"] = focus if focus in {"MENU", "TIMES", "MENU_AND_TIMES"} else "MENU"
    if intent == "SCHEDULE":
        focus = str(obj.get("schedule_focus", "ACADEMIC")).upper()
        validated["schedule_focus"] = focus if focus in {"ACADEMIC", "FULL_DAY", "SPECIFIC"} else "ACADEMIC"
    if intent in {"SCHOOL_INFO", "SCHOOL_BREAKS"}:
        school_query = obj.get("school_query")
        validated["school_query"] = school_query.strip()[:240] if isinstance(school_query, str) else ""
    if intent in {"SCHEDULE", "AFTERNOON"} and obj.get("calendar_date"):
        try:
            validated["calendar_date"] = date.fromisoformat(obj["calendar_date"]).isoformat()
        except (TypeError, ValueError):
            pass
    return validated

# ---------------------------
# Deterministic fast path for the home-page prompts
# ---------------------------
# The Gemini classifier handles everything, but the quick-action cards and
# chips send a small fixed set of phrasings ("What's the block order today?",
# "What's for lunch tomorrow?", "meal tmr"). Recognising those locally means
# they never depend on an LLM round-trip (or fall to the UNKNOWN fallback when
# that call fails). Simple menus and academic timetables need no answer call either.
# Anything with an
# unrecognised word — grades, "and", Korean, follow-ups — goes to the LLM.
_FAST_DAY_WORDS = {
    "today": "TODAY", "todays": "TODAY", "tonight": "TODAY",
    "tomorrow": "TOMORROW", "tomorrows": "TOMORROW", "tmr": "TOMORROW",
    "tmrw": "TOMORROW", "tmw": "TOMORROW", "tomorow": "TOMORROW", "tommorow": "TOMORROW",
    "monday": "MONDAY", "mon": "MONDAY", "tuesday": "TUESDAY", "tue": "TUESDAY", "tues": "TUESDAY",
    "wednesday": "WEDNESDAY", "wed": "WEDNESDAY", "thursday": "THURSDAY", "thu": "THURSDAY",
    "thurs": "THURSDAY", "friday": "FRIDAY", "fri": "FRIDAY", "saturday": "SATURDAY",
    "sat": "SATURDAY", "sunday": "SUNDAY", "sun": "SUNDAY",
}
_FAST_FILLER = {
    "what", "whats", "is", "are", "the", "a", "an", "do", "we", "i", "have", "for", "our",
    "my", "on", "this", "show", "me", "tell", "give", "please", "pls", "hey", "hi", "hello",
    "can", "you", "u", "happening", "going", "with", "be", "there", "at", "in", "school",
    "s", "whole", "full", "up", "got", "get", "gonna", "will", "it", "of",
}
_FAST_BLOCK_WORDS = {"block", "blocks", "order", "schedule", "timetable", "class", "classes"}
_FAST_BLOCK_CORE = {"block", "blocks", "timetable", "schedule"}
_FAST_MEAL_TYPES = {"breakfast": "BREAKFAST", "lunch": "LUNCH", "dinner": "DINNER", "brunch": "BRUNCH"}
_FAST_MEALS_DAY = {"meal", "meals", "food", "menu", "menus", "eating", "eat"}

def quick_classify(user_msg: str) -> list[dict] | None:
    """Rule-based intent for simple block-order / meal questions; None otherwise."""
    text = (user_msg or "").lower().replace("\u2019", "'").replace("'", "")
    tokens = re.findall(r"[a-z]+", text)
    if not tokens or len(tokens) > 12 or re.search(r"[^\x00-\x7f]|\d", text):
        return None

    day_refs = [_FAST_DAY_WORDS[t] for t in tokens if t in _FAST_DAY_WORDS]
    if len(day_refs) > 1:
        return None
    day_ref = day_refs[0] if day_refs else "ANY"
    words = [t for t in tokens if t not in _FAST_DAY_WORDS and t not in _FAST_FILLER]
    if not words:
        return None
    wordset = set(words)

    if wordset <= _FAST_BLOCK_WORDS and wordset & _FAST_BLOCK_CORE:
        focus = "ACADEMIC" if wordset & {"block", "blocks", "timetable", "class", "classes"} else "FULL_DAY"
        return [validate_request({"intent": "SCHEDULE", "day_ref": day_ref, "schedule_focus": focus})]

    meal_types = [_FAST_MEAL_TYPES[w] for w in words if w in _FAST_MEAL_TYPES]
    if wordset <= (set(_FAST_MEAL_TYPES) | _FAST_MEALS_DAY) and len(set(meal_types)) <= 1:
        if meal_types:
            return [validate_request({"intent": "MEAL", "day_ref": day_ref, "meal_type": meal_types[0]})]
        return [validate_request({"intent": "MEALS_DAY", "day_ref": day_ref})]
    return None

def classify_query(user_msg: str, memory: str = "") -> list[dict]:
    if not user_msg or not user_msg.strip():
        return [dict(UNKNOWN_REQUEST)]

    fast = quick_classify(user_msg)
    if fast:
        logger.debug("classify_query: fast path -> %s", fast)
        return fast

    memory = (memory or "").strip()[-1500:]  # keep the newest turns
    context = f"[Recent conversation]\n{memory}\n\n" if memory else ""
    prompt = f"Current school date: {today().isoformat()}\n{context}[User Message]\n{user_msg}\n\nReturn JSON only."
    try:
        r = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=CLASSIFIER_SYSTEM,
                temperature=0.0,
            ),
        )

        txt = (r.text or "").strip()
        if txt.startswith("```"):
            txt = txt.strip("`").replace("json", "", 1).strip()

        try:
            obj = json.loads(txt)
        except json.JSONDecodeError:
            logger.error("classify_query: Gemini returned unparseable JSON: %.200s", txt)
            return [dict(UNKNOWN_REQUEST)]

        # accept {"requests": [...]}, a bare JSON array, or a single object
        if isinstance(obj, list):
            raw_requests = obj
        elif isinstance(obj, dict):
            raw_requests = obj.get("requests", [obj])
        else:
            raw_requests = []
        if not isinstance(raw_requests, list):
            raw_requests = [raw_requests]

        requests_out = [
            validate_request(item)
            for item in raw_requests[:MAX_REQUESTS]
            if isinstance(item, dict)
        ]
        return requests_out or [dict(UNKNOWN_REQUEST)]

    except httpx.TimeoutException:
        logger.error("classify_query: Gemini call timed out after %sms", GEMINI_TIMEOUT_MS)
        return [dict(UNKNOWN_REQUEST)]
    except genai_errors.APIError as e:
        logger.error("classify_query: Gemini API error %s: %s", e.code, e.message)
        return [dict(UNKNOWN_REQUEST)]
    except Exception:
        logger.exception("classify_query failed")
        return [dict(UNKNOWN_REQUEST)]

# ---------------------------
# Build grounded result
# ---------------------------
def menu_search_items(menu_content: str | None) -> list[dict]:
    """Split a menu into its individual dishes, each paired with a Google image
    search link. Menu names like "Banh Mi Vietnamese Pork Roll ..." mean little
    on their own, so the link lets a student see what the dish actually looks
    like. One dish per line; blank lines (e.g. the gap between Sunday brunch
    halves) are dropped."""
    items = []
    for line in (menu_content or "").splitlines():
        name = line.strip()
        if not name:
            continue
        url = "https://www.google.com/search?tbm=isch&q=" + urllib.parse.quote_plus(name)
        items.append({"name": name, "search_url": url})
    return items


def attach_menu_links(rows: list[dict]) -> list[dict]:
    """Add a "menu_items" link list to each meal row (in place) and return rows."""
    for r in rows:
        r["menu_items"] = menu_search_items(r.get("menu_content"))
    return rows


def build_result_from_classification(cls: dict, user_msg: str) -> dict:
    intent = cls.get("intent", "UNKNOWN")
    day_ref = cls.get("day_ref", "ANY")
    meal_type = cls.get("meal_type")
    grade = cls.get("grade")

    if intent == "LOCATION":
        return {"type": "LOCATION"}

    if intent == "PERSONAL_ACTIVITY":
        return {"type": "PERSONAL_ACTIVITY", "reply": PERSONAL_ACTIVITY_REPLY}

    if intent == "PERSONAL_SCHOOL":
        return {"type": "PERSONAL_SCHOOL", "reply": PERSONAL_SCHOOL_REPLY}

    if intent == "SCHOOL_INFO":
        return {
            "type": "SCHOOL_INFO",
            "records": search_school_knowledge(cls.get("school_query") or user_msg),
        }

    if intent == "SCHOOL_BREAKS":
        return {"type": "SCHOOL_BREAKS", "requested_topic": cls.get("school_query") or user_msg,
                **calendar_result(today())}

    if intent == "AFTERNOON":
        if day_ref == "ANY" and not cls.get("calendar_date"):
            return {"type": "AFTERNOON", **afternoon_rules()}
        sched_date = date.fromisoformat(cls["calendar_date"]) if cls.get("calendar_date") else resolve_date(day_ref, user_msg)
        leave = leave_on(sched_date)
        rules = afternoon_rules(sched_date.isoweekday())
        if leave:
            rules["patterns"] = []
        return {
            "type": "AFTERNOON", "date": sched_date.isoformat(),
            "day_name": calendar.day_name[sched_date.weekday()],
            **rules, "school_leave": leave,
        }

    day_id = resolve_day_id(day_ref, user_msg)
    day_name = calendar.day_name[day_id - 1]

    if intent == "MEAL":
        rows = attach_menu_links(fetch_meal(day_id, meal_type, grade)) if meal_type else []
        return {
            "type": "MEAL",
            "grade": grade,
            "day_id": day_id,
            "day_name": day_name,
            "meal_type": meal_type,
            "rows": rows
        }

    if intent == "MEALS_DAY":
        rows = attach_menu_links(fetch_day_meals(day_id, grade))
        return {
            "type": "MEALS_DAY",
            "grade": grade,
            "day_id": day_id,
            "day_name": day_name,
            "rows": rows
        }

    if intent == "SCHEDULE":
        sched_date = date.fromisoformat(cls["calendar_date"]) if cls.get("calendar_date") else resolve_date(day_ref, user_msg)
        rows = fetch_timeline_by_date(sched_date.isoformat())
        leave = leave_on(sched_date)
        afternoon = afternoon_rules(sched_date.isoweekday())
        if leave:
            afternoon["patterns"] = []
            if leave["full_day"]:
                rows = [r for r in rows if r["item_type"] == "EVENT"]
        return {
            "type": "SCHEDULE",
            "date": sched_date.isoformat(),
            "day_name": calendar.day_name[sched_date.weekday()],
            "rows": rows,
            "afternoon": afternoon, "school_leave": leave,
        }

    if intent == "MEAL_SIGNIN":
        rows = fetch_meal(day_id, meal_type, grade) if meal_type else fetch_day_meals(day_id, grade)
        return {
            "type": "MEAL_SIGNIN",
            "grade": grade,
            "meal_signin_exempt_grades": sorted(MEAL_SIGNIN_EXEMPT_GRADES),
            "day_id": day_id,
            "day_name": day_name,
            "meal_type": meal_type,
            "rows": rows
        }

    if intent == "GRADE_GROUP":
        grade = cls.get("grade")
        return {
            "type": "GRADE_GROUP",
            "grade": grade,
            "group_name": fetch_grade_group(grade) if grade is not None else None,
        }

    if intent == "BEDTIME":
        grade = cls.get("grade")
        sched_date = resolve_date(day_ref, user_msg)
        info = fetch_bedtime(grade, sched_date.isoweekday()) if grade is not None \
            else {"has_rule": False, "bedtime": None}
        return {
            "type": "BEDTIME",
            "grade": grade,
            "day_name": calendar.day_name[sched_date.weekday()],
            "bedtime": info["bedtime"],
            "has_rule": info["has_rule"],
        }

    if intent == "EVENT_SEARCH":
        event_name = cls.get("event_name")
        raw = fetch_next_event(event_name, today().isoformat()) if event_name else []
        rows = [{
            "date": r["sched_date"],
            "day_name": calendar.day_name[date.fromisoformat(r["sched_date"]).weekday()],
            "start_time": r["start_time"],
            "end_time": r["end_time"],
        } for r in raw]
        return {
            "type": "EVENT_SEARCH",
            "event_name": event_name,
            "rows": rows,
        }

    if intent == "SIGNIN_SUMMARY":
        grade = cls.get("grade")
        dorm_rows = fetch_dorm_signins(day_id, grade)
        meals = fetch_day_meals(day_id, grade)
        meals_requiring = [r for r in meals if int(r.get("requires_signin") or 0) == 1]
        return {
            "type": "SIGNIN_SUMMARY",
            "grade": grade,
            "meal_signin_exempt_grades": sorted(MEAL_SIGNIN_EXEMPT_GRADES),
            "day_id": day_id,
            "day_name": day_name,
            "dorm_signins": dorm_rows,
            "meal_signins": meals_requiring
        }

    return {
        "type": "UNKNOWN",
        "day_id": day_id,
        "day_name": day_name
    }

# ---------------------------
# Answer generator
# ---------------------------
# Answer rules are selected by intent in answer_prompts.py.

# Dev cheat-code: a message containing this phrase skips the school pipeline
# entirely and talks to Gemini directly (no classifier, no school system
# prompt) — like chatting with plain Gemini. The phrase lives only in the
# server's private .env (DEV_TRIGGER=...); leave it unset to disable the cheat.
DEV_TRIGGER = (os.getenv("DEV_TRIGGER") or "").strip()

# Raw chat keeps a larger window than the school pipeline (~10 Q&A pairs) so the
# dev can hold a real back-and-forth instead of a one-shot question.
RAW_MEMORY_CHARS = 8000

# Raw chat has no school system prompt, but it must still answer in Korean.
RAW_LANG_INSTRUCTION = "[Instruction] Respond in Korean only, regardless of the user's language.\n\n"

def generate_raw_answer(user_msg: str, memory: str = "") -> str:
    memory = (memory or "").strip()[-RAW_MEMORY_CHARS:]  # keep the newest turns
    context = f"[Recent conversation]\n{memory}\n\n" if memory else ""
    try:
        r = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"{RAW_LANG_INSTRUCTION}{context}{user_msg}",
        )
        return (r.text or "").strip()
    except httpx.TimeoutException:
        logger.error("generate_raw_answer: Gemini call timed out after %sms", GEMINI_TIMEOUT_MS)
    except genai_errors.APIError as e:
        logger.error("generate_raw_answer: Gemini API error %s: %s", e.code, e.message)
    except Exception:
        logger.exception("generate_raw_answer failed")
    return "Sorry — something went wrong on my end. Please try again in a moment 🙂"

# Pure where-is questions need no data and no LLM phrasing — answer statically
# and skip the second Gemini call. Mixed messages still go through the LLM
# (the "For LOCATION" rule above covers them).
LOCATION_REPLY = (
    "Every building is on the campus map 🙂 Open it with the Campus button "
    "(left sidebar on desktop, menu on mobile) and search the "
    "building name there."
)

def focused_answer_results(classifications: list[dict], results: list[dict]) -> list[dict]:
    """Keep unrequested details out of both answer data and selected rules."""
    focused = []
    for index, original in enumerate(results):
        result = dict(original)
        intent = result.get("type")
        cls = classifications[index] if index < len(classifications) else {}
        if intent in {"MEAL", "MEALS_DAY"}:
            focus = validate_request({**cls, "intent": intent})["meal_focus"]
            result["meal_focus"] = focus
            allowed = {"type_name", "group_name", "grade_ids"}
            if focus != "TIMES":
                allowed |= {"menu_content", "menu_items"}
            if focus != "MENU":
                allowed |= {"start_time", "end_time"}
            result["rows"] = [{k: v for k, v in row.items() if k in allowed}
                              for row in result.get("rows", [])]
        elif intent == "MEAL_SIGNIN":
            result["rows"] = [{k: v for k, v in row.items()
                               if k not in {"menu_content", "menu_items"}}
                              for row in result.get("rows", [])]
        elif intent == "SIGNIN_SUMMARY":
            result["meal_signins"] = [{k: v for k, v in row.items()
                                       if k not in {"menu_content", "menu_items"}}
                                      for row in result.get("meal_signins", [])]
        elif intent == "SCHEDULE":
            focus = validate_request({**cls, "intent": intent})["schedule_focus"]
            result["schedule_focus"] = focus
            if focus != "FULL_DAY":
                result.pop("afternoon", None)
        focused.append(result)
    return focused


def render_menu_answer(results: list[dict]) -> str:
    """A menu lookup needs no generated prose, serving times or sign-in advice."""
    def escape(value):
        return re.sub(r"([\\`*_\[\]<>])", r"\\\1", str(value))

    sections = []
    for result in results:
        meals = {}
        for row in result.get("rows", []):
            meal = row.get("type_name") or result.get("meal_type") or "Meal"
            items = row.get("menu_items") or menu_search_items(row.get("menu_content"))
            key = tuple((item["name"], item["search_url"]) for item in items)
            groups = meals.setdefault(meal, {}).setdefault(key, set())
            if row.get("grade_ids"):
                groups.add("Grade " + ", ".join(map(str, row["grade_ids"])))
            elif row.get("group_name"):
                groups.add(row["group_name"])
        if not meals:
            meal = (result.get("meal_type") or "meals").replace("_", " ").lower()
            sections.append(f"I don't have the {meal} menu for {result['day_name']} yet.")
            continue
        lines = [f"Here's what's on the menu for **{result['day_name']}**:", ""]
        for meal, menus in meals.items():
            for items, groups in menus.items():
                label = escape(meal.replace("_", " ").title())
                if len(menus) > 1 and groups:
                    label += " (" + escape(" / ".join(sorted(groups))) + ")"
                dishes = "; ".join(f"[{escape(name)}]({url})" for name, url in items)
                lines.append(f"- **{label}:** {dishes or 'Menu unavailable.'}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def render_academic_timetable(result: dict) -> str:
    """Format verified common-school rows without an answer-model round trip."""
    def clock(value):
        if not value:
            return ""
        parsed = datetime.strptime(value, "%H:%M")
        return parsed.strftime("%I:%M %p").lstrip("0")

    def line(row, label):
        label = re.sub(r"([\\`*_\[\]<>])", r"\\\1", str(label))
        start, end = clock(row.get("start_time")), clock(row.get("end_time"))
        when = "All day" if row.get("all_day") else " – ".join(t for t in (start, end) if t)
        return f"- **{label}:** {when or 'Time not listed'}"

    labels = {"COOKIE_BREAK": "Cookie Break", "ASSEMBLY": "Assembly",
              "ADVISORY": "Advisory", "TUTORIAL": "Tutorial", "INSPECTION": "Inspection"}
    classes, events = [], []
    for row in result.get("rows", []):
        kind = row["item_type"]
        if kind == "EVENT":
            events.append(line(row, row.get("event_name") or "Event"))
        else:
            label = f"Block {row['block_code']}" if kind == "BLOCK" else labels[kind]
            classes.append(line(row, label))
    day = result["day_name"]
    text = (f"Here's the class timetable for **{day}**:\n\n" + "\n".join(classes)
            if classes else f"I don't have the class timetable for {day} yet.")
    if events:
        text += "\n\n**Events**\n" + "\n".join(events)
    return text


def generate_answer(user_msg: str, classifications: list[dict], results: list[dict]) -> str:
    results = focused_answer_results(classifications, results)
    if results and all(r["type"] in {"MEAL", "MEALS_DAY"}
                       and r["meal_focus"] == "MENU" for r in results):
        return render_menu_answer(results)
    fast = quick_classify(user_msg)
    if (len(results) == 1 and fast and fast[0].get("schedule_focus") == "ACADEMIC"
            and results[0].get("type") == "SCHEDULE"
            and results[0].get("schedule_focus") == "ACADEMIC"
            and not results[0].get("school_leave")):
        try:
            return render_academic_timetable(results[0])
        except (KeyError, TypeError, ValueError):
            # New row types or unusual time formats retain the grounded model path.
            logger.info("Timetable requires model formatting")
    # Day reflects today() (so FAKE_TODAY works); time-of-day stays real-clock.
    server_day_name = calendar.day_name[today().isoweekday() - 1]
    server_time = datetime.now(SCHOOL_TZ).strftime("%H:%M")

    payload = {
        "server_time": f"{server_day_name} {server_time}",
        "user_message": user_msg,
        "classifications": classifications,
        "results": results,
    }

    try:
        r = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=json.dumps(payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=answer_system_for(results),
                temperature=0.2,
            ),
        )
        return (r.text or "").strip()
    except httpx.TimeoutException:
        logger.error("generate_answer: Gemini call timed out after %sms", GEMINI_TIMEOUT_MS)
    except genai_errors.APIError as e:
        logger.error("generate_answer: Gemini API error %s: %s", e.code, e.message)
    except Exception:
        logger.exception("generate_answer failed")
    return "Sorry — something went wrong on my end. Please try again in a moment 🙂"

# ---------------------------
# Routes
# ---------------------------
def chat_events(user_msg: str, memory: str, req_id: str):
    """The same answer pipeline for JSON and progress-stream clients.

    Status events describe real work, never generated reasoning or fake searches.
    The browser decides when to reveal them; there are no sleeps on the server.
    """
    logger.debug("[%s] USER: %s", req_id, user_msg)

    if DEV_TRIGGER and DEV_TRIGGER in user_msg:
        logger.info("[%s] dev trigger: raw Gemini chat", req_id)
        raw_msg = user_msg.replace(DEV_TRIGGER, " ").strip() or "Hi!"
        yield "status", {"stage": "writing"}
        yield "reply", {"reply": generate_raw_answer(raw_msg, memory)}
        return

    yield "status", {"stage": "understanding"}
    classifications = classify_query(user_msg, memory)

    logger.debug("[%s] CLASSIFICATIONS: %s", req_id, classifications)

    # INFO so prod logs show the intent mix — UNKNOWN rate tells us what to add next.
    intents = [c.get("intent", "UNKNOWN") for c in classifications]
    logger.info("[%s] intents: %s", req_id, ",".join(intents))
    if "UNKNOWN" in intents:
        logger.info("[%s] UNKNOWN query: %s", req_id, user_msg)

    actionable = [c for c in classifications if c.get("intent") not in ("UNKNOWN", "GREETING")]

    if not actionable:
        if any(c.get("intent") == "GREETING" for c in classifications):
            yield "status", {"stage": "writing"}
            reply = generate_answer(user_msg, classifications, [{"type": "GREETING"}])
            if SERVER_TAG:
                reply = f"{SERVER_TAG} {reply}"
            yield "reply", {"reply": reply}
            return

        friendly = "Hey 🙂 I’m not fully sure what you want. You can ask about meals, schedules, sign-in times, school staff, facilities, or student services."
        if SERVER_TAG:
            friendly = f"{SERVER_TAG} {friendly}"
        yield "reply", {"reply": friendly}
        return

    yield "status", {"stage": "checking"}
    try:
        results = [build_result_from_classification(c, user_msg) for c in actionable]
    except Exception:
        logger.exception("[%s] build_result failed", req_id)
        yield "error", {"reply": "Sorry — I had trouble reading the school data."}
        return

    logger.debug("[%s] RESULTS: %s", req_id, results)

    yield "status", {"stage": "writing"}
    if all(r["type"] == "LOCATION" for r in results):
        reply = LOCATION_REPLY
    elif all(r["type"] == "PERSONAL_ACTIVITY" for r in results):
        reply = PERSONAL_ACTIVITY_REPLY
    elif all(r["type"] == "PERSONAL_SCHOOL" for r in results):
        reply = PERSONAL_SCHOOL_REPLY
    else:
        reply = generate_answer(user_msg, actionable, results)

    if SERVER_TAG:
        reply = f"{SERVER_TAG} {reply}"

    yield "reply", {"reply": reply}


@app.route("/chat", methods=["POST"])
@limiter.limit("10 per minute; 300 per day")
def chat():
    req_id = str(uuid.uuid4())[:8]
    data = request.get_json(silent=True) or {}
    # A non-object body or non-string fields is a client bug: answer 400, not a 500 trace.
    user_msg = (data.get("message") or "") if isinstance(data, dict) else None
    memory = (data.get("memory") or "") if isinstance(data, dict) else None
    if not isinstance(user_msg, str) or not isinstance(memory, str):
        return jsonify({"reply": "That message didn't come through properly — please try again."}), 400
    user_msg = user_msg.strip()

    if len(user_msg) > 500:
        return jsonify({"reply": "That message is a bit long — could you shorten it?"}), 400

    events = chat_events(user_msg, memory, req_id)
    if request.accept_mimetypes.best == "text/event-stream":
        def stream():
            try:
                for event, payload in events:
                    yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception:
                logger.exception("[%s] chat stream failed", req_id)
                yield 'event: error\ndata: {"reply":"Sorry — something went wrong. Please try again."}\n\n'
            finally:
                events.close()

        return Response(stream_with_context(stream()), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        })

    for event, payload in events:
        if event == "reply":
            return jsonify(payload)
        if event == "error":
            return jsonify(payload), 500

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/upcoming-events")
@app.route("/api/upcoming-events")
def upcoming_events():
    """Read-only public school-calendar highlights for the sidebar."""
    try:
        rows = fetch_upcoming_school_events(current_school_time())
    except Exception:
        logger.exception("Could not load upcoming school events")
        return jsonify({"events": []}), 500

    return jsonify({"events": rows})

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
