<p align="center">
  <img src="https://i.ibb.co/RGmb4FKk/1781072041102.png" alt="GrishteSync Logo" width="150" />
</p> 
#  GrishteSync Backend
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.0%2B-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Groq](https://img.shields.io/badge/Groq-LLM-FF6B6B?logo=groq&logoColor=white)](https://groq.com/)
[![CDN](https://img.shields.io/badge/CDN-jsDelivr-FFB13B?logo=jsdelivr&logoColor=white)](https://www.jsdelivr.com/)
[![Deploy](https://img.shields.io/badge/Deploy-Render-46C3C8?logo=render&logoColor=white)](https://render.com/)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-222222?logo=githubpages&logoColor=white)](https://suryasticsai.github.io/grishtesync-backend/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**The brain behind the GrishteSync AI coding assistant.**  
A Flask‑based REST API that delivers AI‑powered code generation, intelligent editing, automated code review, and one‑click deployments to GitHub and Hugging Face Spaces.

---

## 🌐 Live Links

| Component | URL |
| :-------- | :-- |
| **⚙️ Backend API** | [https://grishtesync-backend.onrender.com/](https://grishtesync-backend.onrender.com/) |
| **📦 SDK Demo Frontend** | [https://suryasticsai.github.io/grishtesync-backend/](https://suryasticsai.github.io/grishtesync-backend/) |
| **📜 JavaScript Client SDK** | [https://cdn.jsdelivr.net/gh/suryasticsai/grishtesync-backend@main/static/grishtesync-client.js](https://cdn.jsdelivr.net/gh/suryasticsai/grishtesync-backend@main/static/grishtesync-client.js) |

---

## ✨ Key Features

- 🤖 **AI Code Generation** – Turn natural‑language prompts into full project codebases using Groq's Llama 3.3 70B.
- ✂️ **Inline AI Editing** – Select and refine specific code blocks with simple instructions.
- 🔎 **Automated Code Review** – Instantly catch syntax errors, missing imports, and leftover TODOs.
- 🔐 **GitHub OAuth 2.0** – Secure, seamless authentication to delegate repository operations.
- 🚀 **One‑Click Deploy to GitHub** – Automatically create a repo, push files, and open a Pull Request.
- 🤗 **One‑Click Deploy to Hugging Face** – Push code to a brand‑new or existing Hugging Face Space.
- 📦 **Zero‑Dependency JavaScript SDK** – A fully featured, production‑ready client for any vanilla JS project.
- 🌍 **CORS Enabled** – Works with any frontend, regardless of where it's hosted.

---

## 🛠 Tech Stack

- **Backend** – Flask (Python 3.9+)
- **AI / LLM** – Groq API (model: `llama-3.3-70b-versatile`)
- **Integrations** – GitHub API, Hugging Face Hub API
- **Authentication** – OAuth 2.0 (GitHub)
- **Hosting** – Render (backend) + GitHub Pages (frontend demo)

---

## 🚀 Getting Started (Local Development)

### 1. Clone the repository

```
git clone https://github.com/suryasticsai/grishtesync-backend.git
cd grishtesync-backend

```

### 2. Create and activate a virtual environment

```
python -m venv venv
source venv/bin/activate      # On Windows: venv\Scripts\activate

```

### 3. Install dependencies


```
pip install -r requirements.txt

```

### 4. Configure environment variables
Create a `.env` file in the project root:

```
GROQ_API_KEY=your_groq_api_key
GITHUB_CLIENT_ID=your_github_oauth_client_id
GITHUB_CLIENT_SECRET=your_github_oauth_client_secret
FRONTEND_URL=http://localhost:3000   # Your frontend URL for OAuth redirect
HF_API_TOKEN=your_huggingface_token  # Optional – can be passed per request
PORT=5000

```

### 5. Run the server

```
python app.py

```

The API will be available at `http://localhost:5000`.

---

## 🔑 Environment Variables

| Variable | Required | Description |
| :------- | :------- | :---------- |
| `GROQ_API_KEY` | ✅ Yes | Your API key from [Groq Cloud](https://console.groq.com/). |
| `GITHUB_CLIENT_ID` | ✅ Yes | OAuth App Client ID from GitHub Developer Settings. |
| `GITHUB_CLIENT_SECRET` | ✅ Yes | OAuth App Client Secret from GitHub. |
| `FRONTEND_URL` | ✅ Yes | Full URL of your frontend (where users are redirected after login). |
| `HF_API_TOKEN` | ⚠️ Optional | Hugging Face token (can also be passed in the request body). |
| `PORT` | ⚠️ Optional | Port for the Flask server (default: `5000`). |

---

## 📡 API Endpoints

| Method | Endpoint | Description | Auth Required |
| :----- | :------- | :---------- | :------------ |
| `GET` | `/` | Health check / service status. | ❌ No |
| `GET` | `/auth/login` | Redirect to GitHub OAuth authorization page. | ❌ No |
| `GET` | `/auth/callback` | GitHub OAuth callback – handles token exchange and redirect. | ❌ No |
| `POST` | `/api/generate` | Generate code from a prompt. Optionally pass `repo` for context. | ⚠️ Optional (for private repos) |
| `POST` | `/api/edit-selection` | Edit a selected code block using AI. | ❌ No |
| `POST` | `/api/review` | Review files for syntax issues and TODOs. | ❌ No |
| `POST` | `/api/deploy` | Deploy files to a new GitHub repository and open a PR. | ✅ Yes (GitHub Token) |
| `POST` | `/api/deploy-hf` | Deploy files to a Hugging Face Space. | ✅ Yes (HF Token) |

---

## 📦 JavaScript Client SDK

This repository includes a **zero‑dependency, production‑ready** JavaScript client that wraps every API endpoint.

### Installation (via CDN)


```html
<!-- As an ES Module (recommended) -->
<script type="module">
  import { healthCheck, generateCode, deployToGitHub } from "https://cdn.jsdelivr.net/gh/suryasticsai/grishtesync-backend@main/static/grishtesync-client.js";
</script>

<!-- Or as a classic script -->
<script src="https://cdn.jsdelivr.net/gh/suryasticsai/grishtesync-backend@main/static/grishtesync-client.js"></script>
<script>
  // All methods available under window.grishtesync
  grishtesync.healthCheck().then(console.log);
</script>

```

### Quick Usage Example


```javascript
// 1. Health check – no authentication required
const status = await grishtesync.healthCheck();
console.log('Backend status:', status);

// 2. Generate code – no authentication required
const result = await grishtesync.generateCode('Create a Flask app with a /hello endpoint');
console.log('Generated files:', result.files);

// 3. Review code – no authentication required
const review = await grishtesync.reviewCode({ 'app.py': "print('hello')" });
console.log('Issues found:', review.issues);

// 4. Handle OAuth callback – automatically captures token from URL
grishtesync.captureAuthTokenFromUrl();

// 5. Deploy to GitHub – requires a valid auth token
const token = grishtesync.getAuthToken();
if (token) {
  const deployResult = await grishtesync.deployToGitHub(
    'my-new-repo',
    { 'app.py': "print('Hello World')" },
    '1.0.0',
    token
  );
  console.log('Repository created:', deployResult.repo_url);
}

```

### Event Bus for UI Feedback

The SDK emits `start`, `end`, and `error` events so you can easily show loading states and feedback:


```javascript
grishtesync.on('start', (payload) => console.log(`⏳ ${payload.endpoint} started`));
grishtesync.on('end', (payload) => console.log(`✅ ${payload.endpoint} finished`));
grishtesync.on('error', (err) => console.error('❌', err.message));

``` 

---

## 🚢 Deployment

### Backend (Render / Heroku / Fly.io)

1. Push this repository to GitHub.
2. Create a new Web Service on Render (or your preferred platform).
3. Connect your GitHub repository.
4. Set the required environment variables.
5. Use the start command: `gunicorn app:app` (or `python app.py`).

### Frontend Demo (GitHub Pages)

Because this repository includes an `index.html`, you can host it as a static site:

1. Go to **Settings → Pages** on your GitHub repository.
2. Select the `main` branch and the `/ (root)` folder.
3. Click **Save**.
4. Your demo will be live at `https://suryasticsai.github.io/grishtesync-backend/`.

---

## 🤝 Contributing

Contributions are welcome and appreciated! Feel free to open issues or submit pull requests.

**Attribution requirement** – All generated code includes the following watermark:

```
# Created with GrishteSync
# https://suryasticsai.github.io/GrishteSync
# Suryasticsai | suryasticsai@gmail.com
```

Please keep this attribution intact when using the generated code.

---

## 📄 License

This project is open‑source and available under the [MIT License](LICENSE).

---

## 👤 Author

**Suryasticsai**  
- GitHub: [@suryasticsai](https://github.com/suryasticsai)  
- Email: suryasticsai@gmail.com  

---

## ⭐ Support

If you find this project useful, please give it a ⭐ on GitHub – it helps others discover it too!