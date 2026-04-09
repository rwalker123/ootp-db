#!/bin/bash
# OOTP MCP server (stdio). MCP clients normally launch this automatically; use this script
# to verify the venv, deps, or run with MCP Inspector. Blocks waiting for JSON-RPC on stdin.
cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
  echo "✗ Python not found. Install it from https://python.org or: brew install python"
  exit 1
fi

[ -d ".venv" ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

echo "Checking for updates..."
TMPFILE=$(mktemp)
if [ -d ".git" ]; then
  if git fetch origin --quiet 2>/dev/null && BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null); then
    if [ "$BEHIND" -gt 0 ]; then
      echo '{"updates_available": true, "install_type": "git"}' > "$TMPFILE"
      echo "⚠ Update available — run: git pull"
    else
      echo '{"updates_available": false, "install_type": "git"}' > "$TMPFILE"
      echo "✓ Up to date"
    fi
  else
    echo '{"updates_available": null, "install_type": "git"}' > "$TMPFILE"
    echo "⚠ Unable to check for updates"
  fi
else
  if [ ! -f ".downloaded" ]; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" > .downloaded
  fi
  DOWNLOADED=$(cat .downloaded)
  LATEST=$(curl -s --max-time 5 "https://api.github.com/repos/rwalker123/ootp-db/commits/main" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['commit']['committer']['date'])" 2>/dev/null || echo "")
  if [ -n "$LATEST" ]; then
    if [[ "$LATEST" > "$DOWNLOADED" ]]; then
      echo '{"updates_available": true, "install_type": "zip"}' > "$TMPFILE"
      echo "⚠ Update available — download: https://github.com/rwalker123/ootp-db/archive/refs/heads/main.zip"
    else
      echo '{"updates_available": false, "install_type": "zip"}' > "$TMPFILE"
      echo "✓ Up to date"
    fi
  else
    echo '{"updates_available": null, "install_type": "zip"}' > "$TMPFILE"
    echo "⚠ Unable to check for updates"
  fi
fi
mv "$TMPFILE" .update-status

echo ""
echo "Starting OOTP MCP server (stdio) — waiting for a client on stdin."
echo "Tip: An MCP client usually starts this automatically when configured; use this for testing or MCP Inspector."
echo ""
exec .venv/bin/python3 mcp_server.py
