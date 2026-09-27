#!/usr/bin/env bash
# One-command launch for the FastAPI backend.
# Installs dependencies if needed, starts the server, and opens the
# interactive API docs in your browser. Press Ctrl+C to stop.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8000}"
URL="http://127.0.0.1:${PORT}/docs"

cd "$REPO_ROOT"

# Install core dependencies if fastapi isn't already available. Deliberately
# NOT installing requirements-semantic.txt here — that one pulls PyTorch and
# needs a judgment call (see its header comment), so it stays manual.
if ! python3 -c "import fastapi" >/dev/null 2>&1; then
  echo "Installing backend dependencies..."
  pip3 install -r backend/requirements.txt
fi

open_when_ready() {
  # Poll for the server instead of a fixed sleep, so this works even if
  # startup is slow on a cold machine.
  for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      if command -v open >/dev/null 2>&1; then
        open "$URL" || echo "Open this in your browser: $URL"   # macOS
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" || echo "Open this in your browser: $URL"  # Linux
      else
        echo "Open this in your browser: $URL"
      fi
      return
    fi
    sleep 0.5
  done
  echo "Server didn't come up in time — open $URL manually once it does."
}

open_when_ready &

echo "Starting backend at $URL — press Ctrl+C to stop."
exec uvicorn backend.main:app --reload --port "$PORT"
