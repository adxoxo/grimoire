"""Community detection over the constellation graph.

Louvain via networkx (pure Python, already a dependency) rather than Leiden via
leidenalg/igraph: those need a C toolchain this box does not have, and at this graph
size Louvain with a fixed seed is deterministic, fast, and equally useful for the
purpose here (visual grouping). Recomputed on demand via kb_recluster, never on write.
"""

from __future__ import annotations

import networkx as nx

from grimoire.store import Repository

SEED = 42  # fixed so reruns on an unchanged graph give identical communities


def recluster(repo: Repository) -> dict:
    """Run Louvain over the full node/edge graph and persist community ids.

    Communities are numbered largest-first (ties broken by smallest member id) so the
    numbering is stable across reruns when the graph has not changed.
    """
    nodes = repo.list_nodes()
    edges = repo.list_edges()
    graph = nx.Graph()
    graph.add_nodes_from(n["id"] for n in nodes)
    graph.add_edges_from((e["src"], e["dst"]) for e in edges)
    communities = nx.community.louvain_communities(graph, seed=SEED)
    ordered = sorted(communities, key=lambda c: (-len(c), min(c)))
    assignment = {nid: cid for cid, members in enumerate(ordered) for nid in members}
    repo.set_communities(assignment)
    return {"communities": len(ordered), "nodes": len(assignment)}


def community_labels(nodes: list[dict], edges: list[dict]) -> dict[int, str]:
    """Label each community with its highest-degree member's title (no LLM needed)."""
    degree: dict[str, int] = {}
    for e in edges:
        degree[e["src"]] = degree.get(e["src"], 0) + 1
        degree[e["dst"]] = degree.get(e["dst"], 0) + 1
    best: dict[int, tuple[int, str]] = {}
    for n in nodes:
        cid = n.get("community_id")
        if cid is None:
            continue
        d = degree.get(n["id"], 0)
        if cid not in best or d > best[cid][0]:
            best[cid] = (d, n["title"])
    return {cid: title for cid, (_, title) in best.items()}
