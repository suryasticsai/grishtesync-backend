"""
safety_net.py - Post‑generation code fixer for GrishteSync
Automatically corrects common AI mistakes in generated code.
"""

import re
from typing import Dict, Set, List

# ------------------------------------------------------------------
# Helper: Fix requirements.txt content
# ------------------------------------------------------------------
def fix_requirements_content(req_content: str) -> str:
    """Apply basic fixes to requirements.txt."""
    # Typos
    req_content = req_content.replace("grado", "gradio")
    req_content = req_content.replace("gradio3", "gradio")
    req_content = req_content.replace("gradio4", "gradio")
    # Exact version pins -> >=
    req_content = re.sub(r'\b([a-zA-Z0-9_-]+)==([\d.]+)\b', r'\1>=\2', req_content)
    # Remove duplicate lines (case‑insensitive by package name)
    lines = [line.strip() for line in req_content.split('\n') if line.strip() and not line.startswith('#')]
    seen = {}
    unique = []
    for line in lines:
        base = re.sub(r'[>=<!].*', '', line).lower()
        if base not in seen:
            seen[base] = True
            unique.append(line)
    unique.sort()
    return "\n".join(unique)

# ------------------------------------------------------------------
# Core detection: framework → package + version
# ------------------------------------------------------------------
PACKAGE_RULES = [
    # Web frameworks
    (r'from flask import|import flask|Flask\(', 'flask', '2.0.0'),
    (r'from django\.|import django|DJANGO_SETTINGS_MODULE', 'django', '4.0.0'),
    (r'from fastapi import|FastApi\(', 'fastapi', '0.100.0'),
    (r'import uvicorn', 'uvicorn', '0.20.0'),
    (r'import gradio|from gradio import|gr\.Interface|gr\.Blocks|demo\.launch', 'gradio', '4.0.0'),
    (r'import streamlit|st\.', 'streamlit', '1.25.0'),
    (r'import dash|from dash import|dcc\.|dash\.Dash', 'dash', '2.14.0'),
    (r'dbc\.|dash_bootstrap_components', 'dash-bootstrap-components', '2.0.0'),
    
    # ML / AI
    (r'import torch|from torch import|torch\.nn', 'torch', '2.0.0'),
    (r'import tensorflow|from tensorflow import|tf\.keras', 'tensorflow', '2.13.0'),
    (r'import transformers|from transformers import|pipeline\(', 'transformers', '4.30.0'),
    (r'import langchain|from langchain', 'langchain', '0.1.0'),
    (r'import openai|from openai import|OpenAI\(', 'openai', '1.0.0'),
    (r'import anthropic|Anthropic\(', 'anthropic', '0.18.0'),
    (r'from llama_index|import llama_index', 'llama-index', '0.9.0'),
    (r'import sklearn|from sklearn\.', 'scikit-learn', '1.3.0'),
    (r'import keras|from keras\.', 'keras', '2.13.0'),
    
    # Data science
    (r'import pandas|pd\.', 'pandas', '2.0.0'),
    (r'import numpy|np\.', 'numpy', '1.24.0'),
    (r'import matplotlib|plt\.', 'matplotlib', '3.7.0'),
    (r'import seaborn|sns\.', 'seaborn', '0.12.0'),
    (r'import plotly|px\.|go\.Figure', 'plotly', '5.0.0'),
    (r'import altair|alt\.Chart', 'altair', '5.0.0'),
    
    # PDF / document processing
    (r'import PyPDF2|PdfReader|PdfWriter', 'PyPDF2', '3.0.0'),
    (r'import pdfplumber', 'pdfplumber', '0.10.0'),
    (r'from docx import|import docx', 'python-docx', '0.8.11'),
    (r'import openpyxl', 'openpyxl', '3.1.0'),
    (r'from reportlab', 'reportlab', '4.0.0'),
    
    # Databases
    (r'import sqlalchemy|create_engine', 'sqlalchemy', '2.0.0'),
    (r'import psycopg2', 'psycopg2-binary', '2.9.0'),
    (r'import pymongo|MongoClient', 'pymongo', '4.5.0'),
    (r'import redis', 'redis', '5.0.0'),
    
    # API / networking
    (r'import requests|requests\.get', 'requests', '2.31.0'),
    (r'import httpx', 'httpx', '0.24.0'),
    (r'from bs4 import|BeautifulSoup', 'beautifulsoup4', '4.12.0'),
    (r'import scrapy', 'scrapy', '2.11.0'),
    
    # Async / task queues
    (r'import celery|@app\.task', 'celery', '5.3.0'),
    (r'import aiohttp', 'aiohttp', '3.8.0'),
    
    # Utilities
    (r'PIL\.|from PIL import', 'pillow', '10.0.0'),
    (r'cv2\.|import cv2', 'opencv-python', '4.8.0'),
    (r'import dotenv|load_dotenv', 'python-dotenv', '1.0.0'),
    (r'import yaml|YAML\(', 'pyyaml', '6.0.0'),
    (r'import pytest', 'pytest', '7.4.0'),
]

ALIAS_MAP = {
    'sklearn': 'scikit-learn',
    'bs4': 'beautifulsoup4',
    'PIL': 'pillow',
    'cv2': 'opencv-python',
    'dash_bootstrap_components': 'dash-bootstrap-components',
    'dotenv': 'python-dotenv',
    'yaml': 'pyyaml',
}

# Standard library modules to ignore
STDLIB = {
    'os', 'sys', 're', 'json', 'time', 'datetime', 'math', 'random', 'io', 'pathlib',
    'typing', 'collections', 'itertools', 'functools', 'subprocess', 'tempfile', 'shutil',
    'argparse', 'logging', 'unittest', 'hashlib', 'base64', 'urllib', 'http', 'email',
    'html', 'xml', 'csv', 'sqlite3', 'threading', 'multiprocessing', 'asyncio', 'socket',
    'ssl', 'secrets', 'string', 'textwrap', 'pprint', 'copy', 'weakref', 'abc', 'enum',
    'dataclasses', 'contextlib', 'glob', 'fnmatch', 'pickle', 'struct', 'zlib', 'gzip',
    'zipfile', 'tarfile', 'io', 'codecs', 'getpass', 'platform', 'signal', 'atexit'
}

# ------------------------------------------------------------------
# Detect packages from code
# ------------------------------------------------------------------
def detect_packages(code: str) -> Set[str]:
    """Scan code and return set of PyPI package strings (e.g., 'flask>=2.0.0')."""
    packages = set()
    
    # 1. Rule‑based detection
    for pattern, pkg, version in PACKAGE_RULES:
        if re.search(pattern, code, re.IGNORECASE):
            packages.add(f"{pkg}>={version}")
    
    # 2. Import statement parsing
    import_re = re.compile(r'^(?:from|import)\s+([a-zA-Z0-9_]+)', re.MULTILINE)
    for match in import_re.findall(code):
        if match in ALIAS_MAP:
            packages.add(f"{ALIAS_MAP[match]}>=0.0.0")
        elif match not in STDLIB:
            packages.add(f"{match}>=0.0.0")
    
    return packages

# ------------------------------------------------------------------
# Main safety net function
# ------------------------------------------------------------------
def apply_safety_net(files: Dict[str, str]) -> Dict[str, str]:
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
    for name, content in files.items():
        if name.endswith('.py'):
            py_files[name] = content
            all_py_code += content + "\n\n"
    
    # ------------------------------------------------------------------
    # Fix requirements.txt (create if missing)
    # ------------------------------------------------------------------
    req_content = files.get("requirements.txt", "")
    
    # Detect missing packages from code
    detected = detect_packages(all_py_code)
    
    # Merge with existing requirements
    current_pkgs = set()
    for line in req_content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#'):
            base = re.sub(r'[>=<!].*', '', line).lower()
            current_pkgs.add(base)
    
    for pkg_line in detected:
        base = re.sub(r'[>=<!].*', '', pkg_line).lower()
        if base not in current_pkgs:
            req_content = req_content.rstrip() + "\n" + pkg_line
            current_pkgs.add(base)
    
    req_content = fix_requirements_content(req_content)
    files["requirements.txt"] = req_content
    
    # ------------------------------------------------------------------
    # Fix each Python file
    # ------------------------------------------------------------------
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
        
        # Ensure watermark present (at the very beginning)
        if not all(line in code for line in watermark):
            code = watermark_str + code
        
        files[fname] = code
    
    # ------------------------------------------------------------------
    # Fix HTML files (basic)
    # ------------------------------------------------------------------
    for fname, content in html_files.items():
        # Ensure viewport meta tag
        if '<meta name="viewport"' not in content:
            content = content.replace('<head>', '<head>\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">')
        files[fname] = content
    
    return files