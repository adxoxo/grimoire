#!/usr/bin/env python3
"""SessionStart bootstrap: one fetch of a project's Grimoire context, printed as a
compact block so a fresh session opens already knowing the project.

Stdlib only (urllib) so this runs without the venv. Any failure (API down, project
not found, slow, junk JSON) degrades to total silence and exit 0 -- this must never
add noise or delay to session start.

    python3 scripts/session_context.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_BASE = os.environ.get("GRIMOIRE_API_BASE", "http://127.0.0.1:8731")
# Up to three sequential calls (direct lookup, graph fallback, resolved lookup);
# each gets its own slice so the worst case (all three hang) still lands at 3s.
TIMEOUT_SECONDS = 1.0
CODEBASE_PREFIX = "Codebase: "


def _project_name() -> str:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.basename(os.path.normpath(project_dir))


def _get_json(url: str) -> dict | None:
    """GET decoded JSON, or None on a 404 (a non-404 HTTP error propagates)."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _fetch(name: str) -> dict | None:
    return _get_json(f"{API_BASE}/api/projects/{urllib.parse.quote(name)}")


def _fetch_case_insensitive(name: str) -> dict | None:
    """The stored project title may not match the directory basename's case (e.g.
    "grimoire" on disk vs "Grimoire" in the store, and the API lookup is
    case-sensitive). Pull the graph, match the basename case-insensitively against
    project node titles, and re-fetch by the exact stored title on a unique match."""
    graph = _get_json(f"{API_BASE}/api/graph")
    if not graph or not isinstance(graph, dict):
        return None
    lname = name.lower()
    matches = [
        n["title"] for n in graph.get("nodes", [])
        if n.get("type") == "project" and (n.get("title") or "").lower() == lname
    ]
    if len(matches) != 1:
        return None
    return _fetch(matches[0])


def _render(project: dict) -> str:
    lines: list[str] = []
    title = project["title"]
    status = project.get("status") or "unknown"
    lines.append(f"# Grimoire: {title} ({status})")
    summary = (project.get("context_summary") or "").strip()
    if summary:
        lines.append(summary)

    linked = project.get("linked") or []
    memories = [n["title"] for n in linked if n.get("type") == "memory"][:5]
    if memories:
        lines.append("")
        lines.append("Recent memory:")
        for t in memories:
            lines.append(f"- {t}")

    codebase_docs = [n["title"] for n in linked if n.get("type") == "document"
                      and (n.get("title") or "").startswith(CODEBASE_PREFIX)][:3]
    if codebase_docs:
        lines.append("")
        lines.append("Codebase docs:")
        for t in codebase_docs:
            lines.append(f"- {t}")

    lines.append("")
    lines.append("Full knowledge base available via kb_retrieve(query, project) for anything deeper.")
    return "\n".join(lines)


def main() -> None:
    try:
        name = _project_name()
        project = _fetch(name)
        if project is None:
            project = _fetch_case_insensitive(name)
        if not project or not isinstance(project, dict) or "title" not in project:
            return
        print(_render(project))
    except Exception:  # noqa: BLE001 - any failure degrades to silence, never noise
        return


if __name__ == "__main__":
    main()
