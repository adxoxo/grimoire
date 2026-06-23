#!/usr/bin/env bash
# Run the Grimoire as ONE server: the API serves the built dashboard at :8731.
# Build the frontend first if it has not been built.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d frontend/dist ]; then
  echo "building dashboard..."
  npm --prefix frontend install
  npm --prefix frontend run build
fi

exec .venv/bin/uvicorn grimoire.api:app --host 0.0.0.0 --port 8731
