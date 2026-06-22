"""Seed the store with real-shaped data so the dashboard draws a true graph.

Idempotent by reset: wipes the store file, then rebuilds. Uses the offline fake
provider, so no Ollama is required to seed. Run:

    .venv/bin/python scripts/seed.py
"""

from __future__ import annotations

from pathlib import Path

from grimoire.config import settings
from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository

# Real embeddings so the dashboard's search and retrieval are meaningful.
provider = get_provider()


def _wipe(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()


def _tome(repo: Repository, project_id: str, title: str, body: str) -> str:
    doc_id = repo.add_node("document", title, status="reviewed")
    repo.link_nodes(doc_id, project_id, "belongs_to")
    repo.add_chunk(doc_id, 0, body, provider.embed(body))
    return doc_id


def main() -> None:
    db_path = Path(settings.db_path)
    _wipe(db_path)
    repo = Repository(db_path)

    # --- Quest lines (projects) ---
    roar = repo.upsert_project(
        "ROAR",
        meta={"client": "OmniCorp", "stack": "GoHighLevel", "answered_queries": 24},
        status="active",
        context_patch=(
            "Project ROAR is a refactor of the core authentication microservices into a "
            "unified, zero-trust architecture. The current phase focuses on decoupling "
            "legacy identity providers while establishing a robust framework for autonomous "
            "agent delegation. Recent discoveries in the authentication codex suggest "
            "potential token vulnerabilities under high load, requiring attention before "
            "the next deployment cycle."
        ),
    )
    ftv = repo.upsert_project(
        "FTV Mushrooms",
        meta={"client": "self", "stack": "n8n + Shopify"},
        status="active",
        context_patch="Grow logs, substrate SOPs, and the storefront automation for the mushroom line.",
    )
    goated = repo.upsert_project(
        "GoatedTracking",
        meta={"client": "self", "stack": "n8n + Docker Compose"},
        status="active",
        context_patch="Affiliate and conversion tracking pipeline. Webhooks in, attribution out.",
    )
    grimoire = repo.upsert_project(
        "Grimoire",
        meta={"client": "self", "stack": "Python + SQLite + sqlite-vec"},
        status="active",
        context_patch="The shared knowledge base under all the agents. Phase 0 foundations shipped.",
    )
    repo.upsert_project(
        "Aether Notes",
        meta={"stack": "undecided"},
        status="idea",
        context_patch="An idea: voice-captured field notes that distil straight into chronicles.",
    )

    # --- Tomes (documents) ---
    _tome(repo, roar, "Auth API spec v2", "OpenAPI definitions and endpoint schemes for the v2 auth service.")
    _tome(repo, roar, "Legacy migration plan", "Step-by-step procedure for retiring the old identity providers.")
    _tome(repo, ftv, "Substrate recipe", "Master substrate formulation and sterilisation timings.")
    _tome(repo, goated, "Webhook field map", "Mapping of inbound affiliate webhook fields to attribution events.")
    _tome(repo, grimoire, "ARCHITECTURE", "The four-node model, repository layer, and provider interface.")

    # --- Chronicles (memory) + Runes (entities), with shared entities across projects ---
    repo.write_memory(
        project="ROAR",
        summary="Client kickoff sync: gathered requirements and agreed the zero-trust direction.",
        decisions=["adopt zero-trust", "decouple legacy IdP first"],
        entities=["GoHighLevel API", "OAuth2"],
        summary_embedding=provider.embed("Client kickoff sync for ROAR zero-trust auth"),
    )
    repo.write_memory(
        project="ROAR",
        summary="Architecture review: confirmed service boundaries and flagged a token issue under load.",
        decisions=["split token service", "add load test before deploy"],
        entities=["OAuth2"],
        summary_embedding=provider.embed("ROAR architecture review token under load"),
    )
    repo.write_memory(
        project="GoatedTracking",
        summary="Wired the GoHighLevel API poller into the attribution pipeline.",
        decisions=["poll GHL every 15m"],
        entities=["GoHighLevel API", "n8n"],  # GoHighLevel API now links ROAR <-> GoatedTracking
        summary_embedding=provider.embed("GoatedTracking GHL poller attribution"),
    )
    repo.write_memory(
        project="FTV Mushrooms",
        summary="Spring planning: laid out the grow schedule for the upcoming runs.",
        decisions=["two runs per month"],
        entities=["Shopify"],
        summary_embedding=provider.embed("FTV Mushrooms spring planning grow schedule"),
    )
    repo.write_memory(
        project="Grimoire",
        summary="Phase 0 shipped: repository layer, provider interface, backup/restore, all tested.",
        decisions=["SQLite + sqlite-vec", "Python only"],
        entities=["sqlite-vec", "FastMCP", "Ollama"],
        summary_embedding=provider.embed("Grimoire phase 0 shipped foundations"),
    )

    # A couple of real ingested tomes so the reader has full documents to open.
    svc = KnowledgeService(repo, provider)
    for doc in ("ARCHITECTURE.md", "CLAUDE.md"):
        if Path(doc).exists():
            svc.ingest_document(doc, project="Grimoire")

    counts = repo.counts()
    repo.close()
    print(f"seeded {db_path}")
    print(f"  {counts}")


if __name__ == "__main__":
    main()
