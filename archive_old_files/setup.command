#!/bin/bash
# One-time setup for a friend: create .venv and install dependencies.
# Double-click (Mac) or run: ./setup.command
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
echo "Setting up first-ai-agent in $DIR"
if [ -d .venv ]; then
    echo ".venv already exists. Run run_web.command or: .venv/bin/python run_web.py"
    read -p "Press Enter to close…"
    exit 0
fi
python3 -m venv .venv || { echo "Need Python 3.8+. Install from python.org"; read -p "Press Enter to close…"; exit 1; }
.venv/bin/pip install -r requirements.txt
echo "Done. Double-click run_web.command or run: .venv/bin/python run_web.py"
echo "Then open http://127.0.0.1:8765 in your browser."
read -p "Press Enter to close…"
