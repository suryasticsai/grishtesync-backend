# GrishteSync v0.1
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

# ---------- Hugging Face OAuth ----------
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

@app.route("/hf/callback")
def hf_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing code"}), 400

    resp = requests.post(HF_TOKEN_URL, data={
        "client_id": HF_CLIENT_ID,
        "client_secret": HF_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": f"{request.host_url.rstrip('/')}/hf/callback"
    })
    data = resp.json()
    if "access_token" not in data:
        return jsonify({"error": "HF token error", "details": data}), 500

    access_token = data["access_token"]
    return redirect(f"{FRONTEND_URL}?hf_token={access_token}")

# ---------- AI Generation with robust JSON parser ----------
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
        "YOU MUST RETURN ONLY A VALID JSON OBJECT. No markdown, no explanations, no code fences. Just pure JSON.\n\n"
        "Format: {\"files\": {\"filename.py\": \"code here\", \"filename2.txt\": \"content here\"}}\n\n"
        "CRITICAL RULES FOR VALID JSON:\n"
        "- Use double quotes for all keys and string values\n"
        "- Escape any double quotes inside strings with backslash: \\\"\n"
        "- Use \\n for newlines inside code strings\n"
        "- No trailing commas\n"
        "- No single quotes for strings\n"
        "- The response must start with { and end with }\n\n"
        "Important watermark rules:\n"
        "1. Every Python file must start with this exact comment:\n"
        "# Created with GrishteSync\n"
        "# https://suryasticsai.github.io/GrishteSync\n"
        "# Suryasticsai | suryasticsai@gmail.com\n"
        "2. The main app file (app.py) must include a visible footer that shows:\n"
        "   'Made with GrishteSync | Suryasticsai | suryasticsai@gmail.com'\n"
        "   and a link to https://suryasticsai.github.io/GrishteSync.\n"
        "3. The main app must show the GrishteSync logo as a header or footer image.\n"
        "   Use this exact URL: https://i.ibb.co/RGmb4FKk/1781072041102.png\n"
        "   For Streamlit: st.image('https://i.ibb.co/RGmb4FKk/1781072041102.png', width=200)\n"
        "   For Gradio: gr.HTML('<img src=\"https://i.ibb.co/RGmb4FKk/1781072041102.png\" width=\"200\">')\n"
        "4. The README.md must contain a 'Built with GrishteSync' section with:\n"
        "   - GitHub: https://github.com/suryasticsai\n"
        "   - LinkedIn: https://linkedin.com/in/suryasticsai\n"
        "   - Email: suryasticsai@gmail.com\n"
        "   - Logo: ![GrishteSync Logo](https://i.ibb.co/RGmb4FKk/1781072041102.png)\n"
        "5. Include a requirements.txt with all dependencies.\n"
        "6. For a meaningless prompt, create a minimal app that simply shows the user's input text."
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

    # Helper function to call Groq
    def call_groq(messages_list):
        resp = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL_NAME, "messages": messages_list, "temperature": 0.3}
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    # Helper to parse AI response
    def parse_ai_response(ai_content):
        # Remove markdown code fences
        ai_content = re.sub(r'^```(?:json)?\s*', '', ai_content.strip())
        ai_content = re.sub(r'\s*```$', '', ai_content.strip())
        
        # Find JSON boundaries
        start_idx = ai_content.find('{')
        end_idx = ai_content.rfind('}')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            ai_content = ai_content[start_idx:end_idx + 1]
        else:
            return None, "No JSON object found"
        
        # Fix trailing commas
        ai_content = re.sub(r',\s*}', '}', ai_content)
        ai_content = re.sub(r',\s*]', ']', ai_content)
        
        # Fix unescaped newlines in strings
        def fix_newlines(text):
            result = []
            in_string = False
            escape_next = False
            for char in text:
                if escape_next:
                    result.append(char)
                    escape_next = False
                    continue
                if char == '\\':
                    result.append(char)
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
                    result.append(char)
                    continue
                if in_string and char == '\n':
                    result.append('\\n')
                elif in_string and char == '\t':
                    result.append('\\t')
                elif in_string and char == '\r':
                    result.append('')
                else:
                    result.append(char)
            return ''.join(result)
        
        ai_content = fix_newlines(ai_content)
        
        # Try parsing
        errors = []
        
        try:
            return json.loads(ai_content), None
        except json.JSONDecodeError as e1:
            errors.append(f"JSON parse: {str(e1)}")
            
            try:
                import ast
                result = ast.literal_eval(ai_content)
                if isinstance(result, dict):
                    return result, None
                return None, "AST result not a dict"
            except Exception as e2:
                errors.append(f"AST parse: {str(e2)}")
                
                try:
                    open_braces = ai_content.count('{')
                    close_braces = ai_content.count('}')
                    fixed = ai_content
                    if open_braces > close_braces:
                        fixed += '}' * (open_braces - close_braces)
                    elif close_braces > open_braces:
                        fixed = '{' * (close_braces - open_braces) + fixed
                    result = json.loads(fixed)
                    return result, None
                except Exception as e3:
                    errors.append(f"Brace fix: {str(e3)}")
        
        return None, "; ".join(errors)

    try:
        # First attempt
        ai_content = call_groq(messages)
        generated, error = parse_ai_response(ai_content)
        
        # If first attempt fails, ask Groq to fix it
        if generated is None:
            # Add the failed response and ask for correction
            messages.append({"role": "assistant", "content": ai_content})
            messages.append({
                "role": "user", 
                "content": "Your response was not valid JSON. Please output ONLY a valid JSON object with the 'files' key. Start with { and end with }. No markdown, no explanations."
            })
            
            try:
                ai_content_retry = call_groq(messages)
                generated, error = parse_ai_response(ai_content_retry)
            except Exception as retry_error:
                return jsonify({
                    "error": "Retry failed",
                    "first_response": ai_content[:500],
                    "retry_error": str(retry_error)
                }), 500
        
        # If still failing, return debug info
        if generated is None:
            return jsonify({
                "error": f"Failed to parse AI response after retry: {error}",
                "first_response": ai_content[:1000],
                "parse_error": error
            }), 500

        if "files" not in generated:
            generated = {"files": generated}

        return jsonify(generated)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Deploy to GitHub (SHA fix) ----------
@app.route("/api/deploy", methods=["POST"])
def deploy():
    import time  # Add at the top of the function
    
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

    # Create or get repo
    repo_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}"
    check = requests.get(repo_url, headers=headers)
    if check.status_code != 200:
        create_resp = requests.post(f"{GITHUB_API_URL}/user/repos", headers=headers,
                                    json={"name": repo_name, "private": False, "auto_init": True})
        if create_resp.status_code not in [200, 201]:
            return jsonify({"error": f"Failed to create repo: {create_resp.text}"}), 500
        
        # Wait for GitHub to finish initializing the repo
        time.sleep(3)

    repo_info = requests.get(repo_url, headers=headers).json()
    default_branch = repo_info.get("default_branch", "main")

    # Create feature branch (with retry)
    branch_name = f"agent/feature-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    ref_resp = None
    for attempt in range(5):
        ref_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs/heads/{default_branch}"
        ref_resp = requests.get(ref_url, headers=headers)
        if ref_resp.status_code == 200:
            break
        time.sleep(2)
    
    if not ref_resp or ref_resp.status_code != 200:
        return jsonify({
            "error": "Failed to read default branch ref after retries.",
            "details": ref_resp.text if ref_resp else "No response"
        }), 500

    sha = ref_resp.json()["object"]["sha"]
    new_ref_data = {"ref": f"refs/heads/{branch_name}", "sha": sha}
    create_ref = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs", headers=headers, json=new_ref_data)
    if create_ref.status_code != 201:
        return jsonify({"error": f"Failed to create branch: {create_ref.text}"}), 500

    # Push files
    for filepath, content in files.items():
        encoded = base64.b64encode(content.encode()).decode()
        api_path = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{filepath}"
        commit_msg = f"Update {filepath} via GrishteSync v{version}"
        payload = {
            "message": commit_msg,
            "content": encoded,
            "branch": branch_name
        }
        # Check if file exists on THIS branch to get SHA
        file_check = requests.get(f"{api_path}?ref={branch_name}", headers=headers)
        if file_check.status_code == 200:
            existing_sha = file_check.json().get("sha")
            if existing_sha:
                payload["sha"] = existing_sha
        
        put_resp = requests.put(api_path, headers=headers, json=payload)
        if put_resp.status_code not in [200, 201]:
            return jsonify({
                "error": f"Push failed for {filepath}",
                "status": put_resp.status_code,
                "details": put_resp.text
            }), 500

    # Create PR
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
            f"![GrishteSync Logo](https://i.ibb.co/RGmb4FKk/1781072041102.png)"
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
# ---------- Hugging Face Deploy (better error handling) ----------
@app.route("/api/deploy-hf", methods=["POST"])
def deploy_hf():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("token "):
        return jsonify({"error": "Missing GitHub token"}), 401
    github_token = auth_header.split(" ", 1)[1]

    hf_header = request.headers.get("HF-Authorization")
    if not hf_header or not hf_header.startswith("Bearer "):
        return jsonify({"error": "Missing Hugging Face token. Please reconnect Hugging Face."}), 401
    hf_token = hf_header.split(" ", 1)[1]

    data = request.get_json()
    repo_full_name = data.get("repo_full_name")
    space_name = data.get("space_name", repo_full_name.split("/")[1] if repo_full_name else "grishte-app")
    sdk = data.get("sdk", "streamlit")
    files = data.get("files", {})
    
    # ---------- Auto-detect framework ----------
    if files:
        for filename, content in files.items():
            if filename.endswith('.py') and ('app' in filename.lower() or 'main' in filename.lower()):
                content_lower = content.lower()
                if 'gradio' in content_lower:
                    sdk = "gradio"
                    break
                elif 'streamlit' in content_lower:
                    sdk = "streamlit"
                    break
                elif 'flask' in content_lower:
                    sdk = "docker"
                    break
        for filename, content in files.items():
            if filename == 'requirements.txt':
                content_lower = content.lower()
                if 'gradio' in content_lower and sdk != "docker":
                    sdk = "gradio"
                elif 'streamlit' in content_lower and sdk != "docker":
                    sdk = "streamlit"
                elif 'flask' in content_lower:
                    sdk = "docker"
                break

    if not repo_full_name:
        return jsonify({"error": "repo_full_name required"}), 400

    # ---------- Validate Hugging Face token ----------
    try:
        whoami_resp = requests.get(
            f"{HF_API_URL}/whoami",
            headers={"Authorization": f"Bearer {hf_token}"}
        )
        
        content_type = whoami_resp.headers.get("Content-Type", "")
        if "text/html" in content_type:
            return jsonify({
                "error": "Hugging Face token is invalid or expired. Please reconnect Hugging Face.",
                "preview": whoami_resp.text[:200]
            }), 401
        
        if whoami_resp.status_code != 200:
            return jsonify({
                "error": f"Hugging Face authentication failed (status {whoami_resp.status_code})",
                "details": whoami_resp.text[:300]
            }), 401
        
        hf_username = whoami_resp.json()["name"]
    except Exception as e:
        return jsonify({
            "error": f"Failed to verify HF token: {str(e)}"
        }), 401

    # ---------- Create Space dynamically ----------
    space_url = f"{HF_API_URL}/spaces/{hf_username}/{space_name}"
    check = requests.get(space_url)
    
    if check.status_code == 404:
        # Space doesn't exist — create it
        create_data = {
            "sdk": sdk,
            "hardware": "cpu-basic",
            "name": space_name,
            "private": False
        }
        
        create_resp = requests.post(
            f"{HF_API_URL}/spaces",
            json=create_data,
            headers={"Authorization": f"Bearer {hf_token}"}
        )
        
        if create_resp.status_code not in [200, 201]:
            return jsonify({
                "error": f"Failed to create Space (status {create_resp.status_code})",
                "details": create_resp.text[:500]
            }), 500
        
        import time
        time.sleep(3)  # Wait for Space initialization
    
    elif check.status_code != 200:
        return jsonify({
            "error": f"Unexpected response checking Space (status {check.status_code})",
            "details": check.text[:300]
        }), 500
    else:
        # Space exists — update SDK if needed
        existing_sdk = check.json().get("sdk", "")
        if existing_sdk != sdk:
            # Update the Space SDK (if HF API supports it — for now just warn)
            pass

    # ---------- Link GitHub repo to Space ----------
    link_resp = requests.post(
        f"{HF_API_URL}/spaces/{hf_username}/{space_name}/repo",
        headers={"Authorization": f"Bearer {hf_token}"},
        json={
            "repo_id": repo_full_name,
            "repo_type": "github",
            "oauth_token": github_token
        }
    )
    
    if link_resp.status_code not in [200, 201]:
        return jsonify({
            "error": f"Failed to link repo (status {link_resp.status_code})",
            "details": link_resp.text[:500]
        }), 500

    return jsonify({
        "status": "success",
        "space_url": f"https://huggingface.co/spaces/{hf_username}/{space_name}",
        "sdk": sdk
    })
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
