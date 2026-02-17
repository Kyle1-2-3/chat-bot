from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from google import genai
from google.genai import types
import os
import sqlite3
from datetime import datetime
import calendar

load_dotenv()

app = Flask(__name__, static_url_path="", static_folder="static")

# ---------------------------
# DB
# ---------------------------
def get_db():
    db_path = os.path.join("db", "school.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------------------
# Context Builder
# ---------------------------
def get_school_context(user_msg: str) -> str:
    conn = get_db()
    cur = conn.cursor()

    days_map = {
        "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
        "friday": 5, "saturday": 6, "sunday": 7
    }

    # Server time (always compute per-request)
    now = datetime.now()
    server_day_id = now.isoweekday()
    server_day_name = calendar.day_name[server_day_id - 1]
    server_time = now.strftime("%H:%M")

    # Default: today
    target_day = server_day_id
    day_label = f"Today ({server_day_name}, {server_time})"

    # If user explicitly mentions a weekday, use that day_id instead
    msg_lower = (user_msg or "").lower()
    for day_name, day_id in days_map.items():
        if day_name in msg_lower:
            target_day = day_id
            # Still include server time so the model knows "today" reference
            day_label = f"{day_name.capitalize()} (server time: {server_day_name}, {server_time})"
            break

    context = f"Current server time: {day_label}\n"
    context += f"Target Day ID: {target_day}\n"

    # 1) Meals
    cur.execute("""
        SELECT mt.type_name, m.menu_content, gg.group_name, ms.start_time, ms.end_time
        FROM Menus m
        JOIN MealSchedules ms ON m.schedule_id = ms.schedule_id
        JOIN MealTypes mt ON ms.meal_type_id = mt.meal_type_id
        JOIN GradeGroups gg ON ms.group_id = gg.group_id
        WHERE ms.day_id = ?
        ORDER BY mt.meal_type_id, gg.group_id
    """, (target_day,))
    meals = cur.fetchall()

    context += "\n[Meals]\n"
    if meals:
        for m in meals:
            context += f"- {m['type_name']} ({m['group_name']}): {m['menu_content']} [{m['start_time']}-{m['end_time']}]\n"
    else:
        context += "- No meal data found.\n"

    # 2) Academic schedule
    cur.execute("""
        SELECT dt.item_type, b.block_code, dt.start_time, dt.end_time
        FROM DayTimeline dt
        LEFT JOIN Blocks b ON dt.block_id = b.block_id
        WHERE dt.day_id = ?
        ORDER BY dt.item_order
    """, (target_day,))
    timeline = cur.fetchall()

    context += "\n[Academic Schedule]\n"
    if timeline:
        for t in timeline:
            name = t["block_code"] if t["item_type"] == "BLOCK" else t["item_type"]
            context += f"- {name}: {t['start_time']} - {t['end_time']}\n"
    else:
        context += "- No schedule data found.\n"

    # 3) Dorm rules
    cur.execute("""
        SELECT rt.type_name, dsr.start_time, dsr.end_time, gg.group_name
        FROM DormScheduleRules dsr
        JOIN DormSchedules ds ON dsr.dorm_schedule_id = ds.dorm_schedule_id
        JOIN DormRuleTypes rt ON dsr.rule_type_id = rt.rule_type_id
        JOIN GradeGroups gg ON ds.group_id = gg.group_id
        WHERE ds.day_id = ?
        ORDER BY dsr.rule_order, gg.group_id
    """, (target_day,))
    dorm = cur.fetchall()

    context += "\n[Dorm Rules]\n"
    if dorm:
        for d in dorm:
            time = f"{d['start_time']} - {d['end_time']}" if d["end_time"] else d["start_time"]
            context += f"- {d['type_name']} ({d['group_name']}): {time}\n"
    else:
        context += "- No dorm rule data found.\n"

    conn.close()
    return context

# ---------------------------
# Gemini Client + Prompt
# ---------------------------
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """
You are a friendly Brentwood College School assistant chat bot.

Rules:
- Respond only in English.
- Always trust the provided current server time. Never guess dates or times.
- Only use information from the School Context.
- If the answer is not in the School Context, say you don’t have that information.
- Do not invent or assume missing details.

Style:
- Keep responses short, clear, and conversational.
- Sound like a helpful student assistant, not a robot.
- Format schedules or meals cleanly when listing them.
"""

# ---------------------------
# Routes
# ---------------------------
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}

    user_msg = data.get("message", "") or ""
    memory = data.get("memory", "") or ""

    if len(user_msg) > 200:
        return jsonify({"reply": "Input too long."}), 400

    school_context = get_school_context(user_msg)

    prompt = f"""
[Previous Conversation]
{memory}

[School Context]
{school_context}

[User Question]
{user_msg}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        return jsonify({"reply": response.text})
    except Exception:
        return jsonify({"reply": "API Quota exceeded. Please wait a moment."}), 429

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)