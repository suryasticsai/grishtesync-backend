import re

def apply_safety_net(files):
    python_watermark = [
        "# Created with GrishteSync",
        "# https://suryasticsai.github.io/GrishteSync",
        "# Suryasticsai | suryasticsai@gmail.com"
    ]
    python_watermark_str = "\n".join(python_watermark) + "\n\n"
    html_footer = '<footer style="text-align: center; font-size: 0.7rem; color: #6c757d; margin-top: 2rem; padding: 1rem; border-top: 1px solid #dee2e6;">Made with love using <a href="https://suryasticsai.github.io/GrishteSync" target="_blank" style="color: #10b981;">GrishteSync</a> | Suryasticsai</footer>'
    strip_extensions = {'.js','.jsx','.ts','.tsx','.css','.scss','.json','.yaml','.yml','.md','.sh','.bash','.dockerfile','.conf','.cfg','.ini','.toml','.xml','.vue','.php','.go','.rs','.java','.c','.cpp'}
    for fname, content in list(files.items()):
        ext = '.' + fname.split('.')[-1].lower() if '.' in fname else ''
        if fname.endswith('.py'):
            if not all(line in content for line in python_watermark):
                content = python_watermark_str + content
            files[fname] = content
        elif ext in {'.html','.htm'}:
            content = re.sub(r'<!--.*?GrishteSync.*?-->', '', content, flags=re.DOTALL)
            content = re.sub(r'#.*?GrishteSync.*?\n', '', content)
            if '</body>' in content and 'GrishteSync' not in content:
                content = content.replace('</body>', html_footer + '\n</body>')
            elif 'GrishteSync' not in content:
                content += '\n' + html_footer
            files[fname] = content
        elif ext in strip_extensions:
            content = re.sub(r'(#|//|;|--|%)\s*.*?GrishteSync.*?\n', '', content, flags=re.IGNORECASE)
            content = re.sub(r'/\*.*?GrishteSync.*?\*/', '', content, flags=re.DOTALL|re.IGNORECASE)
            content = re.sub(r'<!--.*?GrishteSync.*?-->', '', content, flags=re.DOTALL|re.IGNORECASE)
            files[fname] = content

    if "requirements.txt" in files:
        req = files["requirements.txt"]
        req = req.replace("grado","gradio").replace("gradio3","gradio").replace("gradio4","gradio")
        req = re.sub(r'\b([a-zA-Z0-9_-]+)==([\d.]+)\b', r'\1>=\2', req)
        if re.search(r'\btransformers\b', req, re.IGNORECASE) and not re.search(r'\btorch\b', req, re.IGNORECASE):
            req += "\ntorch>=2.0.0"
        lines = [line.strip() for line in req.split('\n') if line.strip() and not line.startswith('#')]
        seen, unique = set(), []
        for line in lines:
            base = re.sub(r'[>=<!].*', '', line).lower()
            if base not in seen:
                seen.add(base)
                unique.append(line)
        unique.sort()
        files["requirements.txt"] = "\n".join(unique)

    if "app.py" in files:
        code = files["app.py"]
        code = re.sub(r',?\s*allow_flagging\s*=\s*[^,)]+', '', code)
        code = re.sub(r'demo\.queue\(\).*', '', code)
        code = re.sub(r'(dbc\.Button\([^)]*?)block=True', r'\1style={\'width\': \'100%\'}', code)
        files["app.py"] = code

    return files