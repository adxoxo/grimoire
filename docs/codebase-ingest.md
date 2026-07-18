# Codebase ingest

Grimoire stores the map, not the territory. This ingests a distilled codebase map
(architecture report + module wiki pages) as tomes linked to a project, never raw
source files.

## Ingest once

```
.venv/bin/python scripts/ingest_codebase.py <repo_path> <project_name>
```

This needs an extraction engine to produce `GRAPH_REPORT.md` (+ optional
`wiki/*.md` pages):

- If `graphify` is installed and on PATH, it runs automatically.
- Otherwise pass `--graphify-out <dir>` pointing at an already-generated output
  directory (run graphify yourself, or any tool that produces the same shape).

Options:

- `--db PATH` overrides the store path (for testing, without touching the live
  database).
- `GRIMOIRE_PROVIDER` selects the embedding provider (`ollama` default, `fake`
  for offline runs).

Each page is ingested as a tome titled `Codebase: <page name>`, with provenance
(`repo` path + git commit) embedded as the first line of the markdown. Re-running
replaces the project's prior codebase docs, so re-ingestion never duplicates.
State (last commit ingested per repo) is tracked in `data/codebase_ingest.json`.

## Auto re-ingest on commit

```
bash scripts/install_git_hooks.sh
```

Installs `deploy/hooks/post-commit` into `.git/hooks/post-commit`. After each
commit it re-runs the ingest in the background, skipping silently when:

- `graphify` is not on PATH (no way to auto-extract).
- The repo was already ingested at this exact commit.
- The last ingest ran less than 10 minutes ago.

The hook never fails a commit; every path is wrapped to always exit 0. Logs go
to `data/logs/codebase_ingest.log`.

## Session bootstrap

```
python3 scripts/install_session_hook.py
```

Adds a SessionStart hook (in `~/.claude/settings.json`) that runs
`scripts/session_context.py` at the start of every session. It fetches the
current project's Grimoire context in one call (title, status, summary, recent
memory, codebase docs) and prints a compact block, so a fresh session opens
already knowing the project.

Stdlib only (no venv needed), a hard 3 second budget, and silent on any failure
(API down, project unknown, slow, bad JSON) -- it never adds noise or delay to
session start.
