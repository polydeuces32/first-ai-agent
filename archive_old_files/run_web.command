#!/bin/bash
# Double-click to start the web UI (macOS). Then open http://127.0.0.1:8765
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || { echo "Could not cd to $DIR"; read -p "Press Enter to close…"; exit 1; }
# Offline by default so it works without Ollama; set LLM_BACKEND=ollama in env to use a model
export LLM_BACKEND="${LLM_BACKEND:-none}"
if [ -f "$DIR/.venv/bin/python" ]; then
    "$DIR/.venv/bin/python" "$DIR/run_web.py"
else
    python3 "$DIR/run_web.py"
fi
echo ""
read -p "Press Enter to close…"
