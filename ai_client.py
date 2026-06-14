import os
import re
import json
import requests

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.3-70b-versatile"

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')

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
            print(f"Missing context key: {e}")
    return content

def parse_ai_response(ai_content):
    ai_content = re.sub(r'^```(?:json)?\s*', '', ai_content.strip(), flags=re.MULTILINE)
    ai_content = re.sub(r'\s*```$', '', ai_content.strip(), flags=re.MULTILINE)
    start = ai_content.find('{')
    end = ai_content.rfind('}')
    if start == -1 or end <= start:
        return None, f"No JSON object found. Raw: {ai_content[:200]}"
    json_str = ai_content[start:end+1]
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    def fix_newlines(text):
        res, in_str, esc = [], False, False
        for ch in text:
            if esc:
                res.append(ch); esc = False; continue
            if ch == '\\':
                res.append(ch); esc = True; continue
            if ch == '"':
                in_str = not in_str; res.append(ch); continue
            if in_str and ch == '\n':
                res.append('\\n')
            elif in_str and ch == '\t':
                res.append('\\t')
            else:
                res.append(ch)
        return ''.join(res)
    json_str = fix_newlines(json_str)
    try:
        return json.loads(json_str), None
    except json.JSONDecodeError as e:
        lines = json_str.split('\n')
        cleaned = [line for line in lines if 'allow_flagging' not in line and 'demo.queue()' not in line and not line.strip().startswith('//')]
        json_str = '\n'.join(cleaned)
        try:
            return json.loads(json_str), None
        except json.JSONDecodeError as e2:
            return None, f"JSON parse error: {e2}. Preview: {json_str[:300]}"

def call_groq(messages):
    resp = requests.post(
        GROQ_API_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL_NAME, "messages": messages, "temperature": 0.3},
        timeout=90
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()

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
        messages.append({"role": "assistant", "content": ai_content})
        messages.append({"role": "user", "content": "Output ONLY valid JSON with 'files' key. No markdown. Start with { and end with }."})
        ai_content = call_groq(messages)
        files_dict, err = parse_ai_response(ai_content)
        if err:
            raise ValueError(f"Failed to generate: {err}")
    if "files" not in files_dict:
        files_dict = {"files": files_dict}
    return files_dict["files"]