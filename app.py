# GrishteSync backend - v0.0.1
import os
import re
import json
import base64
import requests
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from urllib.parse import urlencode

app = Flask(__name__)
CORS(app)

# ---------- Configuration ----------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.3-70b-versatile"

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://suryasticsai.github.io/grishtesync")
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"

# ---------- OAuth Routes ----------
@app.route("/auth/login")
def login():
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": f"{request.host_url.rstrip('/')}/auth/callback",
        "scope": "repo workflow",
        "state": "randomstring123"
    }
    url = f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
    return redirect(url)

@app.route("/auth/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Missing code.", 400

    token_resp = requests.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": f"{request.host_url.rstrip('/')}/auth/callback"
        }
    )
    token_json = token_resp.json()
    if "access_token" not in token_json:
        return f"Failed to get token: {token_json}", 500

    access_token = token_json["access_token"]
    return redirect(f"{FRONTEND_URL}?token={access_token}")

# ---------- AI Generation (unchanged) ----------
@app.route("/")
def home():
    return "GrishteSync backend is running."

@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    system_prompt = (
        "You are an expert Python developer. "
        "Given a user request, determine if they want a Streamlit app, a Gradio app, or a Flask app. "
        "Default to Gradio if unclear. "
        "Generate the complete code for that framework. "
        "Return exactly a JSON object with a key 'files' that maps filenames to file contents. "
        "For Streamlit: 'app.py' must contain a runnable Streamlit script (no 'if __name__' block needed). "
        "For Gradio: standard Gradio interface with demo.launch(). "
        "For Flask: standard Flask app with app.run(). "
        "Also include 'requirements.txt' with the necessary dependencies, "
        "and any other files like '.env.example', 'tests/test_main.py', 'README.md'. "
        "Use valid JSON: escape double quotes inside strings, use \\n for newlines. "
        "Do not wrap the JSON in markdown. "
        "Example: {\"files\": {\"app.py\": \"import streamlit as st\\n\\nst.title('My App')\\nname = st.text_input('Your name')\\nst.write(f'Hello {name}')\"}}"
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

        if ai_content.startswith("```json"):
            ai_content = ai_content[7:]
        if ai_content.endswith("```"):
            ai_content = ai_content[:-3]
        ai_content = ai_content.strip()

        json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
        if json_match:
            ai_content = json_match.group(0)

        try:
            generated = json.loads(ai_content)
        except json.JSONDecodeError as e:
            return jsonify({
                "error": "AI response was not valid JSON.",
                "raw_response": ai_content,
                "parse_error": str(e)
            }), 500

        if "files" not in generated:
            generated = {"files": generated}

        return jsonify(generated)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Deploy (with user's token) ----------
@app.route("/api/deploy", methods=["POST"])
def deploy():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("token "):
        return jsonify({"error": "Missing or invalid Authorization header. Use 'token <github_token>'"}), 401

    user_token = auth_header.split(" ", 1)[1]

    data = request.get_json()
    repo_name = data.get("repo_name", "my-ai-app")
    files = data.get("files", {})
    version = data.get("version", "0.0.0")

    headers = {
        "Authorization": f"token {user_token}",
        "Accept": "application/vnd.github.v3+json"
    }

    user_resp = requests.get(f"{GITHUB_API_URL}/user", headers=headers)
    if user_resp.status_code != 200:
        return jsonify({"error": "Invalid GitHub token or unable to fetch user."}), 401
    username = user_resp.json()["login"]

    repo_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}"
    check = requests.get(repo_url, headers=headers)
    if check.status_code != 200:
        create_data = {"name": repo_name, "private": False, "auto_init": True}
        create_resp = requests.post(f"{GITHUB_API_URL}/user/repos", headers=headers, json=create_data)
        if create_resp.status_code not in [200, 201]:
            return jsonify({"error": f"Failed to create repo: {create_resp.text}"}), 500

    repo_info = requests.get(repo_url, headers=headers).json()
    default_branch = repo_info.get("default_branch", "main")

    for filepath, content in files.items():
        encoded = base64.b64encode(content.encode()).decode()
        api_path = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{filepath}"
        commit_message = f"Add {filepath} via GrishteSync v{version}"
        payload = {
            "message": commit_message,
            "content": encoded,
            "branch": default_branch
        }
        file_check = requests.get(api_path, headers=headers, params={"ref": default_branch})
        if file_check.status_code == 200:
            payload["sha"] = file_check.json()["sha"]
        put_resp = requests.put(api_path, headers=headers, json=payload)
        if put_resp.status_code not in [200, 201]:
            return jsonify({"error": f"Failed to push {filepath}: {put_resp.text}"}), 500

    return jsonify({
        "status": "success",
        "repo_url": f"https://github.com/{username}/{repo_name}",
        "branch": default_branch
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))