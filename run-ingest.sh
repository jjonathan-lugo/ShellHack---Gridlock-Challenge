#!/usr/bin/env bash
# One command for the automatic-ingest add-on:
#   utility PDFs -> project tables -> OpenStreetMap coordinates -> overlaps (+ weather)
#
#   ./run-ingest.sh              build data/processed/auto/ (needs internet the first time)
#   ./run-ingest.sh --offline    rebuild from cached lookups only
#   ./run-ingest.sh --watch      keep running; rebuild whenever the spreadsheet or PDFs change
#
# Then ./run-app.sh and pick "Data: Auto from PDFs" in the header.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

if [ "${1:-}" = "--watch" ]; then
  shift
  exec python3 -m backend.ingest.watch "$@"
fi

if ! python3 -c "import pdfplumber, pypdf" >/dev/null 2>&1; then
  echo "Installing PDF ingest dependencies (pdfplumber, pypdf)..."
  pip3 install -r backend/requirements-ingest.txt
fi

python3 -m backend.ingest.pipeline --weather "$@"

echo ""
echo "Done. Start the app with ./run-app.sh and pick \"Data: Auto from PDFs\" in the header."
