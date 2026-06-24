"""Scribe-from-text: turn a free-form sentence into one knowledge node.

The dashboard's quick-capture lane. The LLM (provider chain: Groq first, Ollama
fallback) classifies the note into a node type, gives it a title, and picks the
quest line it belongs to; this module then creates it through the repository, the
same intent-methods the MCP gateway uses. Knowledge nodes are embedded so they are
retrievable; if the embedder is unreachable the node is still saved, just unindexed.
"""

from __future__ import annotations

import json

from grimoire.service import KnowledgeService

SCRIBE_SYSTEM = """You are the Grimoire scribe. Turn the user's note into ONE knowledge \
node, returned as a single JSON object. Fields:
- "type": "memory" (a distilled note, fact, idea, or insight — the default), \
"entity" (a reusable API, tool, person, place, or concept worth tracking), \
"document" (reference material / longer text), or "project" (a new quest line / initiative).
- "title": a short title, <= 80 chars, no quotes.
- "content": the note itself, lightly cleaned up and self-contained. For a project this \
is its context summary.
- "project": the quest line this belongs to. Pick the closest match from the existing \
projects when one fits; otherwise propose a short new project name. Omit only when type is "project".
Existing projects: {projects}
Return ONLY the JSON object, nothing else."""

NODE_TYPES = ("memory", "entity", "document", "project")
DEFAULT_PROJECT = "Inbox"


def _parse_json(raw: str) -> dict:
    """Best-effort JSON extraction (strips code fences and surrounding prose)."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw[:4].lower() == "json":
            raw = raw[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {raw[:200]!r}")
    return json.loads(raw[start : end + 1])


def _embed(svc: KnowledgeService, text: str) -> list[float] | None:
    try:
        return svc.provider.embed(text)
    except Exception:  # noqa: BLE001 - embedder offline: save the node unindexed, do not fail
        return None


def scribe_from_text(svc: KnowledgeService, message: str) -> dict:
    """Classify a note and create the corresponding node. Returns the created node."""
    projects = [n["title"] for n in svc.repo.list_nodes(type="project")]
    system = SCRIBE_SYSTEM.format(projects=", ".join(projects) if projects else "(none yet)")
    data = _parse_json(svc.provider.complete(message, system=system, json_mode=True))

    ntype = data.get("type") if data.get("type") in NODE_TYPES else "memory"
    title = (str(data.get("title") or message)[:80]).strip() or "Untitled"
    content = str(data.get("content") or message).strip()
    entities = data.get("entities") if isinstance(data.get("entities"), list) else []

    # A new quest line.
    if ntype == "project":
        pid = svc.repo.upsert_project(title, context_patch=content)
        return {"id": pid, "type": "project", "title": title, "project": title}

    # Everything else links to a quest line (an unlinked node is a bug).
    project = str(data.get("project") or DEFAULT_PROJECT).strip() or DEFAULT_PROJECT
    proj = svc.repo.get_project(project)
    pid = proj["id"] if proj else svc.repo.upsert_project(project)

    if ntype == "memory":
        node_id = svc.repo.write_memory(
            project=project, summary=content, title=title,
            entities=entities, summary_embedding=_embed(svc, content),
        )
        return {"id": node_id, "type": "memory", "title": title, "project": project}

    # entity or document
    node_id = svc.repo.add_node(ntype, title, status="unreviewed", context_summary=content)
    svc.repo.link_nodes(node_id, pid, "belongs_to")
    if ntype == "document":
        emb = _embed(svc, content)
        if emb is not None:
            svc.repo.add_chunk(node_id, 0, content, emb)
    return {"id": node_id, "type": ntype, "title": title, "project": project}
