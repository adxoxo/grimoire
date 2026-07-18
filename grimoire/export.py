"""One-way Obsidian vault export (Phase 6).

Renders every node in the store to a markdown file with YAML frontmatter and
wikilinks for its edges, so the grimoire can be browsed read-only in Obsidian.
This is a snapshot export, not a sync: re-running wipes and rewrites the output
directory (guarded by a marker file so it never clobbers an arbitrary folder).

    from grimoire.export import export_store
    export_store(repo, "path/to/vault")
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

MARKER_NAME = ".grimoire-export"

_REL_HEADINGS = (
    ("belongs_to", "Belongs to"),
    ("references", "References"),
    ("mentions", "Mentions"),
    ("derived_from", "Derived from"),
)


def slugify(title: str, max_len: int = 80) -> str:
    """Lowercase, alnum-and-hyphens slug of a title. Never empty."""
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    s = s[:max_len].strip("-")
    return s or "untitled"


def _frontmatter(node: dict[str, Any]) -> str:
    lines = ["---", f"type: {json.dumps(node['type'])}"]
    community = node.get("community_id")
    if community is not None:
        lines.append(f"community: {json.dumps(community)}")
    lines.append(f"created: {json.dumps(node.get('created_at'))}")
    tags = (node.get("meta") or {}).get("tags")
    if tags:
        lines.append(f"tags: {json.dumps(tags)}")
    lines.append(f"grimoire_id: {json.dumps(node['id'])}")
    lines.append("---")
    return "\n".join(lines)


def _content_body(node: dict[str, Any], repo: Any) -> str:
    summary = node.get("context_summary")
    if summary:
        return summary.strip()
    if node["type"] == "document":
        texts = repo.node_chunk_texts(node["id"])
        if texts:
            return "\n\n".join(texts)
    return ""


def _edges_section(
    node_id: str,
    slugs: dict[str, str],
    nodes_by_id: dict[str, dict[str, Any]],
    outgoing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> str:
    by_rel: dict[str, list[str]] = {}
    for e in outgoing:
        by_rel.setdefault(e["rel"], []).append(e["dst"])

    parts: list[str] = []
    for rel, heading in _REL_HEADINGS:
        dsts = by_rel.get(rel)
        if not dsts:
            continue
        parts.append(f"## {heading}")
        for dst in dsts:
            target = nodes_by_id[dst]
            parts.append(f"- [[{slugs[dst]}|{target['title']}]]")
        parts.append("")

    if incoming:
        parts.append("## Linked from")
        for e in incoming:
            src = nodes_by_id[e["src"]]
            parts.append(f"- [[{slugs[e['src']]}|{src['title']}]]")
        parts.append("")

    return "\n".join(parts).rstrip("\n")


def _render_node(
    node: dict[str, Any],
    repo: Any,
    slugs: dict[str, str],
    nodes_by_id: dict[str, dict[str, Any]],
    outgoing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> str:
    sections = [_frontmatter(node)]
    body = _content_body(node, repo)
    if body:
        sections.append(body)
    edges = _edges_section(node["id"], slugs, nodes_by_id, outgoing, incoming)
    if edges:
        sections.append(edges)
    return "\n\n".join(sections).rstrip("\n") + "\n"


def _assign_slugs(ordered_nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Slugs unique vault-wide (Obsidian resolves wikilinks by filename, not folder)."""
    used: set[str] = set()
    slugs: dict[str, str] = {}
    for node in ordered_nodes:
        base = slugify(node["title"])
        slug = base
        i = 2
        while slug in used:
            slug = f"{base}-{i}"
            i += 1
        used.add(slug)
        slugs[node["id"]] = slug
    return slugs


def _prepare_output_dir(output_dir: Path) -> None:
    marker = output_dir / MARKER_NAME
    if output_dir.exists():
        contents = list(output_dir.iterdir())
        if contents and not marker.exists():
            raise ValueError(
                f"refusing to export into a non-empty directory without a "
                f"{MARKER_NAME} marker: {output_dir}"
            )
        for item in contents:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    else:
        output_dir.mkdir(parents=True)


def export_store(repo: Any, output_dir: str | Path) -> dict[str, Any]:
    """Export the whole store to a flat Obsidian vault under output_dir.

    One .md file per node at <output_dir>/<node_type>/<slug>.md, with YAML
    frontmatter and edges rendered as wikilinks. Idempotent: re-exporting into
    the same directory wipes and rewrites it (guarded by a marker file so an
    arbitrary non-empty directory is never destroyed).

    Returns {"nodes": N, "edges": M, "output_dir": str}.
    """
    output_dir = Path(output_dir)
    _prepare_output_dir(output_dir)

    node_ids = [n["id"] for n in repo.list_nodes()]
    nodes_by_id: dict[str, dict[str, Any]] = {}
    for node_id in node_ids:
        full = repo.get_node(node_id)
        if full is not None:
            nodes_by_id[node_id] = full

    ordered = sorted(nodes_by_id.values(), key=lambda n: (n.get("created_at") or "", n["id"]))
    slugs = _assign_slugs(ordered)

    outgoing_by_node: dict[str, list[dict[str, Any]]] = {}
    incoming_by_node: dict[str, list[dict[str, Any]]] = {}
    edges = repo.list_edges()
    for e in edges:
        if e["src"] not in nodes_by_id or e["dst"] not in nodes_by_id:
            continue
        outgoing_by_node.setdefault(e["src"], []).append(e)
        incoming_by_node.setdefault(e["dst"], []).append(e)

    for node in ordered:
        type_dir = output_dir / node["type"]
        type_dir.mkdir(parents=True, exist_ok=True)
        text = _render_node(
            node,
            repo,
            slugs,
            nodes_by_id,
            outgoing_by_node.get(node["id"], []),
            incoming_by_node.get(node["id"], []),
        )
        (type_dir / f"{slugs[node['id']]}.md").write_text(text, encoding="utf-8")

    (output_dir / MARKER_NAME).write_text(
        "grimoire export marker - do not delete; re-export wipes this directory\n",
        encoding="utf-8",
    )

    return {"nodes": len(ordered), "edges": len(edges), "output_dir": str(output_dir)}
