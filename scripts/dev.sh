#!/usr/bin/env bash
# Dev mode with hot reload: API on :8731 + Vite dev server on :5173 (proxies /api).
# Browse http://localhost:5173. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/uvicorn grimoire.api:app --port 8731 --reload &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

npm --prefix frontend run dev
