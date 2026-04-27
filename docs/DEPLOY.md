# Deploy so anyone can open a link (no terminal needed)

Deploy to **Render** (free tier). You get a URL like `https://first-ai-agent-xxx.onrender.com` — share it and people can use the agent in their browser.

---

## 1. Put the project on GitHub

1. Create a repo on [github.com](https://github.com/new) (e.g. `first-ai-agent`).
2. In your project folder:

```bash
cd ~/first-ai-agent
git init
git add .
# Don't commit .venv or big/cache files
echo ".venv/" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
echo ".DS_Store" >> .gitignore
git add .
git commit -m "Deploy first-ai-agent"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/first-ai-agent.git
git push -u origin main
```

(Replace `YOUR_USERNAME` with your GitHub username.)

---

## 2. Deploy on Render

1. Go to [render.com](https://render.com) and sign up (free).
2. **Dashboard** → **New** → **Web Service**.
3. **Connect** your GitHub repo `first-ai-agent`.
4. Settings:
   - **Name:** `first-ai-agent` (or any name).
   - **Environment:** `Python 3`.
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `python run_web.py`
   - **Instance type:** Free.
5. **Environment** (optional): add `LLM_BACKEND` = `none` (so it runs offline).
6. Click **Create Web Service**. Wait a few minutes.
7. When it’s live, use the URL Render shows (e.g. `https://first-ai-agent-xxx.onrender.com`).

---

## 3. Share the link

Send that URL to your friend. They open it in any browser (phone or computer) — no install, no terminal.  
Free tier may sleep after ~15 min of no use; the first open might take a few seconds to wake.

---

## Optional: Railway

1. Go to [railway.app](https://railway.app), sign up, **New Project** → **Deploy from GitHub**.
2. Select your `first-ai-agent` repo.
3. Railway will detect Python. Set **Start command:** `python run_web.py`.
4. Add variable `LLM_BACKEND` = `none`.
5. **Deploy**. Use the generated URL.
