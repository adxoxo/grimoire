"""Edge provenance acceptance tests: explicit default, inferred writes, migration
backfill, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.store import Repository


def test_default_edges_are_explicit(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        pid = repo.upsert_project("Demo")
        mid = repo.add_node("memory", "m")
        repo.link_nodes(mid, pid, "belongs_to")
        (edge,) = repo.list_edges()
        assert edge["provenance"] == "explicit"
        assert edge["confidence"] == 1.0
    finally:
        repo.close()


def test_inferred_edge_persists(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        pid = repo.upsert_project("Demo")
        did = repo.add_node("document", "d")
        repo.link_nodes(did, pid, "references", provenance="inferred", confidence=0.62)
        (edge,) = repo.list_edges()
        assert edge["provenance"] == "inferred"
        assert edge["confidence"] == pytest.approx(0.62)
    finally:
        repo.close()


def test_unknown_provenance_rejected(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        pid = repo.upsert_project("Demo")
        mid = repo.add_node("memory", "m")
        with pytest.raises(ValueError):
            repo.link_nodes(mid, pid, "belongs_to", provenance="guessed")
    finally:
        repo.close()


def test_write_memory_edges_default_explicit(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        repo.upsert_project("Demo")
        repo.write_memory("Demo", "a summary", entities=["Some API"])
        edges = repo.list_edges()
        assert len(edges) == 2  # belongs_to + mentions
        assert all(e["provenance"] == "explicit" and e["confidence"] == 1.0 for e in edges)
    finally:
        repo.close()
