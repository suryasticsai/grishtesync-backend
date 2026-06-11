# GrishteSync v0.9 – Fixed HF Space Creation with huggingface_hub
import os
import re
import json
import base64
import time
import traceback
import datetime
import io
import requests
from flask import Flask, request, jsonify, redirect, make_response
from flask_cors import CORS
from urllib.parse import urlencode
from huggingface_hub import HfApi, create_repo, repo_exists

app = Flask(__name__)

# ---------- CORS ----------
CORS(app, resources={r"/*": {
    "origins": "*",
    "allow_headers": ["Content-Type", "Authorization"],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
}})

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = make_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.status_code = 200
        return response

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

# ---------- Configuration ----------
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY")
GROQ_API_URL       = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME         = "llama-3.3-70b-versatile"

GITHUB_CLIENT_ID     = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
FRONTEND_URL         = os.environ.get("FRONTEND_URL", "https://suryasticsai.github.io/GrishteSync/")
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL     = "https://github.com/login/oauth/access_token"
GITHUB_API_URL       = "https://api.github.com"

HF_API_TOKEN = os.environ.get("HF_API_TOKEN")

# ---------- Multi‑Prompt Loader ----------
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')

def load_prompt(prompt_type):
    filename = f"{prompt_type}.txt"
    filepath = os.path.join(PROMPTS_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        fallback = os.path.join(PROMPTS_DIR, 'generate.txt')
        try:
            with open(fallback, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except:
            return "You are an expert Python developer. Return ONLY valid JSON with a 'files' key."
    except Exception as e:
        print(f"Error loading prompt {prompt_type}: {e}")
        return "You are an expert Python developer. Return ONLY valid JSON with a 'files' key."

# ---------- Helpers ----------
def safe_json(resp):
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct:
        return None, f"Got HTML instead of JSON (status {resp.status_code}): {resp.text[:300]}"
    try:
        return resp.json(), None
    except Exception as e:
        return None, f"JSON parse failed (status {resp.status_code}): {resp.text[:300]}"

def sanitize_space_name(name):
    name = re.sub(r'[^a-zA-Z0-9-]', '-', name)
    name = re.sub(r'-+', '-', name)
    name = name.strip('-')
    return name[:96] or "grishte-app"

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
    try:
        resp = requests.post(GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{request.host_url.rstrip('/')}/auth/callback"
            },
            timeout=15
        )
        data, err = safe_json(resp)
        if err:
            return jsonify({"error": "GitHub token exchange failed", "details": err}), 500
        if "access_token" not in data:
            return jsonify({"error": "GitHub token error", "details": data}), 500

        access_token = data["access_token"]
        user_resp = requests.get(f"{GITHUB_API_URL}/user",
                                 headers={"Authorization": f"Bearer {access_token}"},
                                 timeout=10)
        user_data, user_err = safe_json(user_resp)
        username = user_data.get("login", "") if user_data else ""

        return redirect(f"{FRONTEND_URL}?token={access_token}&github_user={username}")

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- AI Generation ----------
@app.route("/api/generate", methods=["POST"])
def generate():
    start_time = time.time()
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    prompt = data.get("prompt", "").strip()
    prompt_type = data.get("prompt_type", "generate")
    repo_full_name = data.get("repo")
    user_token = None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        user_token = auth_header.split(" ", 1)[1]
    elif auth_header.startswith("token "):
        user_token = auth_header.split(" ", 1)[1]

    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    system_prompt = load_prompt(prompt_type)

    if prompt_type == "fix":
        user_message = f"Fix the bug in this app: {prompt}"
    elif prompt_type == "improve_ui":
        user_message = f"Improve the UI/UX of this app: {prompt}"
    elif prompt_type == "add_feature":
        user_message = f"Add the following feature to the app: {prompt}"
    elif prompt_type == "refactor":
        user_message = f"Refactor the code of this app: {prompt}"
    elif prompt_type == "diagnose":
        user_message = f"Diagnose the following error and provide a fixed version of the code: {prompt}"
    else:
        user_message = f"Build a web app: {prompt}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    if repo_full_name and user_token:
        try:
            gh_headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github.v3+json"}
            contents_resp = requests.get(f"{GITHUB_API_URL}/repos/{repo_full_name}/contents", headers=gh_headers, timeout=15)
            if contents_resp.status_code == 200:
                existing_code = {}
                for item in contents_resp.json():
                    if item["type"] == "file" and item.get("size", 0) < 500000:
                        try:
                            existing_code[item["name"]] = requests.get(item["download_url"], timeout=10).text
                        except:
                            pass
                if existing_code:
                    context = "Current codebase:\n"
                    for fname, content in existing_code.items():
                        context += f"\n--- {fname} ---\n{content}\n"
                    messages.insert(0, {"role": "system", "content": context})
        except:
            pass

    def call_groq(msgs):
        resp = requests.post(GROQ_API_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL_NAME, "messages": msgs, "temperature": 0.3},
            timeout=60
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def parse_ai_response(ai_content):
        ai_content = re.sub(r'^```(?:json)?\s*', '', ai_content.strip())
        ai_content = re.sub(r'\s*```$', '', ai_content.strip())
        start_idx = ai_content.find('{')
        end_idx = ai_content.rfind('}')
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return None, "No JSON object found"
        ai_content = ai_content[start_idx:end_idx + 1]
        ai_content = re.sub(r',\s*}', '}', ai_content)
        ai_content = re.sub(r',\s*]', ']', ai_content)

        def fix_newlines(text):
            result, in_string, escape_next = [], False, False
            for char in text:
                if escape_next:
                    result.append(char); escape_next = False; continue
                if char == '\\':
                    result.append(char); escape_next = True; continue
                if char == '"':
                    in_string = not in_string; result.append(char); continue
                if in_string:
                    if char == '\n': result.append('\\n')
                    elif char == '\t': result.append('\\t')
                    elif char == '\r': pass
                    else: result.append(char)
                else:
                    result.append(char)
            return ''.join(result)

        ai_content = fix_newlines(ai_content)
        errors = []

        try:
            return json.loads(ai_content), None
        except json.JSONDecodeError as e1:
            errors.append(f"json: {e1}")

        try:
            import ast
            result = ast.literal_eval(ai_content)
            if isinstance(result, dict):
                return result, None
        except Exception as e2:
            errors.append(f"ast: {e2}")

        try:
            ob, cb = ai_content.count('{'), ai_content.count('}')
            fixed = ai_content
            if ob > cb: fixed += '}' * (ob - cb)
            elif cb > ob: fixed = '{' * (cb - ob) + fixed
            return json.loads(fixed), None
        except Exception as e3:
            errors.append(f"brace: {e3}")

        return None, " | ".join(errors)

    try:
        ai_content = call_groq(messages)
        generated, error = parse_ai_response(ai_content)

        if generated is None:
            messages.append({"role": "assistant", "content": ai_content})
            messages.append({"role": "user", "content": "Your response was not valid JSON. Output ONLY valid JSON with a 'files' key. Start with { and end with }."})
            try:
                ai_content = call_groq(messages)
                generated, error = parse_ai_response(ai_content)
            except Exception as re_err:
                return jsonify({"error": "Retry failed", "details": str(re_err)}), 500

        if generated is None:
            return jsonify({"error": "Failed to parse AI response after retry", "parse_error": error, "response_preview": ai_content[:800]}), 500

        if "files" not in generated:
            generated = {"files": generated}

        generated["generate_time"] = round(time.time() - start_time, 1)
        return jsonify(generated)

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

# ---------- Deploy to GitHub ----------
@app.route("/api/deploy", methods=["POST"])
def deploy():
    start_time = time.time()
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        user_token = auth_header.split(" ", 1)[1]
    elif auth_header.startswith("token "):
        user_token = auth_header.split(" ", 1)[1]
    else:
        return jsonify({"error": "Missing GitHub token"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    repo_name = data.get("repo_name")
    files = data.get("files", {})
    version = data.get("version", "0.0.0")

    if not repo_name:
        return jsonify({"error": "repo_name is required"}), 400

    gh_headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github.v3+json"}

    try:
        user_resp = requests.get(f"{GITHUB_API_URL}/user", headers=gh_headers, timeout=10)
        user_data, err = safe_json(user_resp)
        if err or user_resp.status_code != 200:
            return jsonify({"error": "Invalid GitHub token"}), 401
        username = user_data["login"]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    repo_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}"

    try:
        check = requests.get(repo_url, headers=gh_headers, timeout=10)
        if check.status_code == 404:
            create_resp = requests.post(f"{GITHUB_API_URL}/user/repos", headers=gh_headers,
                                        json={"name": repo_name, "private": False, "auto_init": True}, timeout=15)
            if create_resp.status_code not in [200, 201]:
                return jsonify({"error": f"Failed to create repo (status {create_resp.status_code})", "details": create_resp.text[:300]}), 500
            time.sleep(3)
        elif check.status_code != 200:
            return jsonify({"error": f"Unexpected status checking repo: {check.status_code}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        repo_info, err = safe_json(requests.get(repo_url, headers=gh_headers, timeout=10))
        if err:
            return jsonify({"error": "Could not read repo info"}), 500
        default_branch = repo_info.get("default_branch", "main")
    except:
        return jsonify({"error": "Repo info fetch failed"}), 500

    branch_name = f"agent/feature-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    sha = None
    for attempt in range(5):
        try:
            ref_resp = requests.get(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs/heads/{default_branch}", headers=gh_headers, timeout=10)
            if ref_resp.status_code == 200:
                ref_data, err = safe_json(ref_resp)
                if not err and ref_data:
                    sha = ref_data["object"]["sha"]
                    break
        except:
            pass
        time.sleep(2)
    
    if not sha:
        return jsonify({"error": "Failed to get branch SHA after 5 attempts"}), 500

    try:
        create_ref = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs", headers=gh_headers,
                                   json={"ref": f"refs/heads/{branch_name}", "sha": sha}, timeout=10)
        if create_ref.status_code == 422:
            branch_name = f"agent/feature-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(3).hex()}"
            create_ref = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs", headers=gh_headers,
                                       json={"ref": f"refs/heads/{branch_name}", "sha": sha}, timeout=10)
        if create_ref.status_code not in [200, 201]:
            detail, _ = safe_json(create_ref)
            return jsonify({"error": f"Failed to create branch (status {create_ref.status_code})", "details": detail or create_ref.text[:300]}), 500
    except Exception as e:
        return jsonify({"error": f"Branch creation exception: {str(e)}"}), 500

    for filepath, content in files.items():
        try:
            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            api_path = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{filepath}"
            payload = {"message": f"Update {filepath} via GrishteSync v{version}", "content": encoded, "branch": branch_name}
            file_check = requests.get(f"{api_path}?ref={branch_name}", headers=gh_headers, timeout=10)
            if file_check.status_code == 200:
                fdata, _ = safe_json(file_check)
                if fdata and fdata.get("sha"):
                    payload["sha"] = fdata["sha"]
            put_resp = requests.put(api_path, headers=gh_headers, json=payload, timeout=15)
            if put_resp.status_code not in [200, 201]:
                return jsonify({"error": f"Push failed for {filepath} (status {put_resp.status_code})", "details": put_resp.text[:300]}), 500
        except Exception as e:
            return jsonify({"error": f"File push exception for {filepath}: {str(e)}"}), 500

    try:
        custom_description = data.get("pr_description")
        pr_body = custom_description if custom_description else (
            f"## 🌀 GrishteSync Automatic Pull Request\n\n"
            f"**Version:** v{version}\n\n"
            f"**Files changed:**\n" +
            "\n".join([f"- `{f}`" for f in files.keys()]) + "\n\n"
            f"*Created with [GrishteSync](https://suryasticsai.github.io/GrishteSync)*"
        )
        pr_resp = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/pulls", headers=gh_headers,
                                json={"title": f"GrishteSync update v{version}", "head": branch_name, "base": default_branch, "body": pr_body}, timeout=15)
        pr_data, _ = safe_json(pr_resp)
        pr_url = pr_data.get("html_url") if pr_data and pr_resp.status_code in [200, 201] else None
    except:
        pr_url = None

    return jsonify({
        "status": "success",
        "repo_url": f"https://github.com/{username}/{repo_name}",
        "branch": branch_name,
        "pr_url": pr_url,
        "username": username,
        "deploy_time": round(time.time() - start_time, 1)
    })

# ---------- Deploy to Hugging Face (using huggingface_hub) ----------
@app.route("/api/deploy-hf", methods=["POST"])
def deploy_hf():
    start_time = time.time()
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400

        repo_full_name = data.get("repo_full_name")
        if not repo_full_name:
            return jsonify({"error": "repo_full_name is required"}), 400

        if not HF_API_TOKEN:
            return jsonify({"error": "HF_API_TOKEN not configured on server"}), 500

        if "/" in repo_full_name:
            raw_space_name = data.get("space_name", repo_full_name.split("/")[1])
        else:
            raw_space_name = data.get("space_name", repo_full_name)

        space_name = sanitize_space_name(raw_space_name)
        sdk = data.get("sdk", "streamlit")
        files = data.get("files", {})

        # Framework detection
        framework = None
        for filename, content in files.items():
            if filename.endswith(".py"):
                lower = content.lower()
                if "flask" in lower:
                    framework = "flask"
                    break
                elif "gradio" in lower:
                    framework = "gradio"
                    break
                elif "streamlit" in lower:
                    framework = "streamlit"
                    break

        if framework == "flask":
            sdk = "docker"
        elif framework == "gradio":
            sdk = "gradio"
        elif framework == "streamlit":
            sdk = "streamlit"

        # Framework-specific fixes
        if sdk == "docker":
            if "requirements.txt" not in files:
                files["requirements.txt"] = "flask\nhuggingface_hub\n"
            else:
                req = files["requirements.txt"]
                if "flask" not in req.lower():
                    req += "\nflask\n"
                if "huggingface_hub" not in req.lower():
                    req += "\nhuggingface_hub\n"
                files["requirements.txt"] = req
            if "Dockerfile" not in files:
                files["Dockerfile"] = """FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "app.py"]
""".strip()
            for fname, content in files.items():
                if fname.endswith(".py") and "app.run" in content:
                    if "port=7860" not in content.lower():
                        new = content.replace("app.run()", "app.run(host='0.0.0.0', port=7860)")
                        new = new.replace("app.run(debug=True)", "app.run(host='0.0.0.0', port=7860, debug=True)")
                        files[fname] = new

        elif sdk == "gradio":
            if "requirements.txt" not in files:
                files["requirements.txt"] = "gradio\nhuggingface_hub\n"
            else:
                req = files["requirements.txt"]
                if "gradio" not in req.lower():
                    req += "\ngradio\n"
                if "huggingface_hub" not in req.lower():
                    req += "\nhuggingface_hub\n"
                files["requirements.txt"] = req
            for fname, content in files.items():
                if fname.endswith(".py") and "launch" in content:
                    new_content = content
                    new_content = re.sub(r'enable_queue\s*=\s*True\s*,?\s*', '', new_content)
                    new_content = re.sub(r'enable_queue\s*=\s*False\s*,?\s*', '', new_content)
                    new_content = re.sub(r'inline\s*=\s*False\s*,?\s*', '', new_content)
                    new_content = re.sub(r'inline\s*=\s*True\s*,?\s*', '', new_content)
                    new_content = re.sub(r'show_error\s*=\s*False\s*,?\s*', '', new_content)
                    new_content = re.sub(r'show_error\s*=\s*True\s*,?\s*', '', new_content)
                    if "server_name" not in new_content:
                        new_content = new_content.replace(".launch(", ".launch(server_name='0.0.0.0', server_port=7860, ")
                    elif "server_port" not in new_content:
                        new_content = new_content.replace(".launch(", ".launch(server_port=7860, ")
                    new_content = re.sub(r',\s*,', ',', new_content)
                    new_content = re.sub(r',\s*\)', ')', new_content)
                    files[fname] = new_content

        elif sdk == "streamlit":
            if "requirements.txt" not in files:
                files["requirements.txt"] = "streamlit\nhuggingface_hub\n"
            else:
                req = files["requirements.txt"]
                if "streamlit" not in req.lower():
                    req += "\nstreamlit\n"
                if "huggingface_hub" not in req.lower():
                    req += "\nhuggingface_hub\n"
                files["requirements.txt"] = req

        # Auto-generate README.md with correct frontmatter
        if "README.md" not in files:
            if sdk == "docker":
                readme_content = f"""---
title: {space_name}
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
sdk_version: "3.9"
app_file: app.py
pinned: false
---

# {space_name}
Deployed automatically by GrishteSync.
"""
            elif sdk == "gradio":
                readme_content = f"""---
title: {space_name}
emoji: 🎨
colorFrom: purple
colorTo: pink
sdk: gradio
sdk_version: "4.0"
app_file: app.py
pinned: false
---

# {space_name}
Gradio app built with GrishteSync.
"""
            else:
                readme_content = f"""---
title: {space_name}
emoji: 📊
colorFrom: red
colorTo: yellow
sdk: streamlit
sdk_version: "1.28"
app_file: app.py
pinned: false
---

# {space_name}
Streamlit app built with GrishteSync.
"""
            files["README.md"] = readme_content

        # Use huggingface_hub to create and upload
        api = HfApi(token=HF_API_TOKEN)
        
        try:
            whoami = api.whoami()
            hf_username = whoami["name"]
        except Exception as e:
            return jsonify({"error": f"Invalid HF token: {str(e)}"}), 401

        repo_id = f"{hf_username}/{space_name}"
        
        # Check if space exists, create if not
        try:
            if not repo_exists(repo_id, repo_type="space", token=HF_API_TOKEN):
                # Create space with proper SDK
                create_repo(
                    repo_id=repo_id,
                    repo_type="space",
                    space_sdk=sdk,
                    token=HF_API_TOKEN,
                    exist_ok=True
                )
                time.sleep(5)  # Wait for space initialization
        except Exception as e:
            # Some versions of huggingface_hub may have different parameters
            # Fallback: try without space_sdk
            try:
                create_repo(
                    repo_id=repo_id,
                    repo_type="space",
                    token=HF_API_TOKEN,
                    exist_ok=True
                )
                time.sleep(5)
            except Exception as e2:
                return jsonify({"error": f"Failed to create Space: {str(e2)}"}), 500

        # Upload all files
        for filepath, content in files.items():
            file_obj = io.BytesIO(content.encode("utf-8"))
            try:
                api.upload_file(
                    path_or_fileobj=file_obj,
                    path_in_repo=filepath,
                    repo_id=repo_id,
                    repo_type="space",
                    token=HF_API_TOKEN
                )
            except Exception as e:
                return jsonify({"error": f"Failed to upload {filepath}: {str(e)}"}), 500

        space_url = f"https://huggingface.co/spaces/{repo_id}"

        # Update GitHub README with HF badge (if GitHub token provided)
        github_token = data.get("github_token") or request.headers.get("Authorization", "").replace("Bearer ", "").replace("token ", "")
        if github_token and repo_full_name and "/" in repo_full_name:
            try:
                gh_headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github.v3+json"}
                readme_resp = requests.get(f"{GITHUB_API_URL}/repos/{repo_full_name}/contents/README.md", headers=gh_headers)
                readme_content = ""
                readme_sha = None
                if readme_resp.status_code == 200:
                    readme_data = readme_resp.json()
                    readme_content = base64.b64decode(readme_data["content"]).decode("utf-8")
                    readme_sha = readme_data["sha"]
                badge_md = f"\n\n[![Hugging Face Space](https://img.shields.io/badge/🤗-Open%20in%20Spaces-blue)]({space_url})\n"
                if badge_md not in readme_content:
                    readme_content += badge_md
                    encoded_new = base64.b64encode(readme_content.encode("utf-8")).decode("utf-8")
                    payload = {"message": "Add Hugging Face Space link", "content": encoded_new, "branch": "main"}
                    if readme_sha:
                        payload["sha"] = readme_sha
                    requests.put(f"{GITHUB_API_URL}/repos/{repo_full_name}/contents/README.md", headers=gh_headers, json=payload)
            except:
                pass

        return jsonify({
            "status": "success",
            "space_url": space_url,
            "space_full_name": repo_id,
            "sdk": sdk,
            "deploy_time": round(time.time() - start_time, 1)
        })

    except Exception as e:
        return jsonify({
            "error": "Internal server error in deploy_hf",
            "details": str(e),
            "trace": traceback.format_exc()
        }), 500

# ---------- Get repo files ----------
@app.route("/api/repo-files", methods=["POST"])
def get_repo_files():
    data = request.get_json()
    repo_full_name = data.get("repo")
    user_token = data.get("token")
    if not repo_full_name or not user_token:
        return jsonify({"error": "Missing repo or token"}), 400

    gh_headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github.v3+json"}
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/contents"
    try:
        resp = requests.get(url, headers=gh_headers, timeout=15)
        if resp.status_code != 200:
            return jsonify({"error": f"GitHub API error: {resp.status_code}"}), 500
        items = resp.json()
        files = []
        for item in items:
            if item["type"] == "file" and item["size"] < 500000:
                files.append({
                    "name": item["name"],
                    "path": item["path"],
                    "download_url": item["download_url"],
                    "sha": item["sha"]
                })
            elif item["type"] == "dir":
                sub_resp = requests.get(item["url"], headers=gh_headers)
                if sub_resp.status_code == 200:
                    for sub in sub_resp.json():
                        if sub["type"] == "file" and sub["size"] < 500000:
                            files.append({
                                "name": sub["name"],
                                "path": sub["path"],
                                "download_url": sub["download_url"],
                                "sha": sub["sha"]
                            })
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Get HF logs ----------
@app.route("/api/hf-logs", methods=["POST"])
def get_hf_logs():
    data = request.get_json()
    space_name = data.get("space_name")
    if not space_name:
        return jsonify({"error": "Missing space_name"}), 400
    hf_token = HF_API_TOKEN
    headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}
    try:
        logs_url = f"https://huggingface.co/api/spaces/{space_name}/logs"
        resp = requests.get(logs_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            logs = resp.json()
            return jsonify({"logs": logs})
        else:
            return jsonify({"logs": [], "error": f"Status {resp.status_code}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Diagnose & Fix ----------
@app.route("/api/diagnose", methods=["POST"])
def diagnose():
    data = request.get_json()
    error_log = data.get("error_log", "")
    code = data.get("code", "")
    if not error_log:
        return jsonify({"error": "Missing error_log"}), 400

    system_prompt = """You are an expert debugging assistant. Given an error log and the code that caused it, provide a fixed version of the code.

Return ONLY a JSON object with a "files" key containing the corrected files. Only include files that need to be changed.

Example: {"files": {"app.py": "fixed code here", "requirements.txt": "updated packages"}}

Do not include any explanations or markdown outside the JSON."""
    user_message = f"Error log:\n{error_log}\n\nCurrent code:\n{code}\n\nPlease provide the fixed code."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    try:
        resp = requests.post(GROQ_API_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL_NAME, "messages": messages, "temperature": 0.2},
            timeout=60
        )
        resp.raise_for_status()
        ai_content = resp.json()["choices"][0]["message"]["content"].strip()
        ai_content = re.sub(r'^```(?:json)?\s*', '', ai_content)
        ai_content = re.sub(r'\s*```$', '', ai_content)
        start_idx = ai_content.find('{')
        end_idx = ai_content.rfind('}')
        if start_idx != -1 and end_idx != -1:
            ai_content = ai_content[start_idx:end_idx+1]
        fixed = json.loads(ai_content)
        if "files" not in fixed:
            fixed = {"files": fixed}
        return jsonify(fixed)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Health check ----------
@app.route("/")
def health():
    return jsonify({"status": "GrishteSync backend running", "version": "0.9"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
