from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from google import genai
from google.genai import types
import json
import os
import sqlite3


app = Flask(__name__, static_url_path='', static_folder='static')

# =========================
# DB 연결 헬퍼
# =========================
def get_db():
    conn = sqlite3.connect("db/school.db")
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# 급식 정보 Upsert API
# =========================
@app.route("/api/v1/meals", methods=["POST"])
def upsert_meal():  
    data = request.get_json()

    required = ["day_id", "group_id", "meal_type", "menu"]
    if not data or not all(k in data for k in required):
        return jsonify({"error": "Invalid request body"}), 400

    with get_db() as db:
        cur = db.cursor()

        # meal_type 문자열 -> meal_type_id
        cur.execute(
            "SELECT meal_type_id FROM MealTypes WHERE type_name=?",
            (data["meal_type"],)
        )
        meal_type = cur.fetchone()
        if not meal_type:
            return jsonify({"error": "Invalid meal type"}), 400

        # 급식 스케줄 확인
        cur.execute("""
            SELECT schedule_id FROM MealSchedules
            WHERE day_id=? AND group_id=? AND meal_type_id=?
        """, (
            data["day_id"],
            data["group_id"],
            meal_type["meal_type_id"]
        ))
        schedule = cur.fetchone()

        if not schedule:
            return jsonify({"error": "Meal schedule not found"}), 404

        # Upsert
        cur.execute("""
            INSERT INTO Menus (schedule_id, menu_content)
            VALUES (?, ?)
            ON CONFLICT(schedule_id)
            DO UPDATE SET menu_content = excluded.menu_content
        """, (
            schedule["schedule_id"],
            data["menu"]
        ))

        db.commit()

    return jsonify({"status": "ok"}), 200

# =========================
# 시간표 블록 순서 업데이트 API
# =========================
@app.route("/api/v1/timetable/blocks", methods=["POST"])
def update_timetable_blocks():
    data = request.get_json()

    # 요청 형식 검증
    if not data or "day_id" not in data or "blocks" not in data:
        return jsonify({"error": "Invalid request body"}), 400

    day_id = data["day_id"]
    blocks = data["blocks"]

    with get_db() as db:
        cur = db.cursor()

        #해당 요일의 기존 BLOCK만 삭제
        # (ADVISORY, ASSEMBLY, COOKIE_BREAK 등은 유지됨)
        cur.execute("""
            DELETE FROM DayTimeline
            WHERE day_id = ? AND item_type = 'BLOCK'
        """, (day_id,))

        # 새 블록 순서대로 INSERT
        order_num = 1
        for block_code in blocks:
            # block_code → block_id
            cur.execute(
                "SELECT block_id FROM Blocks WHERE block_code = ?",
                (block_code,)
            )
            block = cur.fetchone()
            if not block:
                return jsonify({"error": f"Invalid block code: {block_code}"}), 400

            cur.execute("""
                INSERT INTO DayTimeline
                (day_id, item_type, block_id, start_time, end_time, item_order)
                VALUES (?, 'BLOCK', ?, NULL, NULL, ?)
            """, (day_id, block["block_id"], order_num))

            order_num += 1

        db.commit()

    return jsonify({"status": "ok"}), 200

# =========================
# Gemini / Chatbot 
# =========================
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

def load_school_data():
    with open("school_data.json", "r") as f:
        return json.load(f)

school_data = load_school_data()

SYSTEM_PROMPT = """
You are a helpful Brentwood School assistant chatbot.
You only answer questions related to school information or questions about school.
"""

@app.route('/api/chat', methods=['POST'])
def chat():
    user_msg = request.json.get("message", "")

    if len(user_msg) > 200:
        return jsonify({"reply": "Input cannot exceed 200 characters."})

    info_text = "\n".join([
        f"- {key.replace('_',' ').title()}: {value}"
        for key, value in school_data.items()
    ])

    prompt = f"""
Here is the school information:
{info_text}

User question:
{user_msg}
"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT
        )
    )

    return jsonify({"reply": response.text})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# =========================
# 서버 실행 
# =========================
if __name__ == "__main__":
    app.run(debug=True)