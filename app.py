from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from google import genai
from google.genai import types
import os
import sqlite3
from datetime import datetime
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

def get_server_day_id() -> int:
    return datetime.now().isoweekday()

def resolve_day_id(day_ref: str | None, user_msg: str = "") -> int:
    today = get_server_day_id()
    d = (day_ref or "").upper().strip()

    if d in DAYREF_MAP:
        return DAYREF_MAP[d]
    if d == "TODAY":
        return today
    if d == "TOMORROW":
        return 1 if today == 7 else today + 1

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

def fetch_timeline(day_id: int) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT dt.item_type, b.block_code, dt.start_time, dt.end_time, dt.item_order
        FROM DayTimeline dt
        LEFT JOIN Blocks b ON dt.block_id = b.block_id
        WHERE dt.day_id = ?
        ORDER BY dt.item_order
    """, (day_id,))
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

Classify the user message into exactly ONE intent.

Schema:
{
  "intent": "GREETING" | "MEAL" | "MEALS_DAY" | "SCHEDULE" | "MEAL_SIGNIN" | "SIGNIN_SUMMARY" | "UNKNOWN",
  "day_ref": "TODAY" | "TOMORROW" | "MONDAY" | "TUESDAY" | "WEDNESDAY" | "THURSDAY" | "FRIDAY" | "SATURDAY" | "SUNDAY" | "ANY",
  "meal_type": "BREAKFAST" | "LUNCH" | "DINNER" | "BRUNCH" | "AFTERNOON_SNACK" | null,
  "confidence": 0.0
}

Rules:
- Greeting/small talk only => GREETING
- "today's meals", "what are meals today" => MEALS_DAY
- "what's for lunch friday" => MEAL
- "schedule for monday", "what blocks tomorrow" => SCHEDULE
- If user asks whether a specific meal has sign-in, classify as MEAL_SIGNIN
- If user asks general sign-in time, dorm sign-in, curfew, residence sign-in, or "sign in time for saturday", classify as SIGNIN_SUMMARY
- If the request is unclear => UNKNOWN
- Use meal_type only when relevant
- Use day_ref=ANY if no day is specified
- Output exactly one intent only
"""

def classify_query(user_msg: str) -> dict:
    if not user_msg or not user_msg.strip():
        return {
            "intent": "UNKNOWN",
            "day_ref": "ANY",
            "meal_type": None,
            "confidence": 0.0
        }

    prompt = f"[User Message]\n{user_msg}\n\nReturn JSON only."
    try:
        r = client.models.generate_content(
            model="gemini-2.0-flash",
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
            "TODAY", "TOMORROW", "MONDAY", "TUESDAY", "WEDNESDAY",
            "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY", "ANY"
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

    except Exception:
        return {
            "intent": "UNKNOWN",
            "day_ref": "ANY",
            "meal_type": None,
            "confidence": 0.0
        }

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
        rows = fetch_timeline(day_id)
        return {
            "type": "SCHEDULE",
            "day_id": day_id,
            "day_name": day_name,
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

def generate_answer(user_msg: str, classification: dict, result: dict) -> str:
    now = datetime.now()
    server_day_name = calendar.day_name[now.isoweekday() - 1]
    server_time = now.strftime("%H:%M")

    payload = {
        "server_time": f"{server_day_name} {server_time}",
        "user_message": user_msg,
        "classification": classification,
        "result": result,
    }

    try:
        r = client.models.generate_content(
            model="gemini-2.0-flash",
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

    if len(user_msg) > 500:
        return jsonify({"reply": "That message is a bit long — could you shorten it?"}), 400

    if DEBUG:
        print(f"\n[{req_id}] USER: {user_msg}")

    classification = classify_query(user_msg)

    if DEBUG:
        print(f"[{req_id}] CLASSIFICATION: {json.dumps(classification, ensure_ascii=False, indent=2)}")

    intent = classification.get("intent", "UNKNOWN")

    if intent == "UNKNOWN":
        friendly = "Hey 🙂 I’m not fully sure what you want. You can ask about meals, schedules, or sign-in times."
        if SERVER_TAG:
            friendly = f"{SERVER_TAG} {friendly}"
        return jsonify({"reply": friendly})

    if intent == "GREETING":
        reply = generate_answer(user_msg, classification, {"type": "GREETING"})
        if SERVER_TAG:
            reply = f"{SERVER_TAG} {reply}"
        return jsonify({"reply": reply})

    try:
        result = build_result_from_classification(classification, user_msg)
    except Exception as e:
        if DEBUG:
            print(f"[{req_id}] build_result error: {e}")
        return jsonify({"reply": "Sorry — I had trouble reading the school data."}), 500

    if DEBUG:
        print(f"[{req_id}] RESULT: {json.dumps(result, ensure_ascii=False, indent=2)[:2500]}")

    reply = generate_answer(user_msg, classification, result)

    if SERVER_TAG:
        reply = f"{SERVER_TAG} {reply}"

    return jsonify({"reply": reply})

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)