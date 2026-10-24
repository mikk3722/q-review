#!/bin/bash
# Starts Q-Review from the source code on a Mac.
# The first time it makes a Python environment (.venv) with PyQt6 and FFmpeg (takes a minute).
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install it from https://www.python.org/downloads/ and try again."
  read -n 1 -s -r -p "Press a key to close"; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First start: installing PyQt6 and FFmpeg into .venv …"
  python3 -m venv .venv || { read -n 1 -s -r -p "Could not make .venv – press a key"; exit 1; }
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || { read -n 1 -s -r -p "Install failed – press a key"; exit 1; }
fi
.venv/bin/python q_review.py "$@"
