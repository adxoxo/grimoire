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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from grimoire.compaction import compact_project, consolidate_context
from grimoire.config import settings
from grimoire.distill import capture_session
from grimoire.planner.web import router as planner_router
from grimoire.providers import get_provider
from grimoire.reembed import reembed_all
from grimoire.scribe import scribe_from_text, suggest_project_for_document
from grimoire.service import KnowledgeService
from grimoire.store import Repository

app = FastAPI(title="The Grimoire", version="0.1.0")

# The dashboard runs on the Vite dev server during development.
# localhost dev origins, plus any public dashboard origin(s) from config.
_cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"] + [
    o.strip() for o in settings.public_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# The planner (Today + Flow) tabs. Registered before the SPA catch-all below so its
# /api/planner/* routes are not swallowed by the index.html fallback.
#
# NOTE: app.include_router() is broken in this pinned fastapi 0.138.0 / starlette 1.3.1
# combination (it collapses every sub-route into one empty-path route). The router's
# APIRoute objects are themselves correct and already carry their full /api/planner/*
# paths, so we splice them straight in. Revisit if the dependency pins change.
app.router.routes.extend(planner_router.routes)

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


@app.delete("/api/nodes/{node_id}")
def delete_node(node_id: str) -> dict:
    """Hard-delete a node and its dependents (edges, chunks, vectors, raw turns)."""
    with _repo() as repo:
        if repo.get_node(node_id) is None:
            raise HTTPException(status_code=404, detail="node not found")
        return {"deleted": repo.delete_node(node_id), "node_id": node_id}


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


# ---- write: scribe a new node (Task 2) ----


class NewNode(BaseModel):
    type: Literal["project", "entity", "document"]
    title: str
    meta: dict | None = None
    context: str | None = None  # project context_summary, or a node's body
    project: str | None = None  # for entity/document: link belongs_to this quest line


class ScribeMessage(BaseModel):
    message: str


@app.post("/api/scribe")
def scribe(payload: ScribeMessage) -> dict:
    """Quick-capture: an LLM turns a free-form sentence into one node (classified,
    titled, and filed under a quest line), created through the repository."""
    with _repo() as repo:
        svc = KnowledgeService(repo, _provider)
        try:
            return scribe_from_text(svc, payload.message)
        except Exception as exc:  # noqa: BLE001 - needs the LLM; surfaced as 503
            raise HTTPException(status_code=503, detail=f"scribe needs the LLM: {exc}") from exc


@app.post("/api/ingest")
def ingest(files: list[UploadFile] = File(...), project: str | None = Form(None)) -> dict:
    """Ingest uploaded documents (PDF, ebook, HTML, markdown, text) as tomes: convert to
    markdown, chunk, embed, and link to a quest line. Books/PDFs become searchable."""
    import os
    import tempfile

    typed = (project or "").strip()
    results: list[dict] = []
    with _repo() as repo:
        svc = KnowledgeService(repo, _provider)
        for f in files:
            suffix = os.path.splitext(f.filename or "")[1] or ".txt"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(f.file.read())
                path = tmp.name
            try:
                title = os.path.splitext(os.path.basename(f.filename or "document"))[0]
                # Route: what you typed wins; else the closest quest line by title; else Library.
                dest = typed or suggest_project_for_document(svc, title) or "Library"
                res = svc.ingest_document(path, project=dest, title=title)
                results.append({**res, "filename": f.filename, "project": dest})
            except Exception as exc:  # noqa: BLE001 - report per-file, keep going
                results.append({"filename": f.filename, "error": str(exc)})
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    return {"ingested": results, "project": typed or None}


@app.post("/api/nodes")
def create_node(payload: NewNode) -> dict:
    """Scribe a new node. Quest line -> upsert_project; rune/tome -> add_node (+link)."""
    with _repo() as repo:
        if payload.type == "project":
            pid = repo.upsert_project(payload.title, meta=payload.meta, context_patch=payload.context)
            return {"id": pid, "type": "project", "title": payload.title}
        node_id = repo.add_node(
            payload.type, payload.title, status="unreviewed", meta=payload.meta, context_summary=payload.context
        )
        if payload.project:
            proj = repo.get_project(payload.project)
            if proj is None:
                proj = {"id": repo.upsert_project(payload.project)}
            repo.link_nodes(node_id, proj["id"], "belongs_to")
        return {"id": node_id, "type": payload.type, "title": payload.title}


# ---- write: prune an edge (Task 3) ----


@app.delete("/api/edges")
def delete_edge(src: str, dst: str, rel: str) -> dict:
    """Sever a link between two nodes (the prune action)."""
    with _repo() as repo:
        deleted = repo.unlink_nodes(src, dst, rel)
        return {"deleted": deleted, "edge": {"src": src, "dst": dst, "rel": rel}}


# ---- maintenance triggers (Task 4 settings panel) ----


@app.post("/api/maintenance/compact")
def run_compaction() -> dict:
    """Run compaction + context consolidation across all projects (uses the LLM chain)."""
    with _repo() as repo:
        svc = KnowledgeService(repo, _provider)
        results = []
        for project in [n["title"] for n in repo.list_nodes(type="project")]:
            stats = compact_project(svc, project)
            consolidate_context(svc, project)
            results.append(stats)
    return {"compacted": results}


@app.post("/api/maintenance/reembed")
def run_reembed() -> dict:
    """Re-embed every chunk through the provider (the model-change maintenance path)."""
    with _repo() as repo:
        return {"reembedded": reembed_all(repo, _provider)}


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
