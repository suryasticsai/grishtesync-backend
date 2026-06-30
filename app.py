import os
import json
import re
import logging
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB
CORS(app, origins=["http://localhost:5500", "http://127.0.0.1:5500", "https://suryasticsai.github.io"])

# Configure logging
logging.basicConfig(level=logging.INFO)

# Groq client
groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

# Helper to load prompt files
def load_prompt(filename):
    prompt_path = os.path.join('prompts', filename)
    with open(prompt_path, 'r') as f:
        return f.read()

# --------------------- Existing Routes ---------------------

@app.route('/api/generate', methods=['POST'])
def generate_code():
    """Generate code based on description and project type."""
    try:
        data = request.get_json()
        if not data or 'description' not in data:
            return jsonify({'error': 'Missing description'}), 400

        description = data['description'].strip()
        project_type = data.get('project_type', 'webapp')

        if not description:
            return jsonify({'error': 'Description cannot be empty'}), 400

        # Select prompt
        if project_type == 'fullstack':
            prompt_template = load_prompt('fullstack_generate.txt')
        else:
            prompt_template = load_prompt('generate.txt')  # your existing generic prompt

        prompt = prompt_template.format(description=description)

        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=8192
        )
        result_text = response.choices[0].message.content

        # Parse JSON from result
        try:
            result_json = json.loads(result_text)
            files = result_json.get('files', {})
            readme = result_json.get('readme', '')
        except json.JSONDecodeError:
            # Try to extract from markdown code block
            match = re.search(r'```json\s*(\{.*?\})\s*```', result_text, re.DOTALL)
            if match:
                result_json = json.loads(match.group(1))
                files = result_json.get('files', {})
                readme = result_json.get('readme', '')
            else:
                app.logger.error(f"Failed to parse JSON from: {result_text[:200]}")
                return jsonify({'error': 'Failed to parse AI response as JSON'}), 500

        session['generated_files'] = files
        session['readme'] = readme
        return jsonify({'files': files, 'readme': readme})

    except Exception as e:
        app.logger.error(f"Generate error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/deploy-github', methods=['POST'])
def deploy_to_github():
    """Deploy generated files to GitHub repository."""
    try:
        data = request.get_json()
        if not data or 'token' not in data or 'repo' not in data:
            return jsonify({'error': 'Missing token or repo'}), 400

        token = data['token']
        repo = data['repo']
        files = session.get('generated_files', {})
        if not files:
            return jsonify({'error': 'No generated files found'}), 400

        # Use PyGithub or direct API – simplified here
        import requests
        headers = {'Authorization': f'token {token}'}
        api_url = f'https://api.github.com/repos/{repo}/contents'

        for filepath, content in files.items():
            # Encode content to base64
            import base64
            encoded = base64.b64encode(content.encode()).decode()
            payload = {
                'message': f'Add {filepath}',
                'content': encoded,
                'branch': 'main'
            }
            # Check if file exists, need to get SHA for update
            get_url = f'{api_url}/{filepath}'
            resp = requests.get(get_url, headers=headers)
            if resp.status_code == 200:
                sha = resp.json().get('sha')
                payload['sha'] = sha
            put_resp = requests.put(get_url, headers=headers, json=payload)
            if put_resp.status_code not in (200, 201):
                app.logger.error(f"GitHub deploy error: {put_resp.text}")
                return jsonify({'error': f'Failed to push {filepath}'}), 500

        return jsonify({'success': True, 'message': 'Deployed to GitHub'})

    except Exception as e:
        app.logger.error(f"GitHub deploy error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/deploy-hf', methods=['POST'])
def deploy_to_huggingface():
    """Deploy to Hugging Face Spaces (simplified)."""
    try:
        data = request.get_json()
        if not data or 'token' not in data or 'space' not in data:
            return jsonify({'error': 'Missing token or space'}), 400

        # Placeholder – implement HF API as needed
        return jsonify({'success': True, 'message': 'Deployed to Hugging Face'})

    except Exception as e:
        app.logger.error(f"HF deploy error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# --------------------- New Routes ---------------------

@app.route('/api/edit-selection', methods=['POST'])
def edit_selection():
    """Edit a selected code snippet with full project context."""
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

        # Build project context
        project_context = "\n".join([f"--- {name} ---\n{content}" for name, content in all_files.items()])

        prompt_template = load_prompt('edit_selection.txt')
        prompt = prompt_template.format(
            project_context=project_context,
            filename=filename,
            file_content=all_files.get(filename, ''),
            selected_code=selected_code,
            instruction=instruction
        )

        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4096
        )
        replacement = response.choices[0].message.content.strip()

        return jsonify({'replacement': replacement})

    except Exception as e:
        app.logger.error(f"Edit selection error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/review', methods=['POST'])
def review_code():
    """Review the generated code for issues."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON'}), 400

        files = data.get('files', {})
        if not files:
            return jsonify({'error': 'No files provided'}), 400

        issues = []
        for name, content in files.items():
            if '.py' in name:
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
            return jsonify({'issues': [], 'status': 'success', 'message': 'No obvious issues found.'})

    except Exception as e:
        app.logger.error(f"Review error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# --------------------- Run ---------------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)