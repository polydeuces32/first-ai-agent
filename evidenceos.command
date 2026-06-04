#!/bin/bash
cd "$(dirname "$0")/backend" || exit 1
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python evidenceos_cli.py repl "$@"
else
  exec python3 evidenceos_cli.py repl "$@"
fi
