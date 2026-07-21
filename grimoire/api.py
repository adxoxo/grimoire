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

from grimoire import jobs
from grimoire.cluster import community_labels, recluster
from grimoire.compaction import compact_project, consolidate_context
from grimoire.config import settings
from grimoire.distill import capture_session
from grimoire.planner.web import router as planner_router
from grimoire.providers import get_provider
from grimoire.rerank import get_reranker
from grimoire.reembed import reembed_all
from grimoire.scheduler import lifespan
from grimoire.scribe import scribe_from_text, suggest_project_for_document
from grimoire.service import KnowledgeService
from grimoire.store import Repository

app = FastAPI(title="The Grimoire", version="0.1.0", lifespan=lifespan)


class _WriteAuthASGI:
    """Require `Authorization: Bearer <token>` on write-capable /api routes when
    GRIMOIRE_API_TOKEN is set. Read routes stay open (they get gated with the public
    exposure work). Pure ASGI, same pattern as the MCP gateway's guard; the token is
    read per-request so tests can toggle it without re-importing the app."""

    _OPEN_METHODS = ("GET", "HEAD", "OPTIONS")

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        token = settings.api_token
        if (
            token
            and scope.get("type") == "http"
            and scope.get("method") not in self._OPEN_METHODS
            and scope.get("path", "").startswith("/api/")
        ):
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization", b"").decode() != f"Bearer {token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


app.add_middleware(_WriteAuthASGI)

# The dashboard runs on the Vite dev server during development.
# localhost dev origins, plus any public dashboard origin(s) from config.
_cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"] + [
    o.strip() for o in settings.public_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
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

# Reused across requests; the store connection is per-request. The re-ranker model loads
# lazily on the first search, so this stays cheap at startup.
_provider = get_provider()
_reranker = get_reranker(settings.rerank_enabled, settings.rerank_model)

# Fail loudly at startup when the configured Ollama is unreachable: broken embeddings
# must never degrade silently. Only the real provider is checked; fake stays offline.
if settings.provider == "ollama":
    from grimoire.providers.ollama import verify_reachable

    verify_reachable(settings.ollama_url)


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
def graph() -> dict[str, object]:
    """The whole constellation: nodes + edges + saved layout. `layout` maps node_id to
    {x, y, pinned}; the client restores these so the graph opens settled and only
    simulates nodes without a saved position."""
    with _repo() as repo:
        nodes = repo.list_nodes()
        edges = repo.list_edges()
        labels = community_labels(nodes, edges)
        return {
            "nodes": nodes,
            "edges": edges,
            "layout": repo.get_layout(),
            "communities": {str(cid): {"label": title} for cid, title in labels.items()},
        }


class LayoutPosition(BaseModel):
    node_id: str
    x: float
    y: float
    pinned: bool = False


@app.put("/api/layout")
def save_layout(positions: list[LayoutPosition]) -> dict:
    """Persist constellation node positions (after the sim settles, or on drag end)."""
    with _repo() as repo:
        return {"saved": repo.save_layout([p.model_dump() for p in positions])}


@app.get("/api/nodes/{node_id}")
def node(node_id: str) -> dict:
    with _repo() as repo:
        found = repo.get_node(node_id)
        if found is None:
            raise HTTPException(status_code=404, detail="node not found")
        return found


@app.get("/api/nodes/{node_id}/full")
def node_full(node_id: str) -> dict:
    """Full-fidelity read of a node: its record, complete un-truncated chunk text, and
    (for a chronicle) its raw conversation turns. The drill-down behind summary-first
    retrieval; reads only, embeds nothing."""
    with _repo() as repo:
        svc = KnowledgeService(repo, _provider)
        out = svc.read_node_full(node_id)
        if out is None:
            raise HTTPException(status_code=404, detail="node not found")
        return out


@app.delete("/api/nodes/{node_id}")
def delete_node(node_id: str) -> dict:
    """Hard-delete a node and its dependents (edges, chunks, vectors, raw turns). A
    domain/index scope instead detaches its members to the inbox (never cascades)."""
    with _repo() as repo:
        node = repo.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="node not found")
        if node.get("node_kind") in ("domain", "index"):
            return {"scope": node_id, **repo.delete_scope(node_id)}
        return {"deleted": repo.delete_node(node_id), "node_id": node_id}


@app.get("/api/projects/{name}")
def project(name: str) -> dict:
    """Project hub: the node, its living context, one hop of linked nodes, and breadcrumb."""
    with _repo() as repo:
        found = repo.get_project(name)
        if found is None:
            raise HTTPException(status_code=404, detail="project not found")
        found["breadcrumb"] = repo.node_breadcrumb(found["id"])
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
def search(
    q: str,
    project: str | None = None,
    k: int = 10,
    mode: str = "hybrid",
    route: bool = True,
    domain_id: str | None = None,
    index_id: str | None = None,
) -> dict:
    """Full retrieve path with two-stage scoped retrieval: an explicit project graph-
    narrows (legacy), an explicit domain_id/index_id pins the partition, otherwise the
    query auto-routes to the best index(es) and falls back to global. Returns results
    plus a `routing` block. Vector legs need Ollama; keyword mode works without it."""
    scope = {"domain_id": domain_id, "index_id": index_id} if (domain_id or index_id) else None
    with _repo() as repo:
        try:
            out = KnowledgeService(repo, _provider, _reranker).retrieve_scoped(
                q, project=project, scope=scope, route=route, k=k,
                rerank_candidates=settings.rerank_candidates, mode=mode,
                route_threshold=settings.route_threshold, route_top_k=settings.route_top_k,
                k_min=settings.retrieve_k_min, project_max_hops=settings.project_max_hops,
                expand_related=settings.expand_related,
                related_per_hit=settings.related_per_hit,
                related_min_confidence=settings.related_min_confidence,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as 503
            raise HTTPException(
                status_code=503,
                detail=f"search needs the embedding model running: {exc}",
            ) from exc
        return {"query": q, "results": out["results"],
                "related": out.get("related", []), "routing": out["routing"]}


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
#
# These jobs run for many seconds (LLM chains, whole-store re-embed). They run on a
# background thread via the job registry so the POST returns at once; the client polls
# GET /api/jobs for progress and the result. The registry dedupes per kind, so a
# re-clicked button or a second tab cannot start an overlapping run. Each runner opens
# its own Repository on its thread (SQLite wants one connection per unit of work).


@app.post("/api/maintenance/compact")
def run_compaction() -> dict:
    """Start compaction + context consolidation across all projects on a background
    thread (uses the LLM chain). Returns the job snapshot; poll GET /api/jobs."""

    def runner(report: jobs.ReportFn) -> dict:
        with _repo() as repo:
            svc = KnowledgeService(repo, _provider)
            projects = [n["title"] for n in repo.list_nodes(type="project")]
            results = []
            for i, project in enumerate(projects):
                report({"done": i, "total": len(projects), "detail": project})
                stats = compact_project(svc, project)
                consolidate_context(svc, project)
                results.append(stats)
            report({"done": len(projects), "total": len(projects), "detail": ""})
        return {"compacted": results}

    job, started = jobs.registry.start("compact", runner)
    return {"job": job, "started": started}


@app.post("/api/maintenance/reembed")
def run_reembed() -> dict:
    """Start a whole-store re-embed on a background thread (the model-change maintenance
    path). Returns the job snapshot; the result carries the chunk and scope counts."""

    def runner(report: jobs.ReportFn) -> dict:
        with _repo() as repo:
            def prog(count: int, _chunk: dict) -> None:
                report({"done": count, "total": 0, "detail": "re-embedding chunks"})

            return {"reembedded": reembed_all(repo, _provider, progress=prog)}

    job, started = jobs.registry.start("reembed", runner)
    return {"job": job, "started": started}


@app.post("/api/maintenance/recluster")
def run_recluster() -> dict:
    """Recompute Louvain communities over the constellation on a background thread. The
    global graph view colours its clusters from this. Returns the job snapshot."""

    def runner(_report: jobs.ReportFn) -> dict:
        with _repo() as repo:
            return recluster(repo)

    job, started = jobs.registry.start("recluster", runner)
    return {"job": job, "started": started}


@app.get("/api/jobs")
def jobs_status() -> dict:
    """Live status of the background maintenance jobs, latest per kind. Poll this while a
    job runs; a read route, so it stays open even when writes are token-guarded."""
    return jobs.registry.snapshot()


# ---- taxonomy: scopes, the classification inbox, summaries (V2) ----


class NewDomain(BaseModel):
    title: str
    why: str | None = None


class NewIndex(BaseModel):
    domain_id: str
    title: str
    why: str | None = None


class ClassifyBody(BaseModel):
    index_id: str


class RefreshSummaryBody(BaseModel):
    summary_text: str | None = None


@app.get("/api/scopes")
def scopes() -> dict:
    """The taxonomy: domains with their indexes, member counts, and summary freshness."""
    with _repo() as repo:
        return repo.list_scopes(stale_after=settings.summary_stale_after)


@app.post("/api/scopes/domain")
def create_domain(payload: NewDomain) -> dict:
    """Create a domain scope."""
    with _repo() as repo:
        return {"id": repo.add_scope("domain", payload.title, why=payload.why),
                "node_kind": "domain", "title": payload.title}


@app.post("/api/scopes/index")
def create_index(payload: NewIndex) -> dict:
    """Create an index under a domain."""
    with _repo() as repo:
        if repo.get_scope(payload.domain_id) is None:
            raise HTTPException(status_code=404, detail="domain not found")
        return {"id": repo.add_scope("index", payload.title, domain_id=payload.domain_id,
                                     why=payload.why),
                "node_kind": "index", "title": payload.title, "domain_id": payload.domain_id}


@app.post("/api/scopes/{scope_id}/refresh")
def refresh_summary(scope_id: str, payload: RefreshSummaryBody) -> dict:
    """Regenerate + re-embed a scope's routing summary (client text preferred)."""
    with _repo() as repo:
        svc = KnowledgeService(repo, _provider)
        try:
            out = svc.refresh_summary(scope_id, summary_text=payload.summary_text)
        except Exception as exc:  # noqa: BLE001 - embedding needs the provider
            raise HTTPException(status_code=503, detail=f"summary needs the embedder: {exc}") from exc
        if "error" in out:
            raise HTTPException(status_code=404, detail=out["error"])
        return out


@app.delete("/api/scopes/{scope_id}")
def delete_scope(scope_id: str) -> dict:
    """Delete a domain/index, detaching its members back to the inbox (no cascade)."""
    with _repo() as repo:
        out = repo.delete_scope(scope_id)
        if out is None:
            raise HTTPException(status_code=404, detail="scope not found")
        return {"scope": scope_id, **out}


@app.get("/api/inbox")
def inbox(limit: int = 50) -> dict:
    """Unclassified content nodes awaiting a home, each with its stored proposal."""
    with _repo() as repo:
        return {"items": repo.unclassified_nodes(limit=limit),
                "total": repo.unclassified_count()}


@app.post("/api/nodes/{node_id}/classify")
def classify_node(node_id: str, payload: ClassifyBody) -> dict:
    """File a content node into an index (confirm a proposal or triage from the inbox)."""
    with _repo() as repo:
        try:
            out = repo.classify_node(node_id, payload.index_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if out is None:
            raise HTTPException(status_code=404, detail="node not found")
        return out


@app.post("/api/nodes/{node_id}/autoclassify")
def autoclassify_node(node_id: str, use_llm: bool = True) -> dict:
    """Auto-file one inbox node into its best index (LLM over vector routing). Degrades
    to the vector path when the LLM is unavailable; files only on a confident match."""
    with _repo() as repo:
        svc = KnowledgeService(repo, _provider)
        try:
            return svc.auto_classify_node(
                node_id, use_llm=use_llm, autofile_threshold=settings.autofile_threshold
            )
        except Exception as exc:  # noqa: BLE001 - embedding/LLM needs the provider
            raise HTTPException(status_code=503, detail=f"autoclassify needs the provider: {exc}") from exc


@app.post("/api/inbox/autofile")
def autofile_inbox(use_llm: bool = True, limit: int | None = None) -> dict:
    """Start a bulk auto-file of the inbox on a background thread. Returns the job
    snapshot; the result carries the filed/skipped split. Poll GET /api/jobs for
    progress (done/total) as items are filed."""

    def runner(report: jobs.ReportFn) -> dict:
        with _repo() as repo:
            svc = KnowledgeService(repo, _provider)

            def prog(done: int, total: int) -> None:
                report({"done": done, "total": total, "detail": "filing inbox"})

            return svc.auto_classify_inbox(
                limit=limit, use_llm=use_llm,
                autofile_threshold=settings.autofile_threshold, progress=prog,
            )

    job, started = jobs.registry.start("autofile", runner)
    return {"job": job, "started": started}


# ---- serve the built dashboard (production / Docker) ----
# In dev the dashboard runs on Vite (:5173) and proxies /api here. In a built deploy the
# API serves the SPA itself, so it is one container and same-origin (no CORS/proxy).
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        """SPA fallback: any non-API path returns index.html for client-side routing.
        no-cache so a deploy reaches the browser on the next load: the shell must be
        revalidated every time, while the hashed /assets bundles stay cacheable."""
        return FileResponse(
            _DIST / "index.html",
            headers={"cache-control": "no-cache, must-revalidate"},
        )
