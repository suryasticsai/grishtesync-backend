# GrishteSync backend - v0.0
import os
import re
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.3-70b-versatile"   # corrected model name

@app.route("/")
def home():
    return "GrishteSync backend is running. Use POST /api/generate"

@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    system_prompt = (
        "You are an expert Python developer. "
        "Given a user request, generate the complete code for a Python AI web app using Gradio or Flask. "
        "Return exactly a JSON object with a key 'files' that maps filenames to file contents. "
        "The JSON must be valid: use double quotes, escape any double quotes inside strings with backslash, "
        "and use \\n for newlines inside the code strings. "
        "Do not wrap the JSON in any additional text or markdown. "
        "Example: {\"files\": {\"app.py\": \"import gradio as gr\\ndef greet(name):\\n    return 'Hello ' + name\"}}"
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
        ai_content = resp.json()["choices"][0]["message"]["content"].strip()

        # ---- CLEAN UP THE AI OUTPUT ----
        # Sometimes the AI wraps in ```json ... ```, remove it
        if ai_content.startswith("```json"):
            ai_content = ai_content[7:]
        if ai_content.endswith("```"):
            ai_content = ai_content[:-3]
        ai_content = ai_content.strip()

        # Try to find a JSON object in the text (even if there's extra text)
        json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
        if json_match:
            ai_content = json_match.group(0)

        # Fix common issues: unescaped newlines inside strings (simple but fragile)
        # A better approach is to try parsing, and if it fails, return the raw content
        try:
            generated = json.loads(ai_content)
        except json.JSONDecodeError as e:
            # Return the raw AI content so we can see what went wrong
            return jsonify({
                "error": "AI response was not valid JSON.",
                "raw_response": ai_content,
                "parse_error": str(e)
            }), 500

        # Ensure the expected structure exists
        if "files" not in generated:
            generated = {"files": generated}  # wrap if AI forgot the 'files' key

        return jsonify(generated)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))