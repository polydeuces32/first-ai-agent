# How to run the agent (without the IDE)

You can use the agent from the terminal, by double‑clicking, or in a browser. No Cursor/IDE required after setup.

---

## 1. Terminal (any OS)

From the project folder:

```bash
cd /path/to/first-ai-agent
.venv/bin/python -m src.agent
```

Or with `LLM_BACKEND=none` (offline, no model):

```bash
LLM_BACKEND=none .venv/bin/python -m src.agent
```

---

## 2. Double‑click launcher (macOS)

- **Terminal chat:** double‑click **`run.command`** in Finder.  
  A Terminal window opens and runs the agent. No need to open Cursor or type commands.

- **Web UI:** double‑click **`run_web.command`** in Finder.  
  Then open **http://127.0.0.1:8765** in your browser and chat there.

*(First time: if macOS says the file is from an unidentified developer, right‑click → Open → Open.)*

---

## 3. Web UI (any OS)

Run the server once, then use the agent in your browser:

```bash
cd /path/to/first-ai-agent
.venv/bin/python run_web.py
```

Open **http://127.0.0.1:8765** and type in the box. Same commands and questions as in the terminal (help, ask about a doc, read doc, etc.). Stays local; no extra dependencies.

---

## Summary

| How              | What you do                    | Where you interact        |
|------------------|---------------------------------|----------------------------|
| Terminal         | `python -m src.agent`           | Same terminal             |
| Double‑click     | Double‑click `run.command`      | Terminal window           |
| Web              | `python run_web.py` → open URL  | Browser                   |

All options use the same agent logic and docs in `data/documents/`.
