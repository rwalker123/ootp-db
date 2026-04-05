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

# Check if a server is already running on port 8000
if curl -s --max-time 1 http://localhost:8000/status >/dev/null 2>&1; then
  EXISTING_PID=$(lsof -ti tcp:8000 2>/dev/null)
  echo "⚠ A server is already running on port 8000 (PID ${EXISTING_PID:-unknown})."
  printf "  [k] Kill it and start fresh  [u] Use it (open browser)  [q] Quit: "
  read -r choice
  case "$choice" in
    k|K)
      if [ -n "$EXISTING_PID" ]; then
        kill "$EXISTING_PID" 2>/dev/null
        sleep 0.5
        echo "✓ Killed existing server (PID $EXISTING_PID)"
      fi
      ;;
    u|U)
      open http://localhost:8000
      exit 0
      ;;
    *)
      echo "Quit."
      exit 0
      ;;
  esac
fi

.venv/bin/python3 server.py &
SERVER_PID=$!
echo "Starting server (PID $SERVER_PID)..."

# Wait for server to be ready (up to 10s)
ready=0
for i in $(seq 1 20); do
  if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "✗ Server exited unexpectedly. Check for errors above."
    exit 1
  fi
  if curl -s --max-time 1 http://localhost:8000/status >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done

if [ $ready -eq 0 ]; then
  echo "✗ Server did not become ready after 10s. Check for errors above."
  kill $SERVER_PID 2>/dev/null
  exit 1
fi

open http://localhost:8000

# Interactive command loop
echo "Server running. Commands: [r] restart  [q] quit"
while true; do
  printf "> "
  read -r cmd
  case "$cmd" in
    r|R)
      echo "Restarting server (killing PID $SERVER_PID)..."
      kill "$SERVER_PID" 2>/dev/null
      wait "$SERVER_PID" 2>/dev/null
      .venv/bin/python3 server.py &
      SERVER_PID=$!
      echo "Starting server (PID $SERVER_PID)..."
      ready=0
      for i in $(seq 1 20); do
        if ! kill -0 $SERVER_PID 2>/dev/null; then
          echo "✗ Server exited unexpectedly. Check for errors above."
          break
        fi
        if curl -s --max-time 1 http://localhost:8000/status >/dev/null 2>&1; then
          ready=1
          break
        fi
        sleep 0.5
      done
      if [ $ready -eq 1 ]; then
        echo "✓ Server restarted (PID $SERVER_PID)"
      else
        echo "✗ Server did not become ready. Commands: [r] restart  [q] quit"
      fi
      ;;
    q|Q|"")
      echo "Stopping server (PID $SERVER_PID)..."
      kill "$SERVER_PID" 2>/dev/null
      wait "$SERVER_PID" 2>/dev/null
      echo "✓ Server stopped."
      exit 0
      ;;
    *)
      echo "Commands: [r] restart  [q] quit"
      ;;
  esac
done
