#!/bin/bash
# Double-click this file in Finder to run the agent in Terminal (macOS).
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || { echo "Could not cd to $DIR"; read -p "Press Enter to close…"; exit 1; }
# Offline by default; set LLM_BACKEND=ollama (and run Ollama) to use a model
export LLM_BACKEND="${LLM_BACKEND:-none}"
if [ -f "$DIR/.venv/bin/python" ]; then
    "$DIR/.venv/bin/python" -m src.agent
else
    python3 -m src.agent
fi
echo ""
read -p "Press Enter to close…"
