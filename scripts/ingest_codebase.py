#!/usr/bin/env python3
"""Ingest a distilled codebase map into the Grimoire, linked to a project.

Grimoire stores the map, not the territory: this never embeds raw source files.
It ingests the OUTPUT of a graph-extraction pass (a GRAPH_REPORT.md + wiki pages
describing modules, boundaries, and call graphs) as ordinary tomes.

Extraction engine:
  - If a `graphify` executable is on PATH, its extract command is run against
    repo_path to produce the report + wiki pages.
  - Otherwise you must pass --graphify-out pointing at an existing output
    directory (already-generated GRAPH_REPORT.md + wiki/*.md). This lets you run
    graphify yourself, or point at any other tool that produces the same shape.
  - If neither is available, this exits with an actionable error explaining both
    options.

Re-running archives the project's prior codebase docs (matched by structured
provenance in their meta, so re-ingestion never duplicates and never loses the
prior version -- it's superseded, not deleted).

Usage:
    .venv/bin/python scripts/ingest_codebase.py <repo_path> <project_name> [--graphify-out DIR] [--db PATH]

GRIMOIRE_PROVIDER selects the embedding provider (default from grimoire.config,
usually 'ollama'; set to 'fake' for offline/test runs). --db overrides the store
path (for testing without touching the live database).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from grimoire.config import settings
from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository

TITLE_PREFIX = "Codebase: "

NO_ENGINE_MSG = """\
error: no codebase-map extraction available.

Option 1: install `graphify` so it is on PATH, then re-run this command as-is.
Option 2: run graphify (or an equivalent tool) yourself to produce
          GRAPH_REPORT.md (+ optional wiki/*.md pages) in a directory, then
          re-run with --graphify-out <that directory>.
"""


def _git_head(repo_path: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - not a git repo, or git unavailable
        return "unknown"


def _resolve_output_dir(repo_path: Path, graphify_out: str | None) -> Path:
    """Where the extraction output (GRAPH_REPORT.md + wiki pages) lives."""
    if graphify_out:
        out_dir = Path(graphify_out)
        if not out_dir.is_dir():
            print(f"error: --graphify-out {out_dir} does not exist or is not a directory", file=sys.stderr)
            raise SystemExit(2)
        return out_dir
    graphify_bin = shutil.which("graphify")
    if graphify_bin is None:
        print(NO_ENGINE_MSG, file=sys.stderr)
        raise SystemExit(2)
    out_dir = Path(tempfile.mkdtemp(prefix="graphify_out_"))
    subprocess.run([graphify_bin, "extract", str(repo_path), "--out", str(out_dir)], check=True)
    return out_dir


def _collect_docs(out_dir: Path) -> list[Path]:
    """GRAPH_REPORT.md (if present) followed by wiki pages, in a stable order."""
    docs: list[Path] = []
    report = out_dir / "GRAPH_REPORT.md"
    if report.exists():
        docs.append(report)
    wiki_dir = out_dir / "wiki"
    if wiki_dir.is_dir():
        docs.extend(sorted(wiki_dir.glob("*.md")))
    else:
        docs.extend(sorted(p for p in out_dir.glob("*.md") if p.name != "GRAPH_REPORT.md"))
    if not docs:
        print(f"error: no GRAPH_REPORT.md or wiki pages found in {out_dir}", file=sys.stderr)
        raise SystemExit(2)
    return docs


def _is_codebase_doc(node: dict) -> bool:
    """A prior codebase-map ingest is identified by its meta; fall back to the title
    prefix as a secondary check for docs ingested before this fix existed."""
    if (node.get("meta") or {}).get("source") == "codebase":
        return True
    return (node.get("title") or "").startswith(TITLE_PREFIX)


def _archive_prior_codebase_docs(repo: Repository, project_name: str) -> int:
    """Archive (supersede, don't hard-delete) every existing codebase-map document
    linked to this project. Skips docs already archived so re-ingest doesn't keep
    re-archiving an ever-growing list."""
    proj = repo.get_project(project_name)
    if proj is None:
        return 0
    archived = 0
    for linked in proj["linked"]:
        if linked["type"] != "document" or linked.get("status") == "archived":
            continue
        node = repo.get_node(linked["id"])
        if node is None or node["type"] != "document" or node.get("status") == "archived":
            continue  # confirm before archiving; a title match alone is not enough
        if not _is_codebase_doc(node):
            continue
        repo.archive_node(linked["id"])
        archived += 1
    return archived


def _ingest_with_provenance(
    svc: KnowledgeService, doc_path: Path, project_name: str, repo_path: Path, commit: str
) -> dict:
    title = f"{TITLE_PREFIX}{doc_path.stem}"
    body = doc_path.read_text(encoding="utf-8", errors="replace")
    provenance = f"<!-- codebase-ingest repo={repo_path} commit={commit} -->\n"
    fd, tmp_name = tempfile.mkstemp(suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(provenance + body)
        return svc.ingest_document(
            tmp_name, project=project_name, title=title,
            extra_meta={"source": "codebase", "repo": str(repo_path), "commit": commit},
        )
    finally:
        os.unlink(tmp_name)


def _write_state(state_path: Path, repo_path: Path, project_name: str, commit: str) -> None:
    state: dict = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            state = {}
    state[str(repo_path)] = {
        "project": project_name,
        "commit": commit,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_path")
    parser.add_argument("project_name")
    parser.add_argument("--graphify-out", dest="graphify_out", default=None,
                        help="existing directory with GRAPH_REPORT.md (+ wiki pages), skips running graphify")
    parser.add_argument("--db", dest="db", default=None, help="override the store path (for testing)")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.is_dir():
        print(f"error: repo path not found: {repo_path}", file=sys.stderr)
        raise SystemExit(2)

    db_path = Path(args.db) if args.db else Path(settings.db_path)
    out_dir = _resolve_output_dir(repo_path, args.graphify_out)
    docs = _collect_docs(out_dir)
    commit = _git_head(repo_path)

    provider = get_provider()
    store_repo = Repository(db_path)
    try:
        archived = _archive_prior_codebase_docs(store_repo, args.project_name)
        if archived:
            print(f"archived {archived} prior codebase doc(s) for {args.project_name!r}")

        svc = KnowledgeService(store_repo, provider)
        for doc_path in docs:
            result = _ingest_with_provenance(svc, doc_path, args.project_name, repo_path, commit)
            print(f"ingested {result['title']} ({result['chunks']} chunks)")

        state_path = db_path.parent / "codebase_ingest.json"
        _write_state(state_path, repo_path, args.project_name, commit)
        print(f"state written to {state_path}")
    finally:
        store_repo.close()


if __name__ == "__main__":
    main()
