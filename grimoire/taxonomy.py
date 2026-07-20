"""Taxonomy bootstrap: turn the existing graph into domains and indexes (V2 §7).

Do not hand-file the graph. Bootstrap it from Louvain communities:

  1. `kb_recluster` computes communities (run it first if the graph has grown).
  2. `propose_taxonomy` samples each community's member titles/types so Claude can
     name it and decide domain-vs-index. (This step, plus the human review, happens
     in conversation, not here.)
  3. Adam approves the candidate taxonomy in one pass.
  4/5. `apply_taxonomy` creates the confirmed domains/indexes, backfills
     domain_id/index_id for every community member, and generates + embeds a routing
     summary for each new scope.

Nodes in rejected communities, plus singletons, stay unclassified and land in the
inbox for manual triage. Existing edges are never touched.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from grimoire.cluster import recluster
from grimoire.service import KnowledgeService
from grimoire.store import Repository


def propose_taxonomy(repo: Repository, sample_titles: int = 10) -> dict[str, Any]:
    """Sample each community for a naming pass. Returns communities largest-first, each
    with a size, a sample of member titles, and a type breakdown. Steps 2-3 (naming and
    review) run in conversation from this payload; nothing is written here.

    Reclusters first so proposals always reflect a freshly clustered graph (community ids
    are consumed only here and by the Galaxy viz, so clustering rides on bootstrap now)."""
    recluster(repo)
    nodes = [n for n in repo.list_nodes() if n.get("node_kind", "node") == "node"]
    by_community: dict[int, list[dict]] = defaultdict(list)
    unclustered = 0
    for n in nodes:
        cid = n.get("community_id")
        if cid is None:
            unclustered += 1
        else:
            by_community[cid].append(n)
    communities = [
        {
            "community_id": cid,
            "size": len(members),
            "types": dict(Counter(m["type"] for m in members)),
            "sample_titles": [m["title"] for m in members[:sample_titles]],
        }
        for cid, members in sorted(by_community.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    return {"communities": communities, "unclustered": unclustered, "total_nodes": len(nodes)}


def apply_taxonomy(
    service: KnowledgeService, plan: dict[str, Any], generate_summaries: bool = True
) -> dict[str, Any]:
    """Create the confirmed taxonomy and backfill members (§7 steps 4-5).

    Plan shape:
        {"domains": [
            {"title": "Content automation", "why": "...", "indexes": [
                {"title": "YouTube", "community_ids": [3, 7], "why": "..."},
                {"title": "TikTok",  "community_ids": [5]},
            ]},
        ]}

    Each index's `community_ids` are the Louvain communities whose member nodes get
    filed into it. Summaries are generated server-side unless a scope is refreshed later
    with client-authored text (preferred). Returns creation + backfill stats.
    """
    repo = service.repo
    stats = {"domains": 0, "indexes": 0, "nodes_filed": 0, "summaries": 0,
             "created": {"domains": [], "indexes": []}}
    for d in plan.get("domains", []):
        dom_id = repo.add_scope("domain", d["title"], why=d.get("why"))
        stats["domains"] += 1
        stats["created"]["domains"].append({"id": dom_id, "title": d["title"]})
        for idx in d.get("indexes", []):
            idx_id = repo.add_scope("index", idx["title"], domain_id=dom_id, why=idx.get("why"))
            stats["indexes"] += 1
            stats["created"]["indexes"].append({"id": idx_id, "title": idx["title"], "domain_id": dom_id})
            community_ids = [int(c) for c in (idx.get("community_ids") or [])]
            if community_ids:
                stats["nodes_filed"] += repo.classify_community_nodes(community_ids, idx_id)
            if generate_summaries:
                service.refresh_summary(idx_id)
                stats["summaries"] += 1
        if generate_summaries:
            service.refresh_summary(dom_id)
            stats["summaries"] += 1
    total_nodes = len(repo.list_nodes())
    stats["unclassified_remaining"] = repo.unclassified_count()
    stats["total_nodes"] = total_nodes
    return stats
