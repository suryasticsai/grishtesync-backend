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

def load_prompt(filename):
    """Load a prompt template from the prompts/ folder."""
    prompt_path = os.path.join('prompts', filename)
    try:
        with open(prompt_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        app.logger.error(f"Prompt file not found: {prompt_path}")
        return ""

# ---------- GitHub OAuth Routes ----------

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
        # Fetch the username using the new token
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
    repo_full_name = data.get("repo")
    user_token = None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        user_token = auth_header.split(" ", 1)[1]
    elif auth_header.startswith("token "):
        user_token = auth_header.split(" ", 1)[1]

    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    # Extract app name from prompt
    app_name = prompt.split()[0].title() if prompt else "MyApp"
    if len(app_name) > 30:
        app_name = app_name[:30]

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

        files = generated.get("files", {})
        
        # Ensure requirements.txt exists
        if "requirements.txt" not in files:
            requirements = """# Requirements for GrishteSync generated app
flask>=2.0.0
python-dotenv>=1.0.0
requests>=2.28.0
"""
            files["requirements.txt"] = requirements

        generated["files"] = files
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

# ---------- Deploy to Hugging Face (FIXED) ----------

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

        # Get token from request or environment
        hf_token = data.get("token") or HF_API_TOKEN
        if not hf_token:
            return jsonify({"error": "HF API token required. Set HF_API_TOKEN environment variable or pass in request."}), 400

        raw_space_name = data.get("space_name", repo_full_name.split("/")[1])
        space_name = sanitize_space_name(raw_space_name)
        
        # Default to gradio (most common for HF Spaces)
        sdk = data.get("sdk", "gradio")
        files = data.get("files", {})

        if not files or len(files) == 0:
            return jsonify({"error": "No files to deploy"}), 500

        # Auto-detect SDK and ensure valid options
        detected_sdk = None
        for filename, content in files.items():
            if filename.endswith(".py"):
                content_lower = content.lower()
                if "gradio" in content_lower:
                    detected_sdk = "gradio"
                    break
                elif "streamlit" in content_lower:
                    # Streamlit apps should use "docker" as SDK
                    detected_sdk = "docker"
                    break
                elif "flask" in content_lower:
                    detected_sdk = "docker"
                    break

        # If we detected a valid SDK, use it. Otherwise default to gradio
        if detected_sdk:
            sdk = detected_sdk
        
        # Ensure SDK is one of the valid options for HF Spaces
        valid_sdks = ["gradio", "docker", "static"]
        if sdk not in valid_sdks:
            # If the user specified something invalid, default to gradio
            if "streamlit" in sdk.lower():
                sdk = "docker"  # Streamlit apps work with docker SDK
            else:
                sdk = "gradio"  # Fallback to gradio

        # Initialize Hugging Face API
        api = HfApi(token=hf_token)

        # Get username from token
        try:
            whoami = api.whoami()
            hf_username = whoami["name"]
        except Exception as e:
            return jsonify({"error": f"Invalid HF token: {str(e)}"}), 401

        repo_id = f"{hf_username}/{space_name}"

        # Check if space exists, create if not
        try:
            # First check if it exists
            space_exists = repo_exists(repo_id, repo_type="space", token=hf_token)
            
            if not space_exists:
                # Create the space with the correct SDK
                create_repo(
                    repo_id,
                    repo_type="space",
                    space_sdk=sdk,
                    token=hf_token,
                    exist_ok=True
                )
                time.sleep(5)  # Wait for space to initialize
            else:
                # Space exists, we'll just proceed
                pass
        except Exception as e:
            error_msg = str(e)
            # If it's a bad request with SDK error, try with gradio
            if "Invalid option" in error_msg or "expected one of" in error_msg:
                try:
                    # Try creating with gradio as fallback
                    create_repo(
                        repo_id,
                        repo_type="space",
                        space_sdk="gradio",
                        token=hf_token,
                        exist_ok=True
                    )
                    sdk = "gradio"
                    time.sleep(5)
                except Exception as e2:
                    return jsonify({
                        "error": f"Failed to create Space even with gradio fallback: {str(e2)}"
                    }), 500
            else:
                return jsonify({"error": f"Failed to create/access Space: {error_msg}"}), 500

        # Upload files one by one
        uploaded = []
        failed = []
        
        for filepath, content in files.items():
            try:
                # Skip if content is empty
                if not content or len(content.strip()) == 0:
                    continue
                    
                file_obj = io.BytesIO(content.encode("utf-8"))
                api.upload_file(
                    path_or_fileobj=file_obj,
                    path_in_repo=filepath,
                    repo_id=repo_id,
                    repo_type="space",
                    token=hf_token
                )
                uploaded.append(filepath)
            except Exception as e:
                failed.append(f"{filepath}: {str(e)}")

        # Check if any files were uploaded
        if not uploaded:
            return jsonify({
                "error": "No files were uploaded successfully",
                "failed": failed
            }), 500

        return jsonify({
            "status": "success",
            "space_url": f"https://huggingface.co/spaces/{repo_id}",
            "sdk": sdk,
            "uploaded_files": uploaded,
            "failed_files": failed if failed else None,
            "deploy_time": round(time.time() - start_time, 1)
        })

    except Exception as e:
        app.logger.error(f"HF deploy error: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({
            "error": "HF deployment failed",
            "details": str(e),
            "trace": traceback.format_exc()
        }), 500

# ---------- Health check ----------

@app.route("/")
def health():
    return jsonify({"status": "GrishteSync backend running", "version": "0.5"})

# ---------- Inline Edit and Review Endpoints ----------

@app.route("/api/edit-selection", methods=["POST"])
def edit_selection():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON'}), 400

        instruction = data.get('instruction', '').strip()
        selected_code = data.get('selected_code', '').strip()
        filename = data.get('filename', '').strip()
        all_files = data.get('all_files', {})

        if not instruction or not selected_code or not filename:
            return jsonify({'error': 'Missing required fields: instruction, selected_code, filename'}), 400

        project_context = "\n".join(
            [f"--- {name} ---\n{content}" for name, content in all_files.items()]
        )

        prompt_template = load_prompt('edit_selection.txt')
        if not prompt_template:
            return jsonify({'error': 'Prompt template not found'}), 500

        prompt = prompt_template.format(
            project_context=project_context,
            filename=filename,
            file_content=all_files.get(filename, ''),
            selected_code=selected_code,
            instruction=instruction
        )

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": "You are an expert software engineer. Output ONLY the replacement code, no explanations."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 4096
        }
        
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        replacement = resp.json()["choices"][0]["message"]["content"].strip()
        
        return jsonify({'replacement': replacement})

    except Exception as e:
        app.logger.error(f"Edit selection error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route("/api/review", methods=["POST"])
def review_code():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON'}), 400

        files = data.get('files', {})
        if not files:
            return jsonify({'error': 'No files provided'}), 400

        issues = []
        for name, content in files.items():
            if name.endswith('.py'):
                if 'import' not in content and 'def ' not in content:
                    issues.append(f"{name}: No imports or functions found.")
                if 'TODO' in content:
                    issues.append(f"{name}: Contains TODO comments.")
                try:
                    compile(content, name, 'exec')
                except SyntaxError as e:
                    issues.append(f"{name}: Syntax error: {e}")

        if issues:
            return jsonify({'issues': issues, 'status': 'warning'})
        else:
            return jsonify({
                'issues': [],
                'status': 'success',
                'message': 'No obvious issues found.'
            })

    except Exception as e:
        app.logger.error(f"Review error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))