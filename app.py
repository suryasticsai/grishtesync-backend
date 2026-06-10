# GrishteSync - v0.1
import os
import re
import json
import base64
import requests
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from urllib.parse import urlencode
import datetime

app = Flask(__name__)
CORS(app)

# ---------- Configuration ----------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.3-70b-versatile"

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://suryasticsai.github.io/GrishteSync/")
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"

HF_CLIENT_ID = os.environ.get("HF_CLIENT_ID")
HF_CLIENT_SECRET = os.environ.get("HF_CLIENT_SECRET")
HF_AUTHORIZE_URL = "https://huggingface.co/oauth/authorize"
HF_TOKEN_URL = "https://huggingface.co/oauth/token"
HF_API_URL = "https://huggingface.co/api"

# ---------- GitHub OAuth ----------
@app.route("/auth/login")
def github_login():
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": f"{request.host_url.rstrip('/')}/auth/callback",
        "scope": "repo workflow",
        "state": "github"
    }
    return redirect(f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}")

@app.route("/auth/callback")
def github_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing code"}), 400
    resp = requests.post(GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": f"{request.host_url.rstrip('/')}/auth/callback"
        })
    data = resp.json()
    if "access_token" not in data:
        return jsonify({"error": "GitHub token error", "details": data}), 500
    return redirect(f"{FRONTEND_URL}?token={data['access_token']}")

# ---------- Hugging Face OAuth (FIXED) ----------
@app.route("/hf/login")
def hf_login():
    params = {
        "client_id": HF_CLIENT_ID,
        "redirect_uri": f"{request.host_url.rstrip('/')}/hf/callback",
        "scope": "write-repos read-repos",
        "state": "huggingface",
        "response_type": "code" 
    }
    return redirect(f"{HF_AUTHORIZE_URL}?{urlencode(params)}")

# 🔍 Debug mode – shows the full token exchange response
@app.route("/hf/callback")
def hf_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing code"}), 400

    payload = {
        "client_id": HF_CLIENT_ID,
        "client_secret": HF_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": f"{request.host_url.rstrip('/')}/hf/callback"
    }
    resp = requests.post(HF_TOKEN_URL, data=payload)
    return jsonify({
        "debug_sent": payload,
        "response_status": resp.status_code,
        "response_body": resp.json()
    })

# ---------- AI Generation (unchanged) ----------
@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    repo_full_name = data.get("repo")
    user_token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("token "):
        user_token = auth_header.split(" ", 1)[1]

    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    system_prompt = (
        "You are an expert Python developer. "
        "The user will give a description of the app they want. "
        "If the prompt is empty or meaningless, generate a simple Gradio or Streamlit app that displays the prompt text in a nice card. "
        "Otherwise, build the requested app. "
        "Return exactly a JSON object with a key 'files' mapping filenames to file contents. "
        "Important rules:\n"
        "1. Every Python file must start with this exact comment:\n"
        "# Created with GrishteSync\n"
        "# https://suryasticsai.github.io/GrishteSync\n"
        "# Suryasticsai | suryasticsai@gmail.com\n"
        "2. The main app file (app.py) must include a visible footer that shows:\n"
        "   'Made with GrishteSync | Suryasticsai | suryasticsai@gmail.com'\n"
        "   and a link to https://suryasticsai.github.io/GrishteSync.\n"
        "   For Streamlit, use st.markdown() or similar; for Gradio, gr.HTML() or similar.\n"
        "3. The main app must also show the GrishteSync logo as a header or footer image.\n"
        "   Use this exact URL for the image: https://i.ibb.co/pjmCv3Vy/1781038658031.png\n"
        "   For Streamlit: st.image('https://i.ibb.co/pjmCv3Vy/1781038658031.png', width=200)\n"
        "   For Gradio: gr.HTML('<img src=\"https://i.ibb.co/pjmCv3Vy/1781038658031.png\" width=\"200\">')\n"
        "   Place it above the title or in the footer, together with the watermark text.\n"
        "4. The README.md file must contain a 'Built with GrishteSync' section with:\n"
        "   - Link to the author's GitHub: https://github.com/suryasticsai\n"
        "   - LinkedIn: https://linkedin.com/in/suryasticsai\n"
        "   - Email: suryasticsai@gmail.com\n"
        "   - The logo image: ![GrishteSync Logo](https://i.ibb.co/pjmCv3Vy/1781038658031.png)\n"
        "5. Use valid JSON: escape double quotes inside strings, use \\n for newlines. Do not wrap the JSON in markdown.\n"
        "6. Include a requirements.txt with all dependencies.\n"
        "7. For a meaningless prompt, create a minimal app that simply shows the user's input text."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Build/update: {prompt}"}
    ]

    if repo_full_name and user_token:
        try:
            headers = {"Authorization": f"token {user_token}", "Accept": "application/vnd.github.v3+json"}
            contents_url = f"{GITHUB_API_URL}/repos/{repo_full_name}/contents"
            contents_resp = requests.get(contents_url, headers=headers)
            if contents_resp.status_code != 200:
                return jsonify({"error": f"Failed to read repo: {contents_resp.text}"}), 500
            repo_files = contents_resp.json()
            existing_code = {}
            for item in repo_files:
                if item["type"] == "file" and item["size"] < 500000:
                    file_content = requests.get(item["download_url"]).text
                    existing_code[item["name"]] = file_content
            context = "Current codebase (update it according to the prompt):\n"
            for fname, content in existing_code.items():
                context += f"\n--- {fname} ---\n{content}\n"
            messages.insert(0, {"role": "system", "content": context + "\n" + system_prompt})
        except Exception as e:
            return jsonify({"error": f"Error fetching repo: {str(e)}"}), 500

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL_NAME, "messages": messages, "temperature": 0.3}
        )
        resp.raise_for_status()
        ai_content = resp.json()["choices"][0]["message"]["content"].strip()
        if ai_content.startswith("```json"):
            ai_content = ai_content[7:]
        if ai_content.endswith("```"):
            ai_content = ai_content[:-3]
        json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
        if json_match:
            ai_content = json_match.group(0)
        generated = json.loads(ai_content)
        if "files" not in generated:
            generated = {"files": generated}
        return jsonify(generated)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Deploy to GitHub ----------
@app.route("/api/deploy", methods=["POST"])
def deploy():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("token "):
        return jsonify({"error": "Missing GitHub token"}), 401
    user_token = auth_header.split(" ", 1)[1]
    data = request.get_json()
    repo_name = data.get("repo_name")
    files = data.get("files", {})
    version = data.get("version", "0.0.0")

    headers = {"Authorization": f"token {user_token}", "Accept": "application/vnd.github.v3+json"}
    user_resp = requests.get(f"{GITHUB_API_URL}/user", headers=headers)
    if user_resp.status_code != 200:
        return jsonify({"error": "Invalid token"}), 401
    username = user_resp.json()["login"]

    repo_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}"
    check = requests.get(repo_url, headers=headers)
    if check.status_code != 200:
        create_resp = requests.post(f"{GITHUB_API_URL}/user/repos", headers=headers,
                                    json={"name": repo_name, "private": False, "auto_init": True})
        if create_resp.status_code not in [200, 201]:
            return jsonify({"error": f"Failed to create repo: {create_resp.text}"}), 500

    repo_info = requests.get(repo_url, headers=headers).json()
    default_branch = repo_info.get("default_branch", "main")

    branch_name = f"agent/feature-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    ref_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs/heads/{default_branch}"
    ref_resp = requests.get(ref_url, headers=headers)
    if ref_resp.status_code != 200:
        return jsonify({"error": "Failed to read default branch ref"}), 500
    sha = ref_resp.json()["object"]["sha"]
    new_ref_data = {"ref": f"refs/heads/{branch_name}", "sha": sha}
    create_ref = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs", headers=headers, json=new_ref_data)
    if create_ref.status_code != 201:
        return jsonify({"error": f"Failed to create branch: {create_ref.text}"}), 500

    for filepath, content in files.items():
        encoded = base64.b64encode(content.encode()).decode()
        api_path = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{filepath}"
        commit_msg = f"Update {filepath} via GrishteSync v{version}"
        payload = {
            "message": commit_msg,
            "content": encoded,
            "branch": branch_name
        }
        put_resp = requests.put(api_path, headers=headers, json=payload)
        if put_resp.status_code not in [200, 201]:
            return jsonify({"error": f"Push failed for {filepath}: {put_resp.text}"}), 500

    custom_description = data.get("pr_description")
    if custom_description:
        pr_body = custom_description
    else:
        pr_body = (
            f"## 🌀 GrishteSync Automatic Pull Request\n\n"
            f"**Version:** v{version}\n\n"
            f"**Files changed:**\n" +
            "\n".join([f"- {f}" for f in files.keys()]) + "\n\n"
            f"*Created with [GrishteSync](https://suryasticsai.github.io/GrishteSync) | [Suryasticsai](https://github.com/suryasticsai) | suryasticsai@gmail.com*\n\n"
            f"![GrishteSync Logo](https://i.ibb.co/pjmCv3Vy/1781038658031.png)"
        )

    pr_data = {
        "title": f"GrishteSync update v{version}",
        "head": branch_name,
        "base": default_branch,
        "body": pr_body
    }
    pr_resp = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/pulls", headers=headers, json=pr_data)
    pr_url = pr_resp.json().get("html_url") if pr_resp.status_code in [200, 201] else None

    return jsonify({
        "status": "success",
        "repo_url": f"https://github.com/{username}/{repo_name}",
        "branch": branch_name,
        "pr_url": pr_url
    })

# ---------- Hugging Face Deploy ----------
@app.route("/api/deploy-hf", methods=["POST"])
def deploy_hf():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("token "):
        return jsonify({"error": "Missing GitHub token"}), 401
    github_token = auth_header.split(" ", 1)[1]

    hf_header = request.headers.get("HF-Authorization")
    if not hf_header or not hf_header.startswith("Bearer "):
        return jsonify({"error": "Missing Hugging Face token"}), 401
    hf_token = hf_header.split(" ", 1)[1]

    data = request.get_json()
    repo_full_name = data.get("repo_full_name")
    space_name = data.get("space_name", repo_full_name.split("/")[1] if repo_full_name else "grishte-app")
    sdk = data.get("sdk", "streamlit")

    if not repo_full_name:
        return jsonify({"error": "repo_full_name required"}), 400

    hf_user_resp = requests.get(f"{HF_API_URL}/whoami", headers={"Authorization": f"Bearer {hf_token}"})
    if hf_user_resp.status_code != 200:
        return jsonify({"error": "Invalid Hugging Face token"}), 401
    hf_username = hf_user_resp.json()["name"]

    space_url = f"{HF_API_URL}/spaces/{hf_username}/{space_name}"
    check = requests.get(space_url)
    if check.status_code != 200:
        create_data = {"sdk": sdk, "hardware": "cpu-basic", "name": space_name, "private": False}
        create_resp = requests.post(f"{HF_API_URL}/spaces", json=create_data, headers={"Authorization": f"Bearer {hf_token}"})
        if create_resp.status_code not in [200, 201]:
            return jsonify({"error": f"Failed to create Space: {create_resp.text}"}), 500

    link_resp = requests.post(
        f"{HF_API_URL}/spaces/{hf_username}/{space_name}/repo",
        headers={"Authorization": f"Bearer {hf_token}"},
        json={"repo_id": repo_full_name, "repo_type": "github", "oauth_token": github_token}
    )
    if link_resp.status_code not in [200, 201]:
        return jsonify({"error": f"Failed to link repo: {link_resp.text}"}), 500

    return jsonify({"status": "success", "space_url": f"https://huggingface.co/spaces/{hf_username}/{space_name}"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))