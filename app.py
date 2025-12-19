from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from google import genai
from google.genai import types
import json
import os

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

app = Flask(__name__, static_url_path='', static_folder='static')

# Read school data
def load_school_data():
    with open("school_data.json", "r") as f:
        return json.load(f)

school_data = load_school_data()


SYSTEM_PROMPT = """
You are a helpful Brentwood School assistant chatbot.
You only answer questions related to school information or questions about school.
"""

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json.get("message", "")

    # 입력 길이 제한
    if len(user_msg) > 200:
        return jsonify({
            "reply": "Input cannot exceed 200 characters."
        })

    # 학교 데이터 텍스트화
    info_text = "\n".join([
        f"- {key.replace('_',' ').title()}: {value}"
        for key, value in school_data.items()
    ])

    #not include system prompt
    prompt = f"""
Here is the school information:
{info_text}

User question:
{user_msg}
"""
    # config는 규칙이고, content로 한번에 주면 유저 메세지랑 동급
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

if __name__ == "__main__":
    app.run(port=3000, debug=True)