"""Tests for the one-way Obsidian vault export (grimoire.export).

No provider/embeddings needed: chunks are inserted with plain zero vectors,
sized to the repository's embed_dim, purely to exercise the document
chunk-text fallback path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.export import MARKER_NAME, export_store
from grimoire.store import Repository


def _zero_vec(repo: Repository) -> list[float]:
    return [0.0] * repo.embed_dim


def _build_store(tmp_path: Path) -> tuple[Repository, dict[str, str]]:
    repo = Repository(tmp_path / "g.db")
    ids: dict[str, str] = {}

    ids["alpha"] = repo.add_node("project", "Alpha", status="active")
    ids["beta"] = repo.add_node("project", "Beta", status="active")

    ids["doc"] = repo.add_node("document", "Notes", meta={"tags": ["ref", "doc"]})
    repo.add_chunk(ids["doc"], 0, "First chunk of notes.", _zero_vec(repo))
    repo.add_chunk(ids["doc"], 1, "Second chunk of notes.", _zero_vec(repo))
    repo.link_nodes(ids["doc"], ids["alpha"], "belongs_to")

    ids["entity"] = repo.add_node("entity", "API", status="unreviewed")

    ids["mem1"] = repo.add_node(
        "memory", "Session 1", status="unreviewed",
        context_summary="Distilled summary of session 1.",
    )
    repo.link_nodes(ids["mem1"], ids["alpha"], "belongs_to")
    repo.link_nodes(ids["mem1"], ids["entity"], "mentions")
    repo.link_nodes(ids["mem1"], ids["doc"], "references")

    ids["mem2"] = repo.add_node("memory", "Summary", context_summary="Compacted summary.")
    repo.link_nodes(ids["mem2"], ids["alpha"], "belongs_to")
    repo.link_nodes(ids["mem2"], ids["mem1"], "derived_from")

    ids["dup1"] = repo.add_node("memory", "Duplicate Title", context_summary="dup memory one")
    ids["dup2"] = repo.add_node("memory", "Duplicate Title", context_summary="dup memory two")
    repo.link_nodes(ids["dup1"], ids["beta"], "belongs_to")
    repo.link_nodes(ids["dup2"], ids["beta"], "belongs_to")

    return repo, ids


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm


def _find_file_with_id(output_dir: Path, node_type: str, node_id: str) -> Path:
    for p in (output_dir / node_type).glob("*.md"):
        if f'"{node_id}"' in p.read_text(encoding="utf-8"):
            return p
    raise AssertionError(f"no {node_type} file found with grimoire_id {node_id}")


def test_export_layout_and_frontmatter(tmp_path: Path):
    repo, ids = _build_store(tmp_path)
    out = tmp_path / "vault"
    result = export_store(repo, out)

    assert result["output_dir"] == str(out)
    assert result["nodes"] == 8
    assert result["edges"] == len(repo.list_edges())
    assert (out / MARKER_NAME).exists()

    for node_type in ("project", "document", "memory", "entity"):
        assert (out / node_type).is_dir()

    doc_file = _find_file_with_id(out, "document", ids["doc"])
    fm = _frontmatter(doc_file.read_text(encoding="utf-8"))
    assert fm["type"] == '"document"'
    assert fm["grimoire_id"] == f'"{ids["doc"]}"'
    assert fm["tags"] == '["ref", "doc"]'


def test_document_body_falls_back_to_chunks(tmp_path: Path):
    repo, ids = _build_store(tmp_path)
    out = tmp_path / "vault"
    export_store(repo, out)

    doc_file = _find_file_with_id(out, "document", ids["doc"])
    text = doc_file.read_text(encoding="utf-8")
    assert "First chunk of notes." in text
    assert "Second chunk of notes." in text


def test_wikilinks_grouped_under_rel_headings(tmp_path: Path):
    repo, ids = _build_store(tmp_path)
    out = tmp_path / "vault"
    export_store(repo, out)

    mem1_file = _find_file_with_id(out, "memory", ids["mem1"])
    text = mem1_file.read_text(encoding="utf-8")
    assert "## Belongs to" in text
    assert "## Mentions" in text
    assert "## References" in text
    assert "|Alpha]]" in text
    assert "|API]]" in text
    assert "|Notes]]" in text

    mem2_file = _find_file_with_id(out, "memory", ids["mem2"])
    text2 = mem2_file.read_text(encoding="utf-8")
    assert "## Derived from" in text2
    assert "|Session 1]]" in text2


def test_incoming_links_under_linked_from(tmp_path: Path):
    repo, ids = _build_store(tmp_path)
    out = tmp_path / "vault"
    export_store(repo, out)

    entity_file = _find_file_with_id(out, "entity", ids["entity"])
    text = entity_file.read_text(encoding="utf-8")
    assert "## Linked from" in text
    assert "|Session 1]]" in text


def test_collision_slugs_differ(tmp_path: Path):
    repo, ids = _build_store(tmp_path)
    out = tmp_path / "vault"
    export_store(repo, out)

    dup1_file = _find_file_with_id(out, "memory", ids["dup1"])
    dup2_file = _find_file_with_id(out, "memory", ids["dup2"])
    assert dup1_file != dup2_file
    slugs = {dup1_file.stem, dup2_file.stem}
    assert slugs == {"duplicate-title", "duplicate-title-2"}


def test_reexport_adds_and_removes_files(tmp_path: Path):
    repo, ids = _build_store(tmp_path)
    out = tmp_path / "vault"
    export_store(repo, out)

    stale_file = _find_file_with_id(out, "memory", ids["dup2"])
    assert stale_file.exists()

    gamma_id = repo.add_node("project", "Gamma", status="active")
    repo.delete_node(ids["dup2"])

    result = export_store(repo, out)
    assert result["nodes"] == 8  # 9 built - 1 deleted + 1 added
    assert not stale_file.exists()

    gamma_file = _find_file_with_id(out, "project", gamma_id)
    assert gamma_file.exists()

    # No leftover duplicate memory files from the first export.
    assert len(list((out / "memory").glob("*.md"))) == 3


def test_reexport_into_non_empty_dir_without_marker_raises(tmp_path: Path):
    repo, _ids = _build_store(tmp_path)
    out = tmp_path / "not_a_vault"
    out.mkdir()
    (out / "something.txt").write_text("pre-existing content", encoding="utf-8")

    with pytest.raises(ValueError):
        export_store(repo, out)
