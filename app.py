from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from google import genai
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

#  system prompt 
SYSTEM_PROMPT = """
You are a helpful Brentwood School assistant chatbot.
You only answer questions related to school information or questions about school.
"""

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json.get("message", "")

    #입력 갈이 제한
    if len(user_msg) > 200:
        return jsonify({
            "reply": "Input cannot exceed 200 characters."
        })

    info_text = "\n".join([
        f"- {key.replace('_',' ').title()}: {value}"
        for key, value in school_data.items()
    ])
    #유저 입력과 시스템 프롬프트 분리
    prompt = f"""
{SYSTEM_PROMPT}

Here is the school information:
{info_text}

User question:
{user_msg}
"""
    
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt
    )

    return jsonify({"reply": response.text})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == "__main__":
    app.run(port=3000, debug=True)