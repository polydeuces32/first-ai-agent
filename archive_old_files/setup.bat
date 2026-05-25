@echo off
REM One-time setup for a friend (Windows): create .venv and install dependencies.
cd /d "%~dp0"
if exist .venv (
    echo .venv already exists. Run: .venv\Scripts\python run_web.py
    pause
    exit /b 0
)
python -m venv .venv
if errorlevel 1 (
    echo Need Python 3.8+. Install from python.org
    pause
    exit /b 1
)
.venv\Scripts\pip install -r requirements.txt
echo Done. Run: .venv\Scripts\python run_web.py
echo Then open http://127.0.0.1:8765 in your browser.
pause
