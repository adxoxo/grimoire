"""Read-only HTTP API serving the dashboard.

A thin slice of the Phase 2 gateway: it exposes the repository's read methods over
HTTP so the constellation and project views draw real data from the store. Writes and
the MCP tool surface come with the full gateway later. The API calls repository
intent-methods only; it never touches the engine directly.

Run:
    .venv/bin/uvicorn grimoire.api:app --reload
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Iterator, Literal, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from grimoire.config import settings
from grimoire.distill import capture_session
from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository

app = FastAPI(title="The Grimoire", version="0.1.0")

# The dashboard runs on the Vite dev server during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Reused across requests; the store connection is per-request.
_provider = get_provider()


@contextmanager
def _repo() -> Iterator[Repository]:
    repo = Repository(settings.db_path)
    try:
        yield repo
    finally:
        repo.close()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/graph")
def graph() -> dict[str, list]:
    """The whole constellation: nodes + edges, for the force-directed layout."""
    with _repo() as repo:
        return {"nodes": repo.list_nodes(), "edges": repo.list_edges()}


@app.get("/api/nodes/{node_id}")
def node(node_id: str) -> dict:
    with _repo() as repo:
        found = repo.get_node(node_id)
        if found is None:
            raise HTTPException(status_code=404, detail="node not found")
        return found


@app.get("/api/projects/{name}")
def project(name: str) -> dict:
    """Project hub: the node, its living context, and one hop of linked nodes."""
    with _repo() as repo:
        found = repo.get_project(name)
        if found is None:
            raise HTTPException(status_code=404, detail="project not found")
        return found


@app.get("/api/review")
def review_queue() -> dict:
    """Unreviewed nodes awaiting triage (the review sanctum)."""
    with _repo() as repo:
        return {"items": repo.nodes_by_status("unreviewed")}


@app.post("/api/nodes/{node_id}/review")
def mark_reviewed(node_id: str) -> dict:
    """Mark a node reviewed. Only the user does this, via the review queue."""
    with _repo() as repo:
        if repo.get_node(node_id) is None:
            raise HTTPException(status_code=404, detail="node not found")
        repo.set_status(node_id, "reviewed")
        return {"node_id": node_id, "status": "reviewed"}


@app.get("/api/documents/{node_id}")
def document(node_id: str) -> dict:
    """A tome's full markdown for the reader: the stored body, or joined chunks."""
    with _repo() as repo:
        node = repo.get_node(node_id)
        if node is None or node["type"] != "document":
            raise HTTPException(status_code=404, detail="document not found")
        content = node.get("context_summary") or "\n\n".join(repo.node_chunk_texts(node_id))
        return {
            "id": node["id"],
            "title": node["title"],
            "status": node["status"],
            "meta": node["meta"],
            "content": content,
        }


@app.get("/api/search")
def search(q: str, project: str | None = None, k: int = 10) -> dict:
    """Full retrieve path: graph-narrow (optional project) then similarity x recency.
    Requires the embedding provider (Ollama) to be reachable."""
    with _repo() as repo:
        try:
            hits = KnowledgeService(repo, _provider).retrieve(q, project=project, k=k)
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as 503
            raise HTTPException(
                status_code=503,
                detail=f"search needs the embedding model running: {exc}",
            ) from exc
        return {"query": q, "results": hits}


# ---- n8n capture webhook (Phase 4): one endpoint, two payload types ----


class Turn(BaseModel):
    role: str
    content: str


class ConversationCapture(BaseModel):
    type: Literal["conversation_capture"]
    project: str
    turns: list[Turn]
    created_at: str | None = None


class ProjectContext(BaseModel):
    type: Literal["project_context"]
    project: str
    meta: dict | None = None
    context_patch: str | None = None
    status: str | None = None


CapturePayload = Annotated[Union[ConversationCapture, ProjectContext], Field(discriminator="type")]


@app.post("/api/capture")
def capture(payload: CapturePayload) -> dict:
    """The n8n ingestion target. conversation_capture distils + writes a chronicle;
    project_context upserts a project hub. Both land in the one store."""
    with _repo() as repo:
        svc = KnowledgeService(repo, _provider)
        if isinstance(payload, ConversationCapture):
            turns = [t.model_dump() for t in payload.turns]
            try:
                result = capture_session(svc, payload.project, turns, created_at=payload.created_at)
            except Exception as exc:  # noqa: BLE001 - distillation needs the LLM
                raise HTTPException(status_code=503, detail=f"capture needs the LLM: {exc}") from exc
            return {"kind": "conversation_capture", **result}
        pid = repo.upsert_project(
            payload.project, meta=payload.meta, context_patch=payload.context_patch, status=payload.status
        )
        return {"kind": "project_context", "project_id": pid, "name": payload.project}


# ---- serve the built dashboard (production / Docker) ----
# In dev the dashboard runs on Vite (:5173) and proxies /api here. In a built deploy the
# API serves the SPA itself, so it is one container and same-origin (no CORS/proxy).
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        """SPA fallback: any non-API path returns index.html for client-side routing."""
        return FileResponse(_DIST / "index.html")
