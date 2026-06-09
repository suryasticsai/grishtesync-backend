# GrishteSync backend - v0.0
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)  # Allow requests from your GitHub Pages frontend

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.3-70b-versatile"

@app.route("/")
def home():
    return "GrishteSync backend is running. Use POST /api/generate"

@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    # System message that tells the AI what to build
    system_prompt = (
        "You are an expert Python developer. "
        "Given a user request, generate the complete code for a Python AI web app using Gradio or Flask. "
        "Return the code in the following JSON structure ONLY, with no extra text:\n"
        '{"files": {"app.py": "...", "requirements.txt": "...", ".env.example": "...", "tests/test_main.py": "...", "README.md": "..."}}'
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Build a Python AI app with this description: {prompt}"}
    ]

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL_NAME,
                "messages": messages,
                "temperature": 0.3
            }
        )
        resp.raise_for_status()
        ai_content = resp.json()["choices"][0]["message"]["content"]

        # Try to parse the JSON from the AI
        import json
        # Sometimes AI wraps in ```json ... ```, so extract
        ai_content = ai_content.strip()
        if ai_content.startswith("```json"):
            ai_content = ai_content[7:]
        if ai_content.endswith("```"):
            ai_content = ai_content[:-3]
        generated = json.loads(ai_content)
        return jsonify(generated)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))