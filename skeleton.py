"""
skeleton.py – Reference skeletons for few‑shot prompting.
Each skeleton is a complete, production‑ready example of a common app pattern.
The AI should follow the structure and adapt the logic to the user's request.
"""

# ============================================================
# Skeleton 1: Gradio PDF Search (RAG‑style)
# ============================================================
GRADIO_RAG_SKELETON = '''
# Created with GrishteSync
# https://suryasticsai.github.io/GrishteSync
# Suryasticsai | suryasticsai@gmail.com

import gradio as gr
import PyPDF2

def extract_text_from_pdf(file):
    """Extract all text from a PDF file."""
    reader = PyPDF2.PdfReader(file.name)
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text()
    return full_text

def search_pdf(file, search_term):
    """Search for a term in the PDF and return matching pages with preview."""
    if file is None:
        return "Please upload a PDF file."
    if not search_term.strip():
        return "Please enter a search term."
    
    try:
        reader = PyPDF2.PdfReader(file.name)
        results = []
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if search_term.lower() in text.lower():
                preview = text[:300].replace('\\n', ' ')
                results.append(f"📄 Page {page_num+1}:\\n{preview}...\\n")
        if not results:
            return f"No matches found for '{search_term}'."
        return "\\n".join(results)
    except Exception as e:
        return f"Error: {str(e)}"

demo = gr.Interface(
    fn=search_pdf,
    inputs=[
        gr.File(label="Upload PDF", type="filepath"),
        gr.Textbox(label="Search Term", placeholder="e.g., machine learning")
    ],
    outputs=gr.Textbox(label="Results", lines=15),
    title="PDF Search RAG App",
    description="Upload a PDF and search for any word or phrase."
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
'''

# ============================================================
# Skeleton 2: Flask REST API (CRUD example)
# ============================================================
FLASK_API_SKELETON = '''
# Created with GrishteSync
# https://suryasticsai.github.io/GrishteSync
# Suryasticsai | suryasticsai@gmail.com

from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory storage (for demo purposes)
items = []
next_id = 1

@app.route('/items', methods=['GET'])
def get_items():
    """Return all items."""
    return jsonify(items)

@app.route('/items/<int:item_id>', methods=['GET'])
def get_item(item_id):
    """Return a single item by ID."""
    item = next((i for i in items if i['id'] == item_id), None)
    if item is None:
        return jsonify({'error': 'Item not found'}), 404
    return jsonify(item)

@app.route('/items', methods=['POST'])
def create_item():
    """Create a new item."""
    global next_id
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': 'Name is required'}), 400
    new_item = {
        'id': next_id,
        'name': data['name'],
        'description': data.get('description', '')
    }
    items.append(new_item)
    next_id += 1
    return jsonify(new_item), 201

@app.route('/items/<int:item_id>', methods=['PUT'])
def update_item(item_id):
    """Update an existing item."""
    data = request.get_json()
    item = next((i for i in items if i['id'] == item_id), None)
    if item is None:
        return jsonify({'error': 'Item not found'}), 404
    if 'name' in data:
        item['name'] = data['name']
    if 'description' in data:
        item['description'] = data['description']
    return jsonify(item)

@app.route('/items/<int:item_id>', methods=['DELETE'])
def delete_item(item_id):
    """Delete an item."""
    global items
    item = next((i for i in items if i['id'] == item_id), None)
    if item is None:
        return jsonify({'error': 'Item not found'}), 404
    items = [i for i in items if i['id'] != item_id]
    return jsonify({'message': 'Deleted'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
'''

# ============================================================
# Skeleton 3: Streamlit Data Dashboard
# ============================================================
STREAMLIT_DASHBOARD_SKELETON = '''
# Created with GrishteSync
# https://suryasticsai.github.io/GrishteSync
# Suryasticsai | suryasticsai@gmail.com

import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Data Dashboard", layout="wide")

st.title("📊 Data Dashboard")
st.markdown("Upload a CSV file and explore the data interactively.")

# File uploader
uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

if uploaded_file is not None:
    # Load data
    df = pd.read_csv(uploaded_file)
    st.success(f"Loaded {len(df)} rows and {len(df.columns)} columns.")
    
    # Show raw data
    with st.expander("Preview raw data"):
        st.dataframe(df.head(100))
    
    # Column selection for analysis
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if numeric_cols:
        col1, col2 = st.columns(2)
        with col1:
            x_axis = st.selectbox("X‑axis", numeric_cols)
        with col2:
            y_axis = st.selectbox("Y‑axis", numeric_cols)
        
        st.subheader("Scatter Plot")
        st.scatter_chart(df[[x_axis, y_axis]])
    
    # Summary statistics
    st.subheader("Summary Statistics")
    st.write(df.describe())
    
    # Filtering sidebar
    st.sidebar.header("Filter Data")
    filter_col = st.sidebar.selectbox("Filter by column", df.columns)
    if filter_col:
        unique_vals = df[filter_col].dropna().unique()
        selected = st.sidebar.multiselect("Select values", unique_vals)
        if selected:
            filtered_df = df[df[filter_col].isin(selected)]
            st.write(f"Filtered to {len(filtered_df)} rows")
            st.dataframe(filtered_df)
else:
    st.info("👈 Please upload a CSV file to get started.")
'''

# ============================================================
# Skeleton 4: FastAPI with Pydantic (for completeness)
# ============================================================
FASTAPI_SKELETON = '''
# Created with GrishteSync
# https://suryasticsai.github.io/GrishteSync
# Suryasticsai | suryasticsai@gmail.com

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI()

class Item(BaseModel):
    name: str
    description: str = ""
    price: float
    tax: float = 0.0

# In‑memory storage
items_db = []
next_id = 1

@app.get("/")
def root():
    return {"message": "Welcome to the FastAPI skeleton"}

@app.post("/items/", response_model=dict)
def create_item(item: Item):
    global next_id
    new_item = item.dict()
    new_item["id"] = next_id
    items_db.append(new_item)
    next_id += 1
    return {"id": new_item["id"], **new_item}

@app.get("/items/", response_model=List[dict])
def list_items():
    return items_db

@app.get("/items/{item_id}")
def get_item(item_id: int):
    for item in items_db:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Item not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
'''

# ============================================================
# Utility to get skeleton by name
# ============================================================
SKELETONS = {
    "gradio_rag": GRADIO_RAG_SKELETON,
    "flask_api": FLASK_API_SKELETON,
    "streamlit_dashboard": STREAMLIT_DASHBOARD_SKELETON,
    "fastapi": FASTAPI_SKELETON,
}

def get_skeleton(name: str) -> str:
    """Return the skeleton code for a given name."""
    return SKELETONS.get(name, "")

if __name__ == "__main__":
    # Quick test: print the Gradio skeleton
    print(get_skeleton("gradio_rag"))