"""The MCP gateway: the one read/write interface every coding agent speaks to.

Exposes the knowledge service as MCP tools (kb_*). Each tool is wrapped in an
OpenTelemetry span capturing duration, project, and the count of candidate chunks
retrieved or written, so traversal paths and usage are traceable. Per the request,
this is the minimum tracing to map these gateway operations, no extra configurability.

Tracing note: an MCP stdio server uses stdout for the protocol, so spans are exported
to stderr, never stdout.

Run as an MCP server (stdio):
    .venv/bin/python -m grimoire.gateway
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator

from fastmcp import FastMCP
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from grimoire.config import settings
from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository

# --- tracing (spans -> stderr) ---
_tp = TracerProvider()
_tp.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
trace.set_tracer_provider(_tp)
tracer = trace.get_tracer("grimoire.gateway")

# Provider is reused across calls; the store connection is per-call (SQLite is happiest
# with one connection per unit of work).
_provider = get_provider()

mcp = FastMCP("Grimoire")


@contextmanager
def _service() -> Iterator[KnowledgeService]:
    repo = Repository(settings.db_path)
    try:
        yield KnowledgeService(repo, _provider)
    finally:
        repo.close()


@mcp.tool
def kb_retrieve(query: str, project: str | None = None, k: int = 10) -> list[dict]:
    """Retrieve the most relevant chunks for a query, optionally narrowed to a project."""
    with tracer.start_as_current_span("kb_retrieve") as span:
        span.set_attribute("grimoire.project", project or "")
        span.set_attribute("grimoire.k", k)
        with _service() as svc:
            hits = svc.retrieve(query, project=project, k=k)
        span.set_attribute("grimoire.candidate_chunks", len(hits))
        return [
            {
                "title": h["title"],
                "type": h["type"],
                "node_id": h["node_id"],
                "score": round(h["score"], 4),
                "content": h["content"],
            }
            for h in hits
        ]


@mcp.tool
def kb_write_memory(
    project: str,
    summary: str,
    decisions: list[str] | None = None,
    entities: list[str] | None = None,
) -> dict:
    """Write a distilled session memory, embedded and linked to its project."""
    with tracer.start_as_current_span("kb_write_memory") as span:
        span.set_attribute("grimoire.project", project)
        with _service() as svc:
            emb = svc.provider.embed(summary)
            mem_id = svc.repo.write_memory(
                project=project,
                summary=summary,
                decisions=decisions or [],
                entities=entities or [],
                summary_embedding=emb,
            )
        span.set_attribute("grimoire.chunks_written", 1)
        return {"node_id": mem_id, "chunks_written": 1}


@mcp.tool
def kb_get_project(name: str) -> dict:
    """Return a project hub: its node, living context, and one hop of linked nodes."""
    with tracer.start_as_current_span("kb_get_project") as span:
        span.set_attribute("grimoire.project", name)
        with _service() as svc:
            proj = svc.repo.get_project(name)
        if proj is None:
            return {"error": f"project not found: {name}"}
        span.set_attribute("grimoire.candidate_chunks", len(proj["linked"]))
        return proj


@mcp.tool
def kb_upsert_project(
    name: str,
    meta: dict | None = None,
    context_patch: str | None = None,
    status: str | None = None,
) -> dict:
    """Create a project hub or update it in place (preserving its id)."""
    with tracer.start_as_current_span("kb_upsert_project") as span:
        span.set_attribute("grimoire.project", name)
        with _service() as svc:
            pid = svc.repo.upsert_project(name, meta=meta, context_patch=context_patch, status=status)
        return {"project_id": pid, "name": name}


@mcp.tool
def kb_ingest_document(path: str, project: str | None = None) -> dict:
    """Ingest a document (PDF/HTML/markdown) into the store, linked to a project."""
    with tracer.start_as_current_span("kb_ingest_document") as span:
        span.set_attribute("grimoire.project", project or "")
        with _service() as svc:
            result = svc.ingest_document(path, project=project)
        span.set_attribute("grimoire.chunks_written", result["chunks"])
        return result


if __name__ == "__main__":
    mcp.run()
