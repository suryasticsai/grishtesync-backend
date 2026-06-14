import os
import time
import traceback
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from ai_client import generate_simple, load_prompt, call_groq, parse_ai_response
from safety_net import apply_safety_net
from github_helpers import github_login_redirect, github_callback_handler, create_or_update_repo, push_files_to_branch, create_pull_request, enable_github_pages
from hf_helpers import deploy_to_hf_space, create_embed_page, sanitize_space_name
import requests

app = Flask(__name__)
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

GITHUB_API_URL = "https://api.github.com"

def safe_json(resp):
    try:
        return resp.json(), None
    except:
        return None, f"JSON parse failed: {resp.text[:300]}"

# ---------- Routes ----------
@app.route("/auth/login")
def login():
    return github_login_redirect()

@app.route("/auth/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing code"}), 400
    token, username = github_callback_handler(code)
    if not token:
        return jsonify({"error": "GitHub auth failed"}), 500
    return redirect(f"{os.environ.get('FRONTEND_URL', 'https://suryasticsai.github.io/GrishteSync/')}?token={token}&github_user={username}")

@app.route("/api/list-repos", methods=["GET"])
def list_repos():
    platform = request.args.get("platform", "github")
    auth_header = request.headers.get("Authorization", "")
    user_token = auth_header.replace("Bearer ", "") if auth_header else None
    if platform == "github":
        if not user_token:
            return jsonify({"error": "GitHub token required"}), 401
        resp = requests.get(f"{GITHUB_API_URL}/user/repos?per_page=50", headers={"Authorization": f"Bearer {user_token}"})
        if resp.status_code != 200:
            return jsonify({"error": "Failed to fetch repos"}), resp.status_code
        repos = resp.json()
        result = [{"name": r["name"], "full_name": r["full_name"], "url": r["html_url"]} for r in repos if r["name"].lower().startswith("grishtesync-")]
        return jsonify({"platform": "github", "repos": result})
    elif platform == "huggingface":
        if not os.environ.get("HF_API_TOKEN"):
            return jsonify({"error": "HF_API_TOKEN not configured"}), 500
        from huggingface_hub import HfApi
        api = HfApi(token=os.environ["HF_API_TOKEN"])
        user = api.whoami()["name"]
        spaces = api.list_spaces(author=user)
        result = [{"name": s.id.split("/")[-1], "full_name": s.id, "url": f"https://huggingface.co/spaces/{s.id}"} for s in spaces if s.id.lower().startswith("grishtesync-")]
        return jsonify({"platform": "huggingface", "repos": result})
    return jsonify({"error": "Invalid platform"}), 400

@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    user_prompt = data.get("prompt", "").strip()
    prompt_type = data.get("prompt_type", "generate")
    platform = data.get("platform", "huggingface")
    repo_full_name = data.get("repo")
    user_token = request.headers.get("Authorization", "").replace("Bearer ", "") if request.headers.get("Authorization") else None

    existing_code = {}
    if repo_full_name and platform == "github" and user_token:
        try:
            gh_headers = {"Authorization": f"Bearer {user_token}"}
            contents = requests.get(f"{GITHUB_API_URL}/repos/{repo_full_name}/contents", headers=gh_headers).json()
            for item in contents:
                if item["type"] == "file" and item.get("size", 0) < 500000:
                    existing_code[item["name"]] = requests.get(item["download_url"]).text
        except:
            pass
    elif repo_full_name and platform == "huggingface" and os.environ.get("HF_API_TOKEN"):
        from huggingface_hub import HfApi, hf_hub_download
        api = HfApi(token=os.environ["HF_API_TOKEN"])
        files = api.list_repo_files(repo_id=repo_full_name, repo_type="space")
        for f in files:
            if f.endswith(('.py','.txt','.md','.html','.css','.js')):
                path = hf_hub_download(repo_id=repo_full_name, filename=f, repo_type="space", token=os.environ["HF_API_TOKEN"])
                with open(path, 'r') as file:
                    existing_code[f] = file.read()

    try:
        generated_files = generate_simple(user_prompt, prompt_type, platform, existing_code)
        generated_files = apply_safety_net(generated_files)
        if platform == "github":
            # split inline CSS/JS
            if 'index.html' in generated_files:
                html = generated_files['index.html']
                style_match = re.search(r'<style[^>]*>(.*?)</style>', html, re.DOTALL)
                script_match = re.search(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
                if style_match:
                    generated_files['style.css'] = style_match.group(1).strip()
                    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
                if script_match:
                    generated_files['script.js'] = script_match.group(1).strip()
                    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
                generated_files['index.html'] = html
        return jsonify({"status": "success", "files": generated_files})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/api/diagnose", methods=["POST"])
def diagnose():
    data = request.get_json()
    error_log = data.get("error_log", "")
    current_files = data.get("files", {})
    if not error_log or not current_files:
        return jsonify({"error": "error_log and files required"}), 400
    context = {
        "error_log": error_log,
        "current_code": "\n".join([f"--- {fname} ---\n{content}" for fname, content in current_files.items()])
    }
    fixer_prompt = load_prompt("fixer", context)
    if not fixer_prompt:
        fixer_prompt = f"Fix the code based on error log. Return ONLY JSON with 'files' key.\nCurrent code:\n{context['current_code']}\nError log:\n{error_log}"
    messages = [{"role": "system", "content": fixer_prompt}, {"role": "user", "content": "Fix and return corrected files as JSON."}]
    try:
        from ai_client import call_groq, parse_ai_response
        ai_content = call_groq(messages)
        files_dict, err = parse_ai_response(ai_content)
        if err:
            return jsonify({"error": f"Parse error: {err}"}), 500
        if "files" not in files_dict:
            files_dict = {"files": files_dict}
        fixed_files = apply_safety_net(files_dict["files"])
        return jsonify({"status": "success", "files": fixed_files})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/api/deploy", methods=["POST"])
def deploy_github():
    start = time.time()
    data = request.get_json()
    user_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not user_token:
        return jsonify({"error": "Missing GitHub token"}), 401
    repo_name = data.get("repo_name")
    files = data.get("files", {})
    version = data.get("version", "0.0.0")
    app_name = data.get("app_name", repo_name.replace("GrishteSync-", ""))
    prompt = data.get("prompt", "AI-generated app")
    # Get username
    user_resp = requests.get(f"{GITHUB_API_URL}/user", headers={"Authorization": f"Bearer {user_token}"})
    if user_resp.status_code != 200:
        return jsonify({"error": "Invalid token"}), 401
    username = user_resp.json()["login"]
    # Create/update repo
    create_or_update_repo(username, repo_name, user_token)
    # Create branch and push files
    branch_name = f"agent/feature-{int(time.time())}"
    # Get default branch SHA
    repo_info = requests.get(f"{GITHUB_API_URL}/repos/{username}/{repo_name}", headers={"Authorization": f"Bearer {user_token}"}).json()
    default_branch = repo_info.get("default_branch", "main")
    ref_resp = requests.get(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs/heads/{default_branch}", headers={"Authorization": f"Bearer {user_token}"})
    sha = ref_resp.json()["object"]["sha"]
    # Create branch
    requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/git/refs", headers={"Authorization": f"Bearer {user_token}"}, json={"ref": f"refs/heads/{branch_name}", "sha": sha})
    push_files_to_branch(username, repo_name, files, user_token, branch_name, f"GrishteSync update v{version}")
    # Create PR
    pr_url = create_pull_request(username, repo_name, branch_name, default_branch, f"GrishteSync update v{version}", f"Files: {', '.join(files.keys())}", user_token)
    # Generate README and enable Pages
    readme_content = f"# {app_name}\n\n{prompt}\n\nDeployed by GrishteSync."
    pages_url = enable_github_pages(f"{username}/{repo_name}", user_token, readme_content)
    return jsonify({
        "status": "success",
        "repo_url": f"https://github.com/{username}/{repo_name}",
        "pr_url": pr_url,
        "pages_url": pages_url,
        "deploy_time": round(time.time() - start, 1)
    })

@app.route("/api/deploy-hf", methods=["POST"])
def deploy_hf():
    start = time.time()
    data = request.get_json()
    user_token = request.headers.get("Authorization", "").replace("Bearer ", "") if request.headers.get("Authorization") else None
    repo_full_name = data.get("repo_full_name")
    files = data.get("files", {})
    app_name = data.get("app_name", repo_full_name.split("/")[-1] if repo_full_name else "app")
    prompt = data.get("prompt", "")
    if not repo_full_name or not files:
        return jsonify({"error": "repo_full_name and files required"}), 400
    if not os.environ.get("HF_API_TOKEN"):
        return jsonify({"error": "HF_API_TOKEN not set"}), 500
    from huggingface_hub import HfApi
    api = HfApi(token=os.environ["HF_API_TOKEN"])
    try:
        username = api.whoami()["name"]
    except:
        return jsonify({"error": "HF token invalid"}), 500
    space_name = sanitize_space_name(repo_full_name.split("/")[-1] if "/" in repo_full_name else repo_full_name)
    # Detect SDK
    if any("streamlit" in c for c in files.get("app.py", "")):
        sdk, sdk_version = "streamlit", "1.35.0"
    else:
        sdk, sdk_version = "gradio", "6.18.0"
    # Deploy to HF
    space_url = deploy_to_hf_space(username, space_name, files, sdk, sdk_version, prompt, app_name)
    # Create embed page (if GitHub token available)
    embed_url = None
    if user_token:
        # Generate detailed README for embed
        readme_for_embed = f"# {app_name}\n\n{prompt}\n\nLive Space: {space_url}"
        embed_url = create_embed_page(app_name, space_url, user_token, username, readme_for_embed)
    return jsonify({
        "status": "success",
        "space_url": space_url,
        "embed_url": embed_url,
        "space_full_name": f"{username}/{space_name}",
        "deploy_time": round(time.time() - start, 1)
    })

@app.route("/")
def health():
    return jsonify({"status": "GrishteSync backend running", "version": "5.4"})

if __name__ == "__main__":
    import re
    from flask import make_response
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))