import os
import re
import base64
import time
import tempfile
import shutil
import subprocess
import requests
from huggingface_hub import HfApi, create_repo

HF_API_TOKEN = os.environ.get("HF_API_TOKEN")
GITHUB_API_URL = "https://api.github.com"

def sanitize_space_name(name):
    name = re.sub(r'[^a-zA-Z0-9-]', '-', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')[:96] or "grishte-app"

def create_embed_page(app_name, space_url, github_token, username, readme_content):
    repo_name = "grishtesync-embeds"
    subfolder = re.sub(r'[^a-z0-9-]', '', app_name.lower().replace(' ', '-').replace('_', '-'))
    file_path = f"apps/{subfolder}/index.html"
    embed_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>{app_name} – Live Demo</title>
<style>body{{margin:0;font-family:system-ui;background:#0a0c15;color:#e2e8f0;}}
header{{text-align:center;padding:1rem;background:#11131f;border-bottom:1px solid #10b981;}}
h1{{margin:0;font-size:1.5rem;background:linear-gradient(135deg,#10b981,#60a5fa);-webkit-background-clip:text;background-clip:text;color:transparent;}}
.container{{height:calc(100vh - 80px);width:100%;}}
iframe{{width:100%;height:100%;border:none;}}
footer{{text-align:center;padding:0.5rem;font-size:0.7rem;color:#8b92b0;background:#11131f;border-top:1px solid #1f2438;}}
footer a{{color:#10b981;text-decoration:none;}}
</style>
</head>
<body><header><h1>📱 {app_name}</h1></header>
<div class="container"><iframe src="{space_url}"></iframe></div>
<footer>Powered by <a href="https://suryasticsai.github.io/GrishteSync">GrishteSync</a> | Suryasticsai</footer>
</body>
</html>"""
    gh_headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github.v3+json"}
    repo_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}"
    check = requests.get(repo_url, headers=gh_headers)
    if check.status_code == 404:
        create_payload = {"name": repo_name, "private": False, "auto_init": True, "description": "Embed pages for GrishteSync apps"}
        requests.post(f"{GITHUB_API_URL}/user/repos", headers=gh_headers, json=create_payload)
        time.sleep(2)
        pages_payload = {"source": {"branch": "main", "path": "/"}}
        requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/pages", headers=gh_headers, json=pages_payload)
    try:
        repo_info = requests.get(repo_url, headers=gh_headers).json()
        default_branch = repo_info.get("default_branch", "main")
    except:
        default_branch = "main"
    file_api_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{file_path}"
    file_sha = None
    get_file = requests.get(file_api_url, headers=gh_headers)
    if get_file.status_code == 200:
        file_sha = get_file.json().get("sha")
    content_b64 = base64.b64encode(embed_html.encode()).decode()
    commit_payload = {"message": f"Update embed for {app_name}", "content": content_b64, "branch": default_branch}
    if file_sha:
        commit_payload["sha"] = file_sha
    requests.put(file_api_url, headers=gh_headers, json=commit_payload)
    # Also push README
    readme_b64 = base64.b64encode(readme_content.encode()).decode()
    readme_path = f"apps/{subfolder}/README.md"
    readme_payload = {"message": f"Add README for {app_name}", "content": readme_b64, "branch": default_branch}
    readme_check = requests.get(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{readme_path}", headers=gh_headers)
    if readme_check.status_code == 200:
        readme_payload["sha"] = readme_check.json().get("sha")
    requests.put(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{readme_path}", headers=gh_headers, json=readme_payload)
    return f"https://{username}.github.io/{repo_name}/{file_path}"

def deploy_to_hf_space(username, space_name, files, sdk, sdk_version, prompt, app_name):
    # Prepare README
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
{prompt}
"""
    files["README.md"] = readme_content
    if "requirements.txt" not in files:
        files["requirements.txt"] = "gradio>=4.0.0\nhuggingface_hub>=0.10.1"
    # Ensure Gradio launch parameters
    for fname, content in files.items():
        if fname.endswith(".py") and "launch" in content:
            if "server_name" not in content and "server_port" not in content:
                files[fname] = content.replace(".launch(", ".launch(server_name='0.0.0.0', server_port=7860, ")
    temp_dir = tempfile.mkdtemp()
    space_repo_url = f"https://{username}:{HF_API_TOKEN}@huggingface.co/spaces/{username}/{space_name}"
    subprocess.run(["git", "config", "--global", "user.email", "grishtesync@render.com"], check=False)
    subprocess.run(["git", "config", "--global", "user.name", "GrishteSync Bot"], check=False)
    clone_result = subprocess.run(["git", "clone", space_repo_url, temp_dir], capture_output=True)
    if clone_result.returncode != 0:
        create_repo(repo_id=f"{username}/{space_name}", repo_type="space", space_sdk=sdk, token=HF_API_TOKEN, exist_ok=True)
        time.sleep(3)
        subprocess.run(["git", "clone", space_repo_url, temp_dir], check=True, capture_output=True)
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
    shutil.rmtree(temp_dir, ignore_errors=True)
    return f"https://huggingface.co/spaces/{username}/{space_name}"