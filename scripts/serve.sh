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
# Rebuild every start so a code change never serves a stale bundle. But a frontend
# build failure must not black out the backend API + MCP that agents depend on: fall
# back to the last-good dist and still boot. Only hard-fail if there is no dist at all.
if ! npm --prefix frontend run build; then
  echo "dashboard build FAILED; serving the previous dist" >&2
  [ -d frontend/dist ] || { echo "no previous dist to serve; aborting" >&2; exit 1; }
fi

exec .venv/bin/uvicorn grimoire.api:app --host 0.0.0.0 --port 8731
