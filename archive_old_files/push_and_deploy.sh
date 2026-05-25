#!/bin/bash
# Run this AFTER you create the repo on GitHub (see steps below).
# Usage: ./push_and_deploy.sh YOUR_GITHUB_USERNAME
# Example: ./push_and_deploy.sh vizhnay
set -e
cd "$(dirname "$0")"
USER="${1:?Usage: ./push_and_deploy.sh YOUR_GITHUB_USERNAME}"
REPO_URL="https://github.com/${USER}/first-ai-agent.git"
if git remote add origin "$REPO_URL" 2>/dev/null; then
  echo "Added remote origin."
else
  git remote set-url origin "$REPO_URL"
  echo "Updated remote origin."
fi
git push -u origin main
echo ""
echo "Pushed to GitHub. Now on Render:"
echo "1. Connect the repo: https://github.com/${USER}/first-ai-agent"
echo "2. Build: pip install -r requirements.txt"
echo "3. Start: python run_web.py"
echo "4. Create Web Service — then copy your URL."
