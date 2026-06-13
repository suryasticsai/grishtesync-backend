# - - - GrishteSync version 5.0.0 - - - 
import os
import re
import json
import base64
import time
import traceback
import datetime
import tempfile
import shutil
import subprocess
import requests
from flask import Flask, request, jsonify, redirect, make_response
from flask_cors import CORS
from urllib.parse import urlencode
from huggingface_hub import HfApi, create_repo

app = Flask(__name__)

# ---------- Secure CORS ----------
FRONTEND_URLS = [
    "https://suryasticsai.github.io",
    "http://localhost:3000",
    "http://localhost:5000",
    "https://grishtesync-backend.onrender.com",
]
CORS(app, resources={r"/*": {"origins": FRONTEND_URLS, "allow_headers": ["Content-Type", "Authorization"], "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]}})

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = make_response()
        response.headers["Access-Control-Allow-Origin"] = ",".join(FRONTEND_URLS)
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.status_code = 200
        return response

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin in FRONTEND_URLS:
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

# ---------- Environment Validation ----------
def validate_env_vars():
    required = ["GROQ_API_KEY", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"]
    missing = [var for var in required if not os.environ.get(var)]
    if missing:
        print(f"⚠️ WARNING: Missing required env vars: {', '.join(missing)}")
    if not os.environ.get("HF_API_TOKEN"):
        print("⚠️ WARNING: HF_API_TOKEN not set. Hugging Face deployment will not work.")
validate_env_vars()

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

HF_API_TOKEN = os.environ.get("HF_API_TOKEN")
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')

# ---------- Load Prompt ----------
def load_prompt(prompt_type, context=None):
    filename = f"{prompt_type}.txt"
    filepath = os.path.join(PROMPTS_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    except FileNotFoundError:
        fallback = os.path.join(PROMPTS_DIR, "generate.txt")
        try:
            with open(fallback, 'r', encoding='utf-8') as f:
                content = f.read().strip()
        except:
            content = "You are an expert developer. Return ONLY valid JSON with a 'files' key."
    except Exception as e:
        print(f"Error loading prompt {filename}: {e}")
        content = "You are an expert developer. Return ONLY valid JSON with a 'files' key."

    if context:
        try:
            content = content.format(**context)
        except KeyError as e:
            print(f"Missing context key for {filename}: {e}")
    return content

# ---------- Enhanced JSON Parser ----------
def parse_ai_response(ai_content):
    """Extract JSON from AI response – handles markdown, extra text, trailing commas, unescaped newlines."""
    # Remove markdown code blocks
    ai_content = re.sub(r'^```(?:json)?\s*', '', ai_content.strip(), flags=re.MULTILINE)
    ai_content = re.sub(r'\s*```$', '', ai_content.strip(), flags=re.MULTILINE)

    start = ai_content.find('{')
    end = ai_content.rfind('}')
    if start == -1 or end <= start:
        return None, f"No JSON object found. Raw: {ai_content[:200]}"

    json_str = ai_content[start:end+1]

    # Remove trailing commas before } or ]
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)

    # Fix unescaped newlines inside strings
    def fix_unescaped_newlines(text):
        result = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                result.append(ch)
                escape = False
                continue
            if ch == '\\':
                escape = True
                result.append(ch)
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch == '\n':
                result.append('\\n')
            elif in_string and ch == '\t':
                result.append('\\t')
            else:
                result.append(ch)
        return ''.join(result)

    json_str = fix_unescaped_newlines(json_str)

    try:
        return json.loads(json_str), None
    except json.JSONDecodeError as e:
        # Salvage attempt: remove lines with known problematic patterns
        lines = json_str.split('\n')
        cleaned = []
        for line in lines:
            if 'allow_flagging' in line or 'demo.queue()' in line or line.strip().startswith('//'):
                continue
            cleaned.append(line)
        json_str = '\n'.join(cleaned)
        try:
            return json.loads(json_str), None
        except json.JSONDecodeError as e2:
            return None, f"JSON parse error: {e2}. First 300 chars: {json_str[:300]}"

# ---------- AI Call ----------
def call_groq(messages):
    resp = requests.post(
        GROQ_API_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL_NAME, "messages": messages, "temperature": 0.3},
        timeout=90
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()

# ---------- Generation Function ----------
def generate_simple(prompt, prompt_type, platform, repo_code=None):
    system_prompt = load_prompt(prompt_type, None)
    user_message = f"Build a {'static website' if platform == 'github' else 'Python web app'}: {prompt}"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    if repo_code:
        context = "Current codebase:\n" + "\n".join([f"\n--- {fname} ---\n{content}" for fname, content in repo_code.items()])
        messages.insert(0, {"role": "system", "content": context})

    ai_content = call_groq(messages)
    files_dict, err = parse_ai_response(ai_content)
    if err:
        # Retry with stricter instruction
        messages.append({"role": "assistant", "content": ai_content})
        messages.append({"role": "user", "content": "Output ONLY valid JSON with a 'files' key. No explanations, no markdown. Start with { and end with }."})
        ai_content = call_groq(messages)
        files_dict, err = parse_ai_response(ai_content)
        if err:
            raise ValueError(f"Failed to generate code: {err}")
    if "files" not in files_dict:
        files_dict = {"files": files_dict}
    return files_dict["files"]

# ============================================================
#                SAFETY NET (embedded, no external file)
# ============================================================
def apply_safety_net(files):
    """
    Fix common AI mistakes in generated files.
    - Fixes typos and version pins in requirements.txt
    - Adds missing packages based on code analysis
    - Removes allow_flagging, demo.queue()
    - Fixes dash bootstrap `block=True` → style
    - Injects watermark into all Python files
    """
    # Collect all Python code
    all_py_code = ""
    py_files = {}
    html_files = {}
    for name, content in files.items():
        if name.endswith('.py'):
            py_files[name] = content
            all_py_code += content + "\n\n"
        elif name.endswith('.html'):
            html_files[name] = content

    # ---------- Detect packages from code ----------
    PACKAGE_RULES = [
        (r'from flask import|import flask|Flask\(', 'flask', '2.0.0'),
        (r'from django\.|import django|DJANGO_SETTINGS_MODULE', 'django', '4.0.0'),
        (r'from fastapi import|FastApi\(', 'fastapi', '0.100.0'),
        (r'import uvicorn', 'uvicorn', '0.20.0'),
        (r'import gradio|from gradio import|gr\.Interface|gr\.Blocks|demo\.launch', 'gradio', '4.0.0'),
        (r'import streamlit|st\.', 'streamlit', '1.25.0'),
        (r'import dash|from dash import|dcc\.|dash\.Dash', 'dash', '2.14.0'),
        (r'dbc\.|dash_bootstrap_components', 'dash-bootstrap-components', '2.0.0'),
        (r'import torch|from torch import|torch\.nn', 'torch', '2.0.0'),
        (r'import tensorflow|from tensorflow import|tf\.keras', 'tensorflow', '2.13.0'),
        (r'import transformers|from transformers import|pipeline\(', 'transformers', '4.30.0'),
        (r'import langchain|from langchain', 'langchain', '0.1.0'),
        (r'import openai|from openai import|OpenAI\(', 'openai', '1.0.0'),
        (r'import anthropic|Anthropic\(', 'anthropic', '0.18.0'),
        (r'import sklearn|from sklearn\.', 'scikit-learn', '1.3.0'),
        (r'import pandas|pd\.', 'pandas', '2.0.0'),
        (r'import numpy|np\.', 'numpy', '1.24.0'),
        (r'import matplotlib|plt\.', 'matplotlib', '3.7.0'),
        (r'import seaborn|sns\.', 'seaborn', '0.12.0'),
        (r'import plotly|px\.|go\.Figure', 'plotly', '5.0.0'),
        (r'import PyPDF2|PdfReader|PdfWriter', 'PyPDF2', '3.0.0'),
        (r'import pdfplumber', 'pdfplumber', '0.10.0'),
        (r'from bs4 import|BeautifulSoup', 'beautifulsoup4', '4.12.0'),
        (r'import requests|requests\.get', 'requests', '2.31.0'),
        (r'PIL\.|from PIL import', 'pillow', '10.0.0'),
        (r'cv2\.|import cv2', 'opencv-python', '4.8.0'),
    ]
    ALIAS_MAP = {
        'sklearn': 'scikit-learn',
        'bs4': 'beautifulsoup4',
        'PIL': 'pillow',
        'cv2': 'opencv-python',
        'dash_bootstrap_components': 'dash-bootstrap-components',
    }
    STDLIB = {'os','sys','re','json','time','datetime','math','random','io','pathlib','typing','collections','itertools','functools','subprocess','tempfile','shutil','argparse','logging','unittest','hashlib','base64','urllib','http','email','html','xml','csv','sqlite3','threading','multiprocessing','asyncio','socket','ssl','secrets','string','textwrap','pprint','copy','weakref','abc','enum','dataclasses'}

    detected_packages = set()
    for pattern, pkg, version in PACKAGE_RULES:
        if re.search(pattern, all_py_code, re.IGNORECASE):
            detected_packages.add(f"{pkg}>={version}")

    import_re = re.compile(r'^(?:from|import)\s+([a-zA-Z0-9_]+)', re.MULTILINE)
    for match in import_re.findall(all_py_code):
        if match in ALIAS_MAP:
            detected_packages.add(f"{ALIAS_MAP[match]}>=0.0.0")
        elif match not in STDLIB:
            detected_packages.add(f"{match}>=0.0.0")

    # ---------- Merge into requirements.txt ----------
    req_content = files.get("requirements.txt", "")
    current_pkgs = set()
    for line in req_content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#'):
            base = re.sub(r'[>=<!].*', '', line).lower()
            current_pkgs.add(base)

    for pkg_line in detected_packages:
        base = re.sub(r'[>=<!].*', '', pkg_line).lower()
        if base not in current_pkgs:
            req_content = req_content.rstrip() + "\n" + pkg_line
            current_pkgs.add(base)

    # Fix typos and exact pins
    req_content = req_content.replace("grado", "gradio").replace("gradio3", "gradio").replace("gradio4", "gradio")
    req_content = re.sub(r'\b([a-zA-Z0-9_-]+)==([\d.]+)\b', r'\1>=\2', req_content)
    # Deduplicate
    lines = [line.strip() for line in req_content.split('\n') if line.strip() and not line.startswith('#')]
    seen = set()
    unique = []
    for line in lines:
        base = re.sub(r'[>=<!].*', '', line).lower()
        if base not in seen:
            seen.add(base)
            unique.append(line)
    unique.sort()
    files["requirements.txt"] = "\n".join(unique)

    # ---------- Fix each Python file ----------
    watermark = [
        "# Created with GrishteSync",
        "# https://suryasticsai.github.io/GrishteSync",
        "# Suryasticsai | suryasticsai@gmail.com"
    ]
    watermark_str = "\n".join(watermark) + "\n\n"

    for fname, code in py_files.items():
        # Remove Gradio deprecated args
        code = re.sub(r',?\s*allow_flagging\s*=\s*[^,)]+', '', code)
        code = re.sub(r'demo\.queue\(\).*', '', code)
        # Fix dash bootstrap block=True
        code = re.sub(r'(dbc\.Button\([^)]*?)block=True', r'\1style={\'width\': \'100%\'}', code)
        # Ensure watermark
        if not all(line in code for line in watermark):
            code = watermark_str + code
        files[fname] = code

    # ---------- Fix HTML files ----------
    for fname, content in html_files.items():
        if '<meta name="viewport"' not in content:
            content = content.replace('<head>', '<head>\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">')
        files[fname] = content

    return files

# ------------------------------------------------------------
#                     DEPLOYMENT ENDPOINTS
# ------------------------------------------------------------
def split_inline_css_js(files):
    if 'index.html' not in files or len(files) > 1:
        return files
    html = files['index.html']
    style_match = re.search(r'<style[^>]*>(.*?)</style>', html, re.DOTALL)
    script_match = re.search(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    if style_match:
        css = style_match.group(1).strip()
        files['style.css'] = css
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    if script_match:
        js = script_match.group(1).strip()
        files['script.js'] = js
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    files['index.html'] = html
    return files

def safe_json(resp):
    try:
        return resp.json(), None
    except:
        return None, f"JSON parse failed: {resp.text[:300]}"

def setup_git_identity():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "GrishteSync Bot"], check=False, capture_output=True)
        subprocess.run(["git", "config", "--global", "user.email", "grishtesync@render.com"], check=False, capture_output=True)
    except:
        pass
setup_git_identity()

def enable_github_pages(repo_full_name, github_token, app_description):
    owner, repo = repo_full_name.split('/')
    gh_headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github.v3+json"}
    pages_url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pages"
    payload = {"source": {"branch": "main", "path": "/"}}
    requests.post(pages_url, headers=gh_headers, json=payload)
    readme_content = f"""# {repo} – Generated by GrishteSync

**Generated on:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}

{app_description}

## 🌐 Live Demo
[![GitHub Pages](https://img.shields.io/badge/🌐-Live%20Demo-blue)](https://{owner}.github.io/{repo}/)

## 📄 License
MIT © GrishteSync | Suryasticsai
"""
    encoded = base64.b64encode(readme_content.encode()).decode()
    readme_url = f"{GITHUB_API_URL}/repos/{repo_full_name}/contents/README.md"
    get_resp = requests.get(readme_url, headers=gh_headers)
    payload_readme = {"message": "Add GitHub Pages documentation", "content": encoded, "branch": "main"}
    if get_resp.status_code == 200:
        payload_readme["sha"] = get_resp.json()["sha"]
    requests.put(readme_url, headers=gh_headers, json=payload_readme)
    return f"https://{owner}.github.io/{repo}/"

def sanitize_space_name(name):
    name = re.sub(r'[^a-zA-Z0-9-]', '-', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')[:96] or "grishte-app"

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
        resp = requests.post(
            GITHUB_TOKEN_URL,
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
        if err or "access_token" not in data:
            return jsonify({"error": "GitHub token error", "details": err or data}), 500
        access_token = data["access_token"]
        user_resp = requests.get(f"{GITHUB_API_URL}/user", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        user_data, _ = safe_json(user_resp)
        username = user_data.get("login", "") if user_data else ""
        return redirect(f"{FRONTEND_URL}?token={access_token}&github_user={username}")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/generate", methods=["POST"])
def generate():
    start_time = time.time()
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    user_prompt = data.get("prompt", "").strip()
    prompt_type = data.get("prompt_type", "generate")
    platform = data.get("platform", "huggingface")
    repo_full_name = data.get("repo")
    user_token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") or auth_header.startswith("token "):
        user_token = auth_header.split(" ", 1)[1]

    if not user_prompt:
        return jsonify({"error": "Prompt is required."}), 400

    existing_code = {}
    if repo_full_name and user_token:
        try:
            gh_headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github.v3+json"}
            contents_resp = requests.get(f"{GITHUB_API_URL}/repos/{repo_full_name}/contents", headers=gh_headers, timeout=15)
            if contents_resp.status_code == 200:
                for item in contents_resp.json():
                    if item["type"] == "file" and item.get("size", 0) < 500000:
                        try:
                            existing_code[item["name"]] = requests.get(item["download_url"], timeout=10).text
                        except:
                            pass
        except:
            pass

    try:
        generated_files = generate_simple(user_prompt, prompt_type, platform, existing_code)
        generated_files = apply_safety_net(generated_files)

        if platform == "github":
            generated_files = split_inline_css_js(generated_files)

        return jsonify({
            "status": "success",
            "files": generated_files,
            "generate_time": round(time.time() - start_time, 1)
        })
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/api/deploy", methods=["POST"])
def deploy():
    start_time = time.time()
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") or auth_header.startswith("token "):
        user_token = auth_header.split(" ", 1)[1]
    else:
        return jsonify({"error": "Missing GitHub token"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    repo_name = data.get("repo_name")
    files = data.get("files", {})
    version = data.get("version", "0.0.0")
    app_description = data.get("pr_description", "AI-generated project")

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
    pages_url = None

    try:
        check = requests.get(repo_url, headers=gh_headers, timeout=10)
        if check.status_code == 404:
            create_resp = requests.post(f"{GITHUB_API_URL}/user/repos", headers=gh_headers, json={"name": repo_name, "private": False, "auto_init": True}, timeout=15)
            if create_resp.status_code not in [200, 201]:
                return jsonify({"error": f"Failed to create repo: {create_resp.text[:300]}"}), 500
            time.sleep(3)
            pages_url = enable_github_pages(f"{username}/{repo_name}", user_token, app_description)
        elif check.status_code != 200:
            return jsonify({"error": f"Unexpected repo status: {check.status_code}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        repo_info, _ = safe_json(requests.get(repo_url, headers=gh_headers, timeout=10))
        default_branch = repo_info.get("default_branch", "main")
    except:
        default_branch = "main"

    branch_name = f"agent/feature-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    sha = None
    for attempt in range(5):
        try:
            ref_resp = requests.get(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs/heads/{default_branch}", headers=gh_headers, timeout=10)
            if ref_resp.status_code == 200:
                sha = ref_resp.json()["object"]["sha"]
                break
        except:
            pass
        time.sleep(2)
    if not sha:
        return jsonify({"error": "Failed to get branch SHA"}), 500

    try:
        create_ref = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs", headers=gh_headers, json={"ref": f"refs/heads/{branch_name}", "sha": sha}, timeout=10)
        if create_ref.status_code == 422:
            branch_name = f"agent/feature-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(3).hex()}"
            create_ref = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs", headers=gh_headers, json={"ref": f"refs/heads/{branch_name}", "sha": sha}, timeout=10)
        if create_ref.status_code not in [200, 201]:
            return jsonify({"error": f"Failed to create branch: {create_ref.text[:300]}"}), 500
    except Exception as e:
        return jsonify({"error": f"Branch creation exception: {str(e)}"}), 500

    for filepath, content in files.items():
        try:
            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            api_path = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{filepath}"
            payload = {"message": f"Update {filepath} via GrishteSync v{version}", "content": encoded, "branch": branch_name}
            file_check = requests.get(f"{api_path}?ref={branch_name}", headers=gh_headers, timeout=10)
            if file_check.status_code == 200:
                payload["sha"] = file_check.json()["sha"]
            put_resp = requests.put(api_path, headers=gh_headers, json=payload, timeout=15)
            if put_resp.status_code not in [200, 201]:
                return jsonify({"error": f"Push failed for {filepath}: {put_resp.text[:300]}"}), 500
        except Exception as e:
            return jsonify({"error": f"File push exception for {filepath}: {str(e)}"}), 500

    try:
        pr_body = data.get("pr_description") or f"## GrishteSync update v{version}\n\nFiles: {', '.join(files.keys())}\n\n*Created with [GrishteSync](https://suryasticsai.github.io/GrishteSync)*"
        pr_resp = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/pulls", headers=gh_headers, json={"title": f"GrishteSync update v{version}", "head": branch_name, "base": default_branch, "body": pr_body}, timeout=15)
        pr_url = pr_resp.json().get("html_url") if pr_resp.status_code in [200, 201] else None
    except:
        pr_url = None

    return jsonify({
        "status": "success",
        "repo_url": f"https://github.com/{username}/{repo_name}",
        "branch": branch_name,
        "pr_url": pr_url,
        "pages_url": pages_url,
        "username": username,
        "deploy_time": round(time.time() - start_time, 1)
    })
@app.route("/api/diagnose", methods=["POST"])
def diagnose():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    error_log = data.get("error_log", "").strip()
    current_files = data.get("files", {})
    if not error_log:
        return jsonify({"error": "No error log provided"}), 400
    if not current_files:
        return jsonify({"error": "No code files provided"}), 400

    # Prepare context for the fixer prompt
    context = {
        "error_log": error_log,
        "current_code": "\n".join([f"--- {fname} ---\n{content}" for fname, content in current_files.items()])
    }
    
    # Load the fixer prompt (you need prompts/fixer.txt)
    try:
        with open(os.path.join(PROMPTS_DIR, "fixer.txt"), 'r', encoding='utf-8') as f:
            system_prompt = f.read()
    except:
        # Fallback prompt
        system_prompt = """You are an expert debugger. Fix the code based on the error log.
Return ONLY a JSON object with a "files" key.
The files should have the same structure as the current code, but with fixes applied.
Do not change filenames unnecessarily.
If you need to add a new file, include it.
The JSON must be valid and contain no markdown or extra text.

Current code:
{current_code}

Error log:
{error_log}
"""
    
    # Fill in context (using .format if placeholders exist)
    try:
        system_prompt_filled = system_prompt.format(**context)
    except KeyError:
        # If placeholders not present, just append
        system_prompt_filled = system_prompt + f"\n\nCurrent code:\n{context['current_code']}\n\nError log:\n{error_log}"

    messages = [
        {"role": "system", "content": system_prompt_filled},
        {"role": "user", "content": "Fix the error and return the corrected files as JSON."}
    ]
    
    try:
        ai_content = call_groq(messages)
        files_dict, err = parse_ai_response(ai_content)
        if err:
            return jsonify({"error": f"Failed to parse AI response: {err}"}), 500
        if "files" not in files_dict:
            files_dict = {"files": files_dict}
        # Apply safety net to fix any remaining issues
        fixed_files = apply_safety_net(files_dict["files"])
        return jsonify({"status": "success", "files": fixed_files})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/api/deploy-hf", methods=["POST"])
def deploy_hf():
    start_time = time.time()
    temp_dir = None
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400

        platform = data.get("platform", "huggingface")
        if platform == "github":
            return jsonify({"error": "WebApp projects cannot be deployed to Hugging Face. Use GitHub Pages only."}), 400

        repo_full_name = data.get("repo_full_name")
        if not repo_full_name:
            return jsonify({"error": "repo_full_name is required"}), 400
        if not HF_API_TOKEN:
            return jsonify({"error": "HF_API_TOKEN not configured"}), 500

        if "/" in repo_full_name:
            username = repo_full_name.split("/")[0]
            raw_space_name = data.get("space_name", repo_full_name.split("/")[1])
        else:
            api = HfApi(token=HF_API_TOKEN)
            try:
                username = api.whoami()["name"]
            except:
                return jsonify({"error": "Could not determine HF username"}), 500
            raw_space_name = data.get("space_name", repo_full_name)

        space_name = sanitize_space_name(raw_space_name)
        files = data.get("files", {})

        if not any(f.endswith(".py") for f in files):
            return jsonify({"error": "No Python files found. Hugging Face requires a Python app."}), 400

        # Detect SDK
        if any("import streamlit" in content for content in files.get("app.py", "")):
            sdk = "streamlit"
            sdk_version = "1.35.0"
        else:
            sdk = "gradio"
            sdk_version = "6.18.0"

        readme_content = f"""---
title: {space_name}
emoji: 🐍
colorFrom: green
colorTo: blue
sdk: {sdk}
sdk_version: "{sdk_version}"
python_version: "3.10"
app_file: app.py
pinned: false
---

# {space_name}
Deployed by GrishteSync
"""
        files["README.md"] = readme_content

        if "requirements.txt" not in files:
            files["requirements.txt"] = "gradio>=4.0.0\nhuggingface_hub>=0.10.1"

        # Ensure proper launch for Gradio
        for fname, content in files.items():
            if fname.endswith(".py") and "launch" in content:
                if "server_name" not in content and "server_port" not in content:
                    files[fname] = content.replace(".launch(", ".launch(server_name='0.0.0.0', server_port=7860, ")

        files = apply_safety_net(files)

        temp_dir = tempfile.mkdtemp()
        space_repo_url = f"https://{username}:{HF_API_TOKEN}@huggingface.co/spaces/{username}/{space_name}"
        subprocess.run(["git", "config", "--global", "user.email", "grishtesync@render.com"], check=False)
        subprocess.run(["git", "config", "--global", "user.name", "GrishteSync Bot"], check=False)

        clone_result = subprocess.run(["git", "clone", space_repo_url, temp_dir], capture_output=True)
        if clone_result.returncode != 0:
            try:
                create_repo(repo_id=f"{username}/{space_name}", repo_type="space", space_sdk=sdk, token=HF_API_TOKEN, exist_ok=True)
                time.sleep(3)
                subprocess.run(["git", "clone", space_repo_url, temp_dir], check=True, capture_output=True)
            except Exception as e:
                return jsonify({"error": f"Failed to create Space: {str(e)}"}), 500

        for item in os.listdir(temp_dir):
            if item == ".git":
                continue
            item_path = os.path.join(temp_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

        for filepath, content in files.items():
            file_path = os.path.join(temp_dir, filepath)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        subprocess.run(["git", "-C", temp_dir, "add", "."], check=True)
        status_result = subprocess.run(["git", "-C", temp_dir, "status", "--porcelain"], capture_output=True, text=True)
        if status_result.stdout.strip():
            subprocess.run(["git", "-C", temp_dir, "commit", "-m", f"Deploy from GrishteSync v{int(time.time())}"], check=True)
            subprocess.run(["git", "-C", temp_dir, "push", "origin", "HEAD:main", "--force"], check=True)

        space_url = f"https://huggingface.co/spaces/{username}/{space_name}"
        return jsonify({
            "status": "success",
            "space_url": space_url,
            "space_full_name": f"{username}/{space_name}",
            "deploy_time": round(time.time() - start_time, 1)
        })
    except Exception as e:
        return jsonify({"error": f"Deploy failed: {str(e)}", "trace": traceback.format_exc()}), 500
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

@app.route("/")
def health():
    return jsonify({"status": "GrishteSync backend running", "version": "5.0"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
