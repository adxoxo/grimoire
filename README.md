# Grimoire

A local shared knowledge base served to multiple coding agents through one MCP gateway.
The spec lives in [ARCHITECTURE.md](ARCHITECTURE.md), the build order in
[BUILDPLAN.md](BUILDPLAN.md), and the operating rules in [CLAUDE.md](CLAUDE.md).

## Status

All build phases are implemented and verified.

- **Phase 0 — foundations**: SQLite + sqlite-vec store behind a repository layer (the only module that touches the engine), provider interface (Ollama + offline fake), verified backup/restore, re-embedding seam.
- **Phase 1 — documents + retrieval**: `ingest_document` (PDF/HTML/markdown to chunks + vectors) and `retrieve` (project-scoped 1-2 hop traversal with the entity supernode cap, then similarity x recency decay). [grimoire/service.py](grimoire/service.py)
- **Phase 2 — MCP gateway**: FastMCP server exposing `kb_retrieve / kb_write_memory / kb_get_project / kb_upsert_project / kb_ingest_document`, each wrapped in an OpenTelemetry span (duration, project, chunk counts). [grimoire/gateway.py](grimoire/gateway.py), [.mcp.json](.mcp.json)
- **Phase 3 — memory**: one-call distillation of sessions into chronicles ([grimoire/distill.py](grimoire/distill.py)); history backfill ([scripts/backfill.py](scripts/backfill.py)).
- **Phase 4 — capture**: one `/api/capture` endpoint for n8n, two payload types (conversation_capture, project_context).
- **Phase 5 — compaction**: merge overlapping old memories, archive originals, refresh project context, re-embed ([grimoire/compaction.py](grimoire/compaction.py), [scripts/compact.py](scripts/compact.py)).
- **Phase 6 — UI**: constellation home, project hub, review sanctum, tome reader ([frontend/](frontend/)).

Embeddings + the LLM run on Ollama on the Windows host (GPU), reached from WSL2; see below.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # adjust if needed
```

## Tests

```bash
.venv/bin/python -m pytest
```

Uses the deterministic offline `FakeProvider`, so no Ollama or network is required.

## Dashboard

The grimoire UI: a force-directed constellation home and project hub views, styled from
[design/the_arcane_grimoire/DESIGN.md](design/the_arcane_grimoire/DESIGN.md). It reads
real data from the store through the HTTP API.

```bash
# 1. seed some real data (offline, no Ollama needed)
.venv/bin/python scripts/seed.py

# 2. start the read API (port 8731; the Vite proxy points here)
.venv/bin/uvicorn grimoire.api:app --port 8731

# 3. start the dashboard (separate terminal)
npm --prefix frontend install   # first time only
npm --prefix frontend run dev   # http://localhost:5173
```

The API port is 8731 because :8000 was occupied on the dev machine; the Vite proxy in
`frontend/vite.config.ts` matches it. Change both together if you move it.

## MCP gateway (connect your agents)

The gateway is a stdio MCP server: the MCP client launches it on demand, it is not a
long-running daemon. Tools: `kb_retrieve`, `kb_write_memory`, `kb_get_project`,
`kb_upsert_project`, `kb_ingest_document`. Traces go to stderr.

```bash
.venv/bin/python -m grimoire.gateway      # run it directly (for debugging)
```

**Claude Code**: [.mcp.json](.mcp.json) at the repo root registers it automatically. Open
this project in Claude Code and approve the `grimoire` server when prompted (`/mcp` lists it).

**Claude Desktop (Windows, gateway in WSL2)**: Claude Desktop runs on Windows, so it must
launch the WSL2 process via `wsl.exe`. Edit
`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "grimoire": {
      "command": "wsl.exe",
      "args": ["--cd", "/home/adyu/apps/grimoire", "-e",
               ".venv/bin/python", "-m", "grimoire.gateway"]
    }
  }
}
```

Then fully restart Claude Desktop (quit from the tray, reopen). The gateway reads its
Ollama URL from `.env`, so no env is needed in the config. Verify with the hammer/tools
icon in the chat box.

## Deploy (Docker Compose)

Bundles the API (which serves the dashboard + the n8n `/api/capture` endpoint) and n8n.
The store is the SQLite file on the `./data` volume; Ollama stays on the host (GPU),
reached via `host.docker.internal`.

```bash
docker compose up --build      # dashboard at http://localhost:8731, n8n at :5678
```

The gateway is not a compose service (it is stdio, launched per-agent). Note: authored
against the BUILDPLAN spec but not built in this WSL2 env, which has no Docker; run it on
Docker Desktop or the Oracle Cloud VM.

## Capture (n8n) and maintenance

```bash
# n8n posts session payloads to one endpoint (served by the API):
#   POST /api/capture  {"type":"conversation_capture","project":"ROAR","turns":[...]}
#   POST /api/capture  {"type":"project_context","project":"ROAR","meta":{...},"context_patch":"..."}

.venv/bin/python scripts/backfill.py conversations.json   # one-time history backfill
.venv/bin/python scripts/compact.py                       # scheduled compaction + context refresh
.venv/bin/python scripts/compact.py --reembed             # also re-embed the whole store
```

## Backup and restore

```bash
.venv/bin/python -m grimoire.backup backup
.venv/bin/python -m grimoire.backup restore backups/grimoire-<timestamp>.db
```

Every backup is integrity-checked before it is trusted; restore is verified after.

## Embeddings + LLM (Ollama on Windows)

Ollama runs on the Windows host (GPU) and is reached from WSL2 over the network. On
Windows: install Ollama, set `OLLAMA_HOST=0.0.0.0:11434` (so WSL2 can connect), restart
it, then `ollama pull nomic-embed-text` and `ollama pull llama3.2`. Point the project at
it in `.env` via `GRIMOIRE_OLLAMA_URL=http://<windows-gateway-ip>:11434` (the gateway IP
is `ip route show default | awk '{print $3}'`; it can change on a WSL restart).

Verify: `.venv/bin/python scripts/verify_ollama.py`. To skip Ollama (tests/CI), set
`GRIMOIRE_PROVIDER=fake`.

## Layout

| Path | Role |
|---|---|
| [grimoire/store/](grimoire/store/) | Repository layer + schema. The only code that issues SQL. |
| [grimoire/providers/](grimoire/providers/) | Provider interface (ollama, fake) + factory. |
| [grimoire/backup.py](grimoire/backup.py) | Verified backup/restore routine + CLI. |
| [grimoire/reembed.py](grimoire/reembed.py) | Re-embedding routine (model-change seam). |
| [grimoire/config.py](grimoire/config.py) | Env-driven settings (`GRIMOIRE_` prefix). |
| [grimoire/service.py](grimoire/service.py) | Knowledge service: ingest + retrieve (the read/write paths). |
| [grimoire/distill.py](grimoire/distill.py) | Session distillation + capture. |
| [grimoire/compaction.py](grimoire/compaction.py) | Compaction + context consolidation. |
| [grimoire/gateway.py](grimoire/gateway.py) | FastMCP gateway (`kb_*` tools) + OpenTelemetry. |
| [grimoire/api.py](grimoire/api.py) | HTTP API: dashboard reads + n8n capture endpoint. |
| [scripts/](scripts/) | seed, backfill, compact, verify_ollama. |
| [frontend/](frontend/) | React + Vite + Tailwind dashboard (constellation, hub, sanctum, tome reader). |
| [tests/](tests/) | Phase 0 + Phase 1 acceptance suites. |
