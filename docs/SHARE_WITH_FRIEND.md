# How to send this to a friend to test

## What you do (sender)

### 1. Zip the project **without** the virtual env

Don’t include `.venv` (it’s large and machine-specific). Your friend will create their own.

**Option A – From the project folder in Terminal:**

```bash
cd ~
zip -r first-ai-agent.zip first-ai-agent -x "first-ai-agent/.venv/*" -x "first-ai-agent/__pycache__/*" -x "*__pycache__*" -x "*.pyc"
```

**Option B – In Finder:**  
Copy the whole `first-ai-agent` folder to a new folder (e.g. `first-ai-agent-share`), delete the `.venv` folder inside it, then right‑click the folder → “Compress”.

### 2. Send the zip

Use whatever you like: email (if small enough), Google Drive, Dropbox, WeTransfer, AirDrop (Mac to Mac), etc.

### 3. Tell your friend

- They need **Python 3.8+** installed ([python.org](https://www.python.org/downloads/)).
- They should read **“Friend: first-time setup”** below (or send them that section).

---

## Friend: first-time setup

### 1. Unzip

Unzip `first-ai-agent.zip` somewhere (e.g. Desktop or Documents). Open a terminal in that folder (e.g. `cd` into `first-ai-agent`).

### 2. One-time setup (create env and install deps)

**On Mac/Linux:**

```bash
cd first-ai-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**On Windows (PowerShell):**

```powershell
cd first-ai-agent
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Or double‑click **`setup.command`** (Mac) if you have it — it does the same.

### 3. Run it

**Web UI (easiest):**

- **Mac:** Double‑click **`run_web.command`**, then open **http://127.0.0.1:8765** in your browser.
- **Or in terminal:**  
  `./.venv/bin/python run_web.py` (Mac/Linux)  
  `\.venv\Scripts\python run_web.py` (Windows)

**Terminal only:**

- **Mac:** Double‑click **`run.command`**.
- **Or:** `./.venv/bin/python -m src.agent` (Mac/Linux).

### 4. Try these

- Type **help** — see commands and question examples.
- Drop a PDF into `data/documents/` and type **list documents** to see it.
- Type **ask about <your doc name>** — then ask follow‑up questions.

Everything runs **offline** (no API keys, no internet needed for the agent).
