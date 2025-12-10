from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from google import genai
import json
import os

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

app = Flask(__name__, static_url_path='', static_folder='static')

def load_school_data():
    with open("school_data.json", "r") as f:
        return json.load(f)

school_data = load_school_data()

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json['message']

    info_text = "\n".join([
        f"- {key.replace('_',' ').title()}: {value}"
        for key, value in school_data.items()
    ])

    prompt = f"""
You are a helpful Brentwood School assistant chatbot.

Here is the school information (use it when relevant):

{info_text}

User: {user_msg}
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