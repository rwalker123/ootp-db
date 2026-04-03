#!/bin/bash
cd "$(dirname "$0")"

# Check Python is installed
if ! command -v python3 &>/dev/null; then
  echo "✗ Python not found. Install it from https://python.org or: brew install python"
  exit 1
fi

# Create venv if missing
[ -d ".venv" ] || python3 -m venv .venv

# Install/update packages
.venv/bin/pip install -q -r requirements.txt

open http://localhost:8000
.venv/bin/python3 server.py
