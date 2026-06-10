# GrishteSync v0.3 - Backend with Progress Timing
import os
import re
import json
import base64
import time
import traceback
import datetime
import requests
from flask import Flask, request, jsonify, redirect, make_response
from flask_cors import CORS
from urllib.parse import urlencode

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
HF_API_URL   = "https://huggingface.co/api"

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
        return redirect(f"{FRONTEND_URL}?token={data['access_token']}&github_user={data.get('login','')}")
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
    repo_full_name = data.get("repo")
    user_token = None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("token "):
        user_token = auth_header.split(" ", 1)[1]

    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    system_prompt = (
        "You are an expert Python developer. "
        "Return ONLY a valid JSON object. No markdown, no explanations. Just pure JSON.\n\n"
        'Format: {"files": {"filename.py": "code here", "filename2.txt": "content here"}}\n\n'
        "CRITICAL RULES:\n"
        "- Use double quotes for all keys and strings\n"
        "- Escape double quotes inside strings with backslash\n"
        "- Use \\n for newlines inside code strings\n"
        "- No trailing commas\n"
        "- Response must start with { and end with }\n\n"
        "Watermark rules:\n"
        "1. Every Python file must start with:\n"
        "# Created with GrishteSync\n"
        "# https://suryasticsai.github.io/GrishteSync\n"
        "# Suryasticsai | suryasticsai@gmail.com\n"
        "2. app.py must show footer: 'Made with GrishteSync | Suryasticsai | suryasticsai@gmail.com'\n"
        "3. Show logo: https://i.ibb.co/RGmb4FKk/1781072041102.png\n"
        "4. Include requirements.txt\n"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Build: {prompt}"}
    ]

    if repo_full_name and user_token:
        try:
            gh_headers = {"Authorization": f"token {user_token}", "Accept": "application/vnd.github.v3+json"}
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
    if not auth_header.startswith("token "):
        return jsonify({"error": "Missing GitHub token"}), 401
    user_token = auth_header.split(" ", 1)[1]

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    repo_name = data.get("repo_name")
    files = data.get("files", {})
    version = data.get("version", "0.0.0")

    if not repo_name:
        return jsonify({"error": "repo_name is required"}), 400

    gh_headers = {"Authorization": f"token {user_token}", "Accept": "application/vnd.github.v3+json"}

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
            f"*Created with [GrishteSync](https://suryasticsai.github.io/GrishteSync)*\n\n"
            f"![GrishteSync Logo](https://i.ibb.co/RGmb4FKk/1781072041102.png)"
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

# ---------- Deploy to Hugging Face ----------

@app.route("/api/deploy-hf", methods=["POST"])
def deploy_hf():
    start_time = time.time()
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    repo_full_name = data.get("repo_full_name")
    if not repo_full_name:
        return jsonify({"error": "repo_full_name is required"}), 400

    raw_space_name = data.get("space_name", repo_full_name.split("/")[1])
    space_name = sanitize_space_name(raw_space_name)
    sdk = data.get("sdk", "streamlit")
    files = data.get("files", {})

    for filename, content in files.items():
        lower = content.lower()
        if filename.endswith(".py") and ("app" in filename.lower() or "main" in filename.lower()):
            if "gradio" in lower: sdk = "gradio"; break
            if "streamlit" in lower: sdk = "streamlit"; break
            if "flask" in lower: sdk = "docker"; break
    for filename, content in files.items():
        if filename == "requirements.txt":
            lower = content.lower()
            if "gradio" in lower and sdk != "docker": sdk = "gradio"
            elif "streamlit" in lower and sdk != "docker": sdk = "streamlit"
            elif "flask" in lower: sdk = "docker"
            break

    if sdk not in ("gradio", "streamlit", "docker", "static"):
        sdk = "streamlit"

    hf_token = HF_API_TOKEN
    if not hf_token:
        return jsonify({"error": "HF_API_TOKEN not configured on server"}), 500

    try:
        whoami = requests.get("https://huggingface.co/api/whoami-v2",
                              headers={"Authorization": f"Bearer {hf_token}"}, timeout=15)
        if whoami.status_code != 200:
            return jsonify({"error": "HF token invalid", "details": whoami.text[:300]}), 500
        hf_username = whoami.json().get("name")
    except Exception as e:
        return jsonify({"error": f"HF whoami failed: {str(e)}"}), 500

    try:
        check = requests.get(f"{HF_API_URL}/spaces/{hf_username}/{space_name}",
                             headers={"Authorization": f"Bearer {hf_token}"}, timeout=15)
        if check.status_code == 404:
            create_payload = {"type": "space", "name": space_name, "sdk": sdk, "private": False, "exists_ok": True}
            create_resp = requests.post(f"{HF_API_URL}/repos/create",
                                        headers={"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"},
                                        json=create_payload, timeout=20)
            if create_resp.status_code not in [200, 201]:
                return jsonify({"error": f"Failed to create Space (status {create_resp.status_code})", "details": create_resp.text[:500]}), 500
            time.sleep(4)
        elif check.status_code != 200:
            return jsonify({"error": f"Unexpected status checking Space ({check.status_code})", "details": check.text[:300]}), 500
    except Exception as e:
        return jsonify({"error": f"Space check/create exception: {str(e)}"}), 500

    try:
        link_resp = requests.post(f"{HF_API_URL}/spaces/{hf_username}/{space_name}/repo",
                                  headers={"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"},
                                  json={"repo_id": repo_full_name, "repo_type": "github"}, timeout=20)
        if link_resp.status_code not in [200, 201]:
            return jsonify({"error": f"Failed to link repo (status {link_resp.status_code})", "details": link_resp.text[:500]}), 500
    except Exception as e:
        return jsonify({"error": f"Repo linking exception: {str(e)}"}), 500

    return jsonify({
        "status": "success",
        "space_url": f"https://huggingface.co/spaces/{hf_username}/{space_name}",
        "sdk": sdk,
        "deploy_time": round(time.time() - start_time, 1)
    })

# ---------- Health check ----------

@app.route("/")
def health():
    return jsonify({"status": "GrishteSync backend running", "version": "0.3"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
