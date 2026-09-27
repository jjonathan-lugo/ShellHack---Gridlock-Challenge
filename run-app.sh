#!/usr/bin/env bash
# One-command launch for the static demo (app/index.html).
# Starts the local server and opens the page in your browser.
# Press Ctrl+C to stop the server when you're done.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8000}"
URL="http://localhost:${PORT}/app/index.html"

cd "$REPO_ROOT"

# Cache 10 years of weather history for the weather-risk panel, in the
# background so the app opens right away. Open-Meteo's free tier only allows
# about two of these downloads a minute, so it takes a few minutes the first
# time; it resumes where it left off and is instant once complete. Meanwhile
# the page fetches whichever pair you click live. Log: data/cache/weather_fetch.log
mkdir -p data/cache
python3 -m backend.weather.fetch > data/cache/weather_fetch.log 2>&1 &
echo "Updating the weather-history cache in the background (log: data/cache/weather_fetch.log)"

# Start the server in the background so we can open the browser after it's up.
python3 -m http.server "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null' EXIT

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
