#!/usr/bin/env bash
# Run the Grimoire as ONE server: the API serves the built dashboard at :8731.
# Always rebuild the frontend on start so a code change can never serve a stale
# bundle. A stale dist against an updated job API is what broke the maintenance
# buttons (old frontend read the sync response shape the new API no longer returns).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d frontend/node_modules ]; then
  echo "installing dashboard deps..."
  npm --prefix frontend install
fi
echo "building dashboard..."
npm --prefix frontend run build

exec .venv/bin/uvicorn grimoire.api:app --host 0.0.0.0 --port 8731
