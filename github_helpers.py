import os
import base64
import time
import requests
from urllib.parse import urlencode
from flask import redirect

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://suryasticsai.github.io/GrishteSync/")

def safe_json(resp):
    try:
        return resp.json(), None
    except:
        return None, f"JSON parse failed: {resp.text[:300]}"

def github_login_redirect():
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": f"{os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:5000')}/auth/callback",
        "scope": "repo workflow",
        "state": "github"
    }
    return redirect(f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}")

def github_callback_handler(code):
    resp = requests.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": f"{os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:5000')}/auth/callback"
        },
        timeout=15
    )
    data, err = safe_json(resp)
    if err or "access_token" not in data:
        return None, f"GitHub token error: {err or data}"
    access_token = data["access_token"]
    user_resp = requests.get(f"{GITHUB_API_URL}/user", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
    user_data, _ = safe_json(user_resp)
    username = user_data.get("login", "") if user_data else ""
    return access_token, username

def create_or_update_repo(username, repo_name, github_token):
    gh_headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github.v3+json"}
    repo_url = f"{GITHUB_API_URL}/repos/{username}/{repo_name}"
    check = requests.get(repo_url, headers=gh_headers)
    if check.status_code == 404:
        create_resp = requests.post(f"{GITHUB_API_URL}/user/repos", headers=gh_headers, json={"name": repo_name, "private": False, "auto_init": True})
        if create_resp.status_code not in [200, 201]:
            raise Exception(f"Failed to create repo: {create_resp.text[:300]}")
        time.sleep(2)
    return repo_url

def enable_github_pages(repo_full_name, github_token, readme_content):
    owner, repo = repo_full_name.split('/')
    gh_headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github.v3+json"}
    # Enable Pages
    pages_url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pages"
    payload = {"source": {"branch": "main", "path": "/"}}
    requests.post(pages_url, headers=gh_headers, json=payload)
    # Push README
    encoded = base64.b64encode(readme_content.encode()).decode()
    readme_url = f"{GITHUB_API_URL}/repos/{repo_full_name}/contents/README.md"
    get_resp = requests.get(readme_url, headers=gh_headers)
    payload_readme = {"message": "Add documentation", "content": encoded, "branch": "main"}
    if get_resp.status_code == 200:
        payload_readme["sha"] = get_resp.json()["sha"]
    requests.put(readme_url, headers=gh_headers, json=payload_readme)
    return f"https://{owner}.github.io/{repo}/"

def push_files_to_branch(username, repo_name, files, github_token, branch_name, commit_message):
    gh_headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github.v3+json"}
    for filepath, content in files.items():
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        api_path = f"{GITHUB_API_URL}/repos/{username}/{repo_name}/contents/{filepath}"
        payload = {"message": commit_message, "content": encoded, "branch": branch_name}
        file_check = requests.get(f"{api_path}?ref={branch_name}", headers=gh_headers)
        if file_check.status_code == 200:
            payload["sha"] = file_check.json()["sha"]
        put_resp = requests.put(api_path, headers=gh_headers, json=payload)
        if put_resp.status_code not in [200, 201]:
            raise Exception(f"Push failed for {filepath}: {put_resp.text[:300]}")

def create_pull_request(username, repo_name, head_branch, base_branch, title, body, github_token):
    gh_headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github.v3+json"}
    pr_payload = {"title": title, "head": head_branch, "base": base_branch, "body": body}
    pr_resp = requests.post(f"{GITHUB_API_URL}/repos/{username}/{repo_name}/pulls", headers=gh_headers, json=pr_payload)
    if pr_resp.status_code in [200, 201]:
        return pr_resp.json().get("html_url")
    return None