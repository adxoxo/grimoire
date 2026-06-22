"""Compaction: the scheduled store-maintenance job that keeps retrieval quality and
storage flat. It merges old, topic-overlapping memory fragments per project into one
consolidated chronicle (originals archived, raw kept), and refreshes each project's
living context summary. Load-bearing, not polish.
"""

from __future__ import annotations

from datetime import datetime, timezone

from grimoire.service import KnowledgeService

DEFAULT_OLDER_THAN_DAYS = 30
# Cosine distance below this means two summaries are "on overlapping topics".
DEFAULT_DISTANCE_THRESHOLD = 0.25
RECENT_FOR_CONTEXT = 8

_MERGE_SYSTEM = "You merge overlapping session notes into one summary without losing any decision or open question."
_CONTEXT_SYSTEM = "You maintain a project's living context summary."


def _age_days(created_at: str, now: datetime) -> float:
    try:
        ts = datetime.fromisoformat(created_at)
    except ValueError:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 86400.0


def compact_project(
    service: KnowledgeService,
    project: str,
    older_than_days: int = DEFAULT_OLDER_THAN_DAYS,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> dict:
    """Merge clusters of old, overlapping memories in one project. Returns stats."""
    repo, provider = service.repo, service.provider
    proj = repo.get_project(project)
    if proj is None:
        return {"project": project, "clusters_merged": 0, "originals_archived": 0}

    now = datetime.now(timezone.utc)
    old = [
        m
        for m in repo.project_memories(proj["id"])
        if m["chunk_id"] and _age_days(m["created_at"], now) >= older_than_days
    ]

    # Greedy clustering by pairwise cosine distance.
    used: set[str] = set()
    clusters: list[list[dict]] = []
    for i, seed in enumerate(old):
        if seed["id"] in used:
            continue
        cluster = [seed]
        used.add(seed["id"])
        for other in old[i + 1:]:
            if other["id"] in used:
                continue
            dist = repo.vector_distance(seed["chunk_id"], other["chunk_id"])
            if dist is not None and dist <= distance_threshold:
                cluster.append(other)
                used.add(other["id"])
        if len(cluster) >= 2:
            clusters.append(cluster)

    merged = 0
    archived = 0
    for cluster in clusters:
        bullets = "\n\n".join(f"- {m['context_summary']}" for m in cluster if m["context_summary"])
        consolidated = provider.complete(
            "Consolidate these related session summaries into ONE concise summary "
            "(3 to 5 sentences), preserving key decisions and open questions. "
            "Output only the summary:\n\n" + bullets,
            system=_MERGE_SYSTEM,
        ).strip()
        new_id = repo.write_memory(
            project=project,
            summary=consolidated,
            summary_embedding=provider.embed(consolidated),
            title=f"Consolidated: {cluster[0]['title'][:50]}",
        )
        for m in cluster:
            repo.link_nodes(new_id, m["id"], "derived_from")
            repo.archive_node(m["id"])
            archived += 1
        merged += 1

    return {"project": project, "clusters_merged": merged, "originals_archived": archived}


def consolidate_context(
    service: KnowledgeService, project: str, max_recent: int = RECENT_FOR_CONTEXT
) -> str | None:
    """Refresh a project's living context summary from its most recent active memories."""
    repo, provider = service.repo, service.provider
    proj = repo.get_project(project)
    if proj is None:
        return None
    memories = repo.project_memories(proj["id"])
    recent = sorted(memories, key=lambda m: m["created_at"], reverse=True)[:max_recent]
    bullets = "\n\n".join(f"- {m['context_summary']}" for m in recent if m["context_summary"])
    if not bullets:
        return None
    summary = provider.complete(
        "Write a 3 to 5 sentence living context summary of this project from its recent "
        "session notes. Output only the summary:\n\n" + bullets,
        system=_CONTEXT_SYSTEM,
    ).strip()
    repo.upsert_project(project, context_patch=summary)
    return summary
