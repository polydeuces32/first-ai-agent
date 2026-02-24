#!/bin/bash
# Free the port(s) used by the web server so you can start run_web again.
# Double-click or run: ./reset_web.command
for port in 8765 8766 8767 8768 8769; do
  pid=$(lsof -t -i :$port 2>/dev/null)
  if [ -n "$pid" ]; then
    kill -9 $pid 2>/dev/null && echo "Stopped process $pid on port $port" || echo "Could not stop port $port"
  fi
done
echo "Done. You can run run_web.command or: .venv/bin/python run_web.py"
read -p "Press Enter to close…"
