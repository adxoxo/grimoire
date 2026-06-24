#!/usr/bin/env bash
# Run the MCP gateway as an HTTP daemon for remote agents (Gemini, Codex, etc.),
# fronted by your Cloudflare tunnel. Binds to localhost:8730 so only the local
# tunnel reaches it. The bearer token + provider come from .env.
#
# This does NOT affect the local stdio gateway that Claude Desktop launches via
# .mcp.json: transport=http is set here inline, not in .env.
#
#   bash scripts/serve-mcp.sh
# Then point your tunnel:  mcp.aquryu.space -> http://localhost:8730
# Agents connect to:       https://mcp.aquryu.space/mcp   (Authorization: Bearer <token>)
set -euo pipefail
cd "$(dirname "$0")/.."

exec env GRIMOIRE_MCP_TRANSPORT=http GRIMOIRE_MCP_HTTP_HOST=127.0.0.1 GRIMOIRE_MCP_HTTP_PORT=8730 \
  .venv/bin/python -m grimoire.gateway
