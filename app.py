from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from google import genai
from google.genai import types
import os
import sqlite3
from datetime import datetime, date, timedelta
import calendar
import json
import uuid

load_dotenv()

app = Flask(__name__, static_url_path="", static_folder="static")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ---------------------------
# Settings
# ---------------------------
DEBUG = False
SERVER_TAG = ""
DB_PATH = os.path.join("db", "school.db")

# ---------------------------
# DB
# ---------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
    return datetime.now().date()

def get_server_day_id() -> int:
    return today().isoweekday()

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
    today = get_server_day_id()
    d = (day_ref or "").upper().strip()

    if d in DAYREF_MAP:
        return DAYREF_MAP[d]
    if d == "TODAY":
        return today
    if d == "TOMORROW":
        return 1 if today == 7 else today + 1
    if d == "DAY_AFTER_TOMORROW":
        return ((today - 1 + 2) % 7) + 1

    # fallback keyword search
    m = (user_msg or "").lower()
    fallback_days = {
        "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
        "friday": 5, "saturday": 6, "sunday": 7
    }
    for name, did in fallback_days.items():
        if name in m:
            return did

    return today

# ---------------------------
# DB Fetchers
# ---------------------------
def fetch_meal(day_id: int, meal_type: str) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT mt.type_name, gg.group_name, ms.start_time, ms.end_time,
               ms.requires_signin, m.menu_content
        FROM MealSchedules ms
        JOIN MealTypes mt ON ms.meal_type_id = mt.meal_type_id
        JOIN GradeGroups gg ON ms.group_id = gg.group_id
        LEFT JOIN Menus m ON m.schedule_id = ms.schedule_id
        WHERE ms.day_id = ? AND UPPER(mt.type_name) = ?
        ORDER BY gg.group_id
    """, (day_id, meal_type.upper()))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def fetch_day_meals(day_id: int) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT mt.type_name, gg.group_name, ms.start_time, ms.end_time,
               ms.requires_signin, m.menu_content
        FROM MealSchedules ms
        JOIN MealTypes mt ON ms.meal_type_id = mt.meal_type_id
        JOIN GradeGroups gg ON ms.group_id = gg.group_id
        LEFT JOIN Menus m ON m.schedule_id = ms.schedule_id
        WHERE ms.day_id = ?
        ORDER BY mt.meal_type_id, gg.group_id
    """, (day_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def fetch_dorm_signins(day_id: int) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT gg.group_name, dsr.start_time, dsr.rule_order
        FROM DormScheduleRules dsr
        JOIN DormSchedules ds ON dsr.dorm_schedule_id = ds.dorm_schedule_id
        JOIN DormRuleTypes rt ON dsr.rule_type_id = rt.rule_type_id
        JOIN GradeGroups gg ON ds.group_id = gg.group_id
        WHERE ds.day_id = ? AND rt.type_name = 'SIGN_IN'
        ORDER BY gg.group_id, dsr.rule_order
    """, (day_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def fetch_timeline_by_date(sched_date: str) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT item_type, block_code, start_time, end_time, item_order
        FROM ScheduleTimeline
        WHERE sched_date = ?
        ORDER BY item_order
    """, (sched_date,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

# ---------------------------
# LLM Classifier (Experiment 3)
# ---------------------------
CLASSIFIER_SYSTEM = """
You are an intent classifier for a school chatbot.

Return ONLY valid JSON.
No markdown.
No explanations.

The user message may ask one thing or several things at once.
Output one request object per thing asked, in the order asked (max 3).

Schema:
{
  "requests": [
    {
      "intent": "GREETING" | "MEAL" | "MEALS_DAY" | "SCHEDULE" | "MEAL_SIGNIN" | "SIGNIN_SUMMARY" | "UNKNOWN",
      "day_ref": "TODAY" | "TOMORROW" | "DAY_AFTER_TOMORROW" | "MONDAY" | "TUESDAY" | "WEDNESDAY" | "THURSDAY" | "FRIDAY" | "SATURDAY" | "SUNDAY" | "ANY",
      "meal_type": "BREAKFAST" | "LUNCH" | "DINNER" | "BRUNCH" | "AFTERNOON_SNACK" | null,
      "confidence": 0.0
    }
  ]
}

Rules for each request:
- Greeting/small talk only => GREETING
- "today's meals", "what are meals today" => MEALS_DAY
- "what's for lunch friday" => MEAL
- "schedule for monday", "what blocks tomorrow" => SCHEDULE
- If user asks whether a specific meal has sign-in, classify as MEAL_SIGNIN
- If user asks general sign-in time, dorm sign-in, curfew, residence sign-in, or "sign in time for saturday", classify as SIGNIN_SUMMARY
- If the request is unclear => UNKNOWN
- Use meal_type only when relevant
- Use day_ref=ANY if no day is specified
- "tmr" means tomorrow; "the day after tmr/tomorrow" => DAY_AFTER_TOMORROW
- If [Recent conversation] is given, use it to resolve follow-ups: a vague
  message like "what about tomorrow" or "and dinner?" carries over the
  previous intent and meal_type, changing only what the user newly specified.
- Compound example: "block order tmr and breakfast the day after tmr"
  => requests: [ {intent SCHEDULE, day_ref TOMORROW}, {intent MEAL, meal_type BREAKFAST, day_ref DAY_AFTER_TOMORROW} ]
"""

UNKNOWN_REQUEST = {
    "intent": "UNKNOWN",
    "day_ref": "ANY",
    "meal_type": None,
    "confidence": 0.0
}

MAX_REQUESTS = 6

def validate_request(obj: dict) -> dict:
    intent = str(obj.get("intent", "UNKNOWN")).upper()
    day_ref = str(obj.get("day_ref", "ANY")).upper()
    meal_type = obj.get("meal_type", None)
    confidence = obj.get("confidence", 0.0)

    if isinstance(meal_type, str):
        meal_type = meal_type.upper()

    valid_intents = {
        "GREETING", "MEAL", "MEALS_DAY", "SCHEDULE",
        "MEAL_SIGNIN", "SIGNIN_SUMMARY", "UNKNOWN"
    }
    valid_days = {
        "TODAY", "TOMORROW", "DAY_AFTER_TOMORROW", "MONDAY", "TUESDAY",
        "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY", "ANY"
    }
    valid_meals = {"BREAKFAST", "LUNCH", "DINNER", "BRUNCH", "AFTERNOON_SNACK"}

    if intent not in valid_intents:
        intent = "UNKNOWN"
    if day_ref not in valid_days:
        day_ref = "ANY"
    if meal_type is not None and meal_type not in valid_meals:
        meal_type = None

    try:
        confidence = float(confidence)
    except Exception:
        confidence = 0.0

    return {
        "intent": intent,
        "day_ref": day_ref,
        "meal_type": meal_type,
        "confidence": confidence
    }

def classify_query(user_msg: str, memory: str = "") -> list[dict]:
    if not user_msg or not user_msg.strip():
        return [dict(UNKNOWN_REQUEST)]

    memory = (memory or "").strip()[:1500]
    context = f"[Recent conversation]\n{memory}\n\n" if memory else ""
    prompt = f"{context}[User Message]\n{user_msg}\n\nReturn JSON only."
    try:
        r = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=CLASSIFIER_SYSTEM,
                temperature=0.0,
            ),
        )

        txt = (r.text or "").strip()
        if txt.startswith("```"):
            txt = txt.strip("`").replace("json", "", 1).strip()

        obj = json.loads(txt)

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

    except Exception:
        return [dict(UNKNOWN_REQUEST)]

# ---------------------------
# Build grounded result
# ---------------------------
def build_result_from_classification(cls: dict, user_msg: str) -> dict:
    intent = cls.get("intent", "UNKNOWN")
    day_ref = cls.get("day_ref", "ANY")
    meal_type = cls.get("meal_type")

    day_id = resolve_day_id(day_ref, user_msg)
    day_name = calendar.day_name[day_id - 1]

    if intent == "MEAL":
        rows = fetch_meal(day_id, meal_type) if meal_type else []
        return {
            "type": "MEAL",
            "day_id": day_id,
            "day_name": day_name,
            "meal_type": meal_type,
            "rows": rows
        }

    if intent == "MEALS_DAY":
        rows = fetch_day_meals(day_id)
        return {
            "type": "MEALS_DAY",
            "day_id": day_id,
            "day_name": day_name,
            "rows": rows
        }

    if intent == "SCHEDULE":
        sched_date = resolve_date(day_ref, user_msg)
        rows = fetch_timeline_by_date(sched_date.isoformat())
        return {
            "type": "SCHEDULE",
            "date": sched_date.isoformat(),
            "day_name": calendar.day_name[sched_date.weekday()],
            "rows": rows
        }

    if intent == "MEAL_SIGNIN":
        rows = fetch_meal(day_id, meal_type) if meal_type else []
        return {
            "type": "MEAL_SIGNIN",
            "day_id": day_id,
            "day_name": day_name,
            "meal_type": meal_type,
            "rows": rows
        }

    if intent == "SIGNIN_SUMMARY":
        dorm_rows = fetch_dorm_signins(day_id)
        meals = fetch_day_meals(day_id)
        meals_requiring = [r for r in meals if int(r.get("requires_signin") or 0) == 1]
        return {
            "type": "SIGNIN_SUMMARY",
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
ANSWER_SYSTEM = """
You are a friendly school chatbot.

IMPORTANT RULES:
- Use ONLY the provided JSON data.
- Do not invent schedules, meals, sign-in rules, block names, or times.
- If the data is missing, clearly say you do not have that information.
- "results" is a list: the user may have asked several things at once.
  Answer EVERY result, in order, in one reply. Each result has its own day_name.

STYLE:
- Friendly, natural, concise.
- Short paragraphs are okay.
- Bullet points are okay.
- Always mention the actual day_name when answering.

SPECIAL RULES:
- For MEAL:
  - Give meal time, group(s), and menu if available.
- For MEALS_DAY:
  - Organize by meal type.
- For SCHEDULE:
  - Show timeline in order.
- For MEAL_SIGNIN:
  - Say whether sign-in is required.
  - Include time range.
  - Mention Dining Hall.
- For SIGNIN_SUMMARY:
  - Show dorm sign-in times.
  - Show meal sign-ins that require sign-in.
- For GREETING:
  - Greet back and briefly say what the user can ask.

Return plain English text only.
"""

def generate_answer(user_msg: str, classifications: list[dict], results: list[dict]) -> str:
    now = datetime.now()
    server_day_name = calendar.day_name[now.isoweekday() - 1]
    server_time = now.strftime("%H:%M")

    payload = {
        "server_time": f"{server_day_name} {server_time}",
        "user_message": user_msg,
        "classifications": classifications,
        "results": results,
    }

    try:
        r = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=json.dumps(payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=ANSWER_SYSTEM,
                temperature=0.2,
            ),
        )
        return (r.text or "").strip()
    except Exception:
        return "Sorry — I hit an API quota limit right now. Try again in a moment 🙂"

# ---------------------------
# Routes
# ---------------------------
@app.route("/chat", methods=["POST"])
def chat():
    req_id = str(uuid.uuid4())[:8]
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message", "") or "").strip()
    memory = (data.get("memory", "") or "")

    if len(user_msg) > 500:
        return jsonify({"reply": "That message is a bit long — could you shorten it?"}), 400

    if DEBUG:
        print(f"\n[{req_id}] USER: {user_msg}")

    classifications = classify_query(user_msg, memory)

    if DEBUG:
        print(f"[{req_id}] CLASSIFICATIONS: {json.dumps(classifications, ensure_ascii=False, indent=2)}")

    actionable = [c for c in classifications if c.get("intent") not in ("UNKNOWN", "GREETING")]

    if not actionable:
        if any(c.get("intent") == "GREETING" for c in classifications):
            reply = generate_answer(user_msg, classifications, [{"type": "GREETING"}])
            if SERVER_TAG:
                reply = f"{SERVER_TAG} {reply}"
            return jsonify({"reply": reply})

        friendly = "Hey 🙂 I’m not fully sure what you want. You can ask about meals, schedules, or sign-in times."
        if SERVER_TAG:
            friendly = f"{SERVER_TAG} {friendly}"
        return jsonify({"reply": friendly})

    try:
        results = [build_result_from_classification(c, user_msg) for c in actionable]
    except Exception as e:
        if DEBUG:
            print(f"[{req_id}] build_result error: {e}")
        return jsonify({"reply": "Sorry — I had trouble reading the school data."}), 500

    if DEBUG:
        print(f"[{req_id}] RESULTS: {json.dumps(results, ensure_ascii=False, indent=2)[:2500]}")

    reply = generate_answer(user_msg, actionable, results)

    if SERVER_TAG:
        reply = f"{SERVER_TAG} {reply}"

    return jsonify({"reply": reply})

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)