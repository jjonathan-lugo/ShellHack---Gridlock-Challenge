#!/usr/bin/env bash
# One-command launch for the static demo (app/index.html).
# Starts the local server and opens the page in your browser.
# Press Ctrl+C to stop the server when you're done.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8000}"
API_PORT=$((PORT + 1))
URL="http://localhost:${PORT}/app/index.html"

cd "$REPO_ROOT"

# A previous ./run-app.sh (e.g. in another terminal tab) still holding the
# ports is the usual cause of "Address already in use" - say so plainly.
port_busy() {
  ! python3 - "$1" >/dev/null 2>&1 <<'PY'
import socket, sys
port = int(sys.argv[1])
for host in ("127.0.0.1", ""):  # a server may hold either the loopback or the wildcard address
    s = socket.socket()
    s.bind((host, port))
    s.close()
PY
}
for p in "$PORT" "$API_PORT"; do
  if port_busy "$p"; then
    echo "Port $p is already in use - probably an earlier ./run-app.sh still running."
    echo "Stop it with Ctrl+C in that terminal, or run:  lsof -ti tcp:$PORT,$API_PORT | xargs kill"
    echo "then run ./run-app.sh again. (Or use other ports: PORT=8100 ./run-app.sh)"
    exit 1
  fi
done

# Optional: put HF_TOKEN=hf_... in a .env file here (git-ignored) so the AI
# recommendation panel uses the Hugging Face model without exporting it each time.
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# Cache 10 years of weather history for the weather-risk panel, in the
# background so the app opens right away. Open-Meteo's free tier only allows
# about two of these downloads a minute, so it takes a few minutes the first
# time; it resumes where it left off and is instant once complete. Meanwhile
# the page fetches whichever pair you click live. Log: data/cache/weather_fetch.log
mkdir -p data/cache
python3 -m backend.weather.fetch > data/cache/weather_fetch.log 2>&1 &
echo "Updating the weather-history cache in the background (log: data/cache/weather_fetch.log)"

# The backend powers the AI recommendation panel (Hugging Face draft + the
# hallucination guard). The page falls back to its offline template if it
# isn't running, so the demo works either way. Log: data/cache/backend.log
BACKEND_PID=""
if python3 -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  python3 -m uvicorn backend.main:app --port "$API_PORT" > data/cache/backend.log 2>&1 &
  BACKEND_PID=$!
  if [ -n "${HF_TOKEN:-}" ]; then
    echo "AI recommendations: backend on port ${API_PORT}, using Hugging Face (HF_TOKEN is set)"
  else
    echo "AI recommendations: backend on port ${API_PORT}, but HF_TOKEN isn't set - the panel shows the template."
    echo "  (export HF_TOKEN=hf_... or put it in a .env file here, then restart)"
  fi
else
  echo "AI recommendations: backend not installed, the panel shows the offline template."
  echo "  (pip3 install -r backend/requirements.txt, then restart)"
fi

# Start the server in the background so we can open the browser after it's up.
python3 -m http.server "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" $BACKEND_PID 2>/dev/null' EXIT

sleep 1

if command -v open >/dev/null 2>&1; then
  open "$URL" || echo "Open this in your browser: $URL"   # macOS
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" || echo "Open this in your browser: $URL"  # Linux
else
  echo "Open this in your browser: $URL"
fi

echo "Serving at $URL — press Ctrl+C to stop."
wait "$SERVER_PID"
