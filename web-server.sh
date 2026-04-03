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

# Check for updates
echo "Checking for updates..."
if [ -d ".git" ]; then
  git fetch origin --quiet 2>/dev/null
  BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null || echo "0")
  if [ "$BEHIND" -gt 0 ] 2>/dev/null; then
    echo '{"updates_available": true, "install_type": "git"}' > .update-status
    echo "⚠ Update available — run: git pull"
  else
    echo '{"updates_available": false, "install_type": "git"}' > .update-status
    echo "✓ Up to date"
  fi
else
  if [ ! -f ".downloaded" ]; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" > .downloaded
  fi
  DOWNLOADED=$(cat .downloaded)
  LATEST=$(curl -s --max-time 5 "https://api.github.com/repos/rwalker123/ootp-db/commits/main" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['commit']['committer']['date'])" 2>/dev/null || echo "")
  if [ -n "$LATEST" ] && [[ "$LATEST" > "$DOWNLOADED" ]]; then
    echo '{"updates_available": true, "install_type": "zip"}' > .update-status
    echo "⚠ Update available — download: https://github.com/rwalker123/ootp-db/archive/refs/heads/main.zip"
  else
    echo '{"updates_available": false, "install_type": "zip"}' > .update-status
    echo "✓ Up to date"
  fi
fi

open http://localhost:8000
.venv/bin/python3 server.py
