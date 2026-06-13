"""
safety_net.py – Post‑generation code fixer for GrishteSync
Automatically corrects common AI mistakes in generated code.
"""

import re
from typing import Dict, Set

def apply_safety_net(files: Dict[str, str]) -> Dict[str, str]:
    """
    Fix common AI mistakes and inject proper watermarks.
    - Python files: add comment header.
    - HTML files: add visible footer (small one line).
    - All other code/config files: strip any GrishteSync comments.
    - Fixes requirements.txt (typos, exact pins, missing torch, dedup).
    - Removes allow_flagging, demo.queue(), fixes dash block=True.
    """
    # ============================================================
    # 1. WATERMARK HANDLING
    # ============================================================
    python_watermark = [
        "# Created with GrishteSync",
        "# https://suryasticsai.github.io/GrishteSync",
        "# Suryasticsai | suryasticsai@gmail.com"
    ]
    python_watermark_str = "\n".join(python_watermark) + "\n\n"
    
    html_footer = '<footer style="text-align: center; font-size: 0.7rem; color: #6c757d; margin-top: 2rem; padding: 1rem; border-top: 1px solid #dee2e6;">Made with ❤️ using <a href="https://suryasticsai.github.io/GrishteSync" target="_blank" style="color: #10b981;">GrishteSync</a> | Suryasticsai</footer>'
    
    # Extensions that should have watermark stripped (all non-Python, non-HTML)
    strip_extensions = {
        '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.css', '.scss', '.sass', '.less',
        '.json', '.yaml', '.yml', '.md', '.txt', '.sh', '.bash', '.zsh', '.ps1', '.bat',
        '.dockerfile', '.conf', '.cfg', '.ini', '.toml', '.xml', '.svg', '.vue', '.svelte',
        '.php', '.rb', '.go', '.rs', '.swift', '.kt', '.java', '.c', '.cpp', '.h', '.hpp',
        '.cs', '.fs', '.scala', '.clj', '.elm', '.erl', '.ex', '.exs', '.lua', '.r', '.jl',
        '.m', '.mm'
    }
    
    for filename, content in list(files.items()):
        ext = '.' + filename.split('.')[-1].lower() if '.' in filename else ''
        
        if filename.endswith('.py'):
            # Python: add comment header if missing
            if not all(line in content for line in python_watermark):
                content = python_watermark_str + content
            files[filename] = content
            
        elif ext in {'.html', '.htm'}:
            # HTML: inject visible footer
            # Remove any existing GrishteSync comments (AI might have added)
            content = re.sub(r'<!--.*?GrishteSync.*?-->', '', content, flags=re.DOTALL)
            content = re.sub(r'#.*?GrishteSync.*?\n', '', content)
            # Inject footer before </body> if not already present
            if '</body>' in content and 'GrishteSync' not in content:
                content = content.replace('</body>', html_footer + '\n</body>')
            elif 'GrishteSync' not in content:
                content += '\n' + html_footer
            files[filename] = content
            
        elif ext in strip_extensions:
            # All other code/config files: strip any GrishteSync comments
            # Single-line comments (#, //, ;, --, %)
            content = re.sub(r'(#|//|;|--|%)\s*.*?GrishteSync.*?\n', '', content, flags=re.IGNORECASE)
            # Multi-line comments (/* ... */)
            content = re.sub(r'/\*.*?GrishteSync.*?\*/', '', content, flags=re.DOTALL | re.IGNORECASE)
            # HTML/XML comments (<!-- ... -->) – already handled but for safety
            content = re.sub(r'<!--.*?GrishteSync.*?-->', '', content, flags=re.DOTALL | re.IGNORECASE)
            files[filename] = content
    
    # ============================================================
    # 2. REQUIREMENTS.TXT FIXES
    # ============================================================
    if "requirements.txt" in files:
        req = files["requirements.txt"]
        
        # Typo fixes
        req = req.replace("grado", "gradio")
        req = req.replace("gradio3", "gradio")
        req = req.replace("gradio4", "gradio")
        
        # Exact version pins -> >=
        req = re.sub(r'\b([a-zA-Z0-9_-]+)==([\d.]+)\b', r'\1>=\2', req)
        
        # If transformers used, ensure torch is present
        if re.search(r'\btransformers\b', req, re.IGNORECASE) and not re.search(r'\btorch\b', req, re.IGNORECASE):
            req = req.rstrip() + "\ntorch>=2.0.0"
        
        # Deduplicate lines (case‑insensitive by package name)
        lines = [line.strip() for line in req.split('\n') if line.strip() and not line.startswith('#')]
        seen = set()
        unique = []
        for line in lines:
            base = re.sub(r'[>=<!].*', '', line).lower()
            if base not in seen:
                seen.add(base)
                unique.append(line)
        unique.sort()
        files["requirements.txt"] = "\n".join(unique)
    
    # ============================================================
    # 3. GRADIO / DASH FIXES (app.py)
    # ============================================================
    if "app.py" in files:
        code = files["app.py"]
        # Remove allow_flagging
        code = re.sub(r',?\s*allow_flagging\s*=\s*[^,)]+', '', code)
        # Remove demo.queue()
        code = re.sub(r'demo\.queue\(\).*', '', code)
        # Fix dash bootstrap block=True -> style
        code = re.sub(r'(dbc\.Button\([^)]*?)block=True', r'\1style={\'width\': \'100%\'}', code)
        files["app.py"] = code
    
    return files
