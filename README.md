# Grimoire

A local shared knowledge base served to multiple coding agents through one MCP gateway.
The spec lives in [ARCHITECTURE.md](ARCHITECTURE.md), the build order in
[BUILDPLAN.md](BUILDPLAN.md), and the operating rules in [CLAUDE.md](CLAUDE.md).

## Status

Phase 0 (foundations) is complete and tested:

- Store: SQLite + sqlite-vec (768-dim), decision recorded in ARCHITECTURE.md.
- Repository layer: the only module that touches the engine ([grimoire/store/](grimoire/store/)).
- Provider interface: embeddings + completion behind one seam, Ollama and an offline fake ([grimoire/providers/](grimoire/providers/)).
- Backup/restore: verified by re-opening the backup, never assumed ([grimoire/backup.py](grimoire/backup.py)).
- Re-embedding routine: the seam for changing models later ([grimoire/reembed.py](grimoire/reembed.py)).
- Acceptance suite green ([tests/test_phase0.py](tests/test_phase0.py)).

Outstanding: the live Ollama embed round-trip is gated on installing Ollama (below). The
suite runs without it via the offline provider.

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

## Backup and restore

```bash
.venv/bin/python -m grimoire.backup backup
.venv/bin/python -m grimoire.backup restore backups/grimoire-<timestamp>.db
```

Every backup is integrity-checked before it is trusted; restore is verified after.

## Embeddings (Ollama)

The default provider is local Ollama at 768 dimensions. This machine has no Docker and
no passwordless sudo, so install Ollama as a user binary (no root). Exact paths inside
the archive may vary, so confirm the binary location after extracting:

```bash
curl -L https://ollama.com/download/ollama-linux-amd64.tgz -o /tmp/ollama.tgz
mkdir -p ~/.local && tar -xzf /tmp/ollama.tgz -C ~/.local
~/.local/bin/ollama serve &
~/.local/bin/ollama pull nomic-embed-text
.venv/bin/python scripts/verify_ollama.py
```

To skip Ollama entirely (tests, CI), set `GRIMOIRE_PROVIDER=fake`.

## Layout

| Path | Role |
|---|---|
| [grimoire/store/](grimoire/store/) | Repository layer + schema. The only code that issues SQL. |
| [grimoire/providers/](grimoire/providers/) | Provider interface (ollama, fake) + factory. |
| [grimoire/backup.py](grimoire/backup.py) | Verified backup/restore routine + CLI. |
| [grimoire/reembed.py](grimoire/reembed.py) | Re-embedding routine (model-change seam). |
| [grimoire/config.py](grimoire/config.py) | Env-driven settings (`GRIMOIRE_` prefix). |
| [tests/](tests/) | Phase 0 acceptance. |
