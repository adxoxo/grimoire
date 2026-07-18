"""Knowledge service: the read/write paths that compose the repository and the
provider. The repository stores; the provider embeds and completes; this layer
orchestrates them into the operations the gateway exposes.

Phase 1 covers ingest_document and retrieve. Distillation/capture (Phase 3) and
compaction (Phase 5) live in their own modules but use this same composition.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from grimoire.providers.base import Provider
from grimoire.rerank import Reranker
from grimoire.store import Repository

HALF_LIFE_DAYS = 90.0
# Reciprocal rank fusion constant for hybrid retrieval (the standard k=60).
RRF_K = 60
# ~500 tokens at ~4 chars/token, with a small overlap. Tune later.
CHUNK_CHARS = 2000
CHUNK_OVERLAP = 200


def recency_decay(updated_at: str, now: datetime | None = None) -> float:
    """Exponential decay with a ~90 day half-life, in [0, 1]."""
    now = now or datetime.now(timezone.utc)
    try:
        ts = datetime.fromisoformat(updated_at)
    except ValueError:
        return 1.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def chunk_text(text: str, target: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Paragraph-aware chunking to ~target chars with a small carry-over overlap."""
    paras: list[str] = []
    for p in re.split(r"\n\s*\n", text):
        p = p.strip()
        if not p:
            continue
        while len(p) > target:  # hard-split a single overlong paragraph
            paras.append(p[:target])
            p = p[target - overlap:]
        paras.append(p)
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > target:
            chunks.append(cur)
            cur = (cur[-overlap:] + "\n\n" + p) if overlap else p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def _to_markdown(source: str) -> tuple[str, str]:
    """Return (title, markdown) for a local path or URL. PDF and HTML are converted;
    markdown/text pass through. Never returns raw PDF bytes.
    """
    if source.startswith(("http://", "https://")):
        resp = httpx.get(source, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        title = source.rstrip("/").split("/")[-1] or source
        if "pdf" in ctype or source.lower().endswith(".pdf"):
            import tempfile
            import pymupdf4llm

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(resp.content)
                tmp = f.name
            return title, pymupdf4llm.to_markdown(tmp)
        from markdownify import markdownify

        return title, markdownify(resp.text)

    path = Path(source)
    title = path.stem
    suffix = path.suffix.lower()
    # PyMuPDF (fitz) opens PDFs and common ebook formats; pymupdf4llm renders them to markdown.
    if suffix in (".pdf", ".epub", ".xps", ".fb2", ".mobi", ".cbz"):
        import pymupdf4llm

        return title, pymupdf4llm.to_markdown(str(path))
    if suffix in (".html", ".htm"):
        from markdownify import markdownify

        return title, markdownify(path.read_text(encoding="utf-8", errors="replace"))
    return title, path.read_text(encoding="utf-8", errors="replace")


class KnowledgeService:
    def __init__(self, repo: Repository, provider: Provider, reranker: Reranker | None = None) -> None:
        self.repo = repo
        self.provider = provider
        self.reranker = reranker

    # ---- read path ------------------------------------------------------

    def retrieve(
        self,
        query: str,
        project: str | None = None,
        k: int = 10,
        rerank_candidates: int = 25,
        mode: str = "hybrid",
    ) -> list[dict]:
        """Graph-narrow, then search by `mode`, then (if a re-ranker is configured) a
        local cross-encoder re-rank of the top candidates.

        Modes: 'hybrid' (default) fuses BM25 keyword search with vector search via
        reciprocal rank fusion (k=60) and applies recency decay after fusion — vector
        recall plus exact-identifier precision. 'vector' is the pure bi-encoder path
        (similarity x recency, the pre-hybrid behaviour). 'keyword' is BM25 only and
        needs no embedding provider at all.

        With a project, candidates are narrowed to its 1-2 hop neighbourhood (entity cap
        applied in the repository) before scoring. Without one, all chunks score. The
        re-rank is best-effort: if the model is unavailable it falls back to the score
        order, so retrieval never depends on the re-ranker being loadable.
        """
        if mode not in ("hybrid", "vector", "keyword"):
            raise ValueError(f"unknown retrieval mode: {mode!r}")
        node_ids = None
        if project:
            proj = self.repo.get_project(project)
            if proj is None:
                return []
            node_ids = self.repo.candidate_node_ids(proj["id"])
        now = datetime.now(timezone.utc)

        if mode == "vector":
            rows = self.repo.scored_chunks(self.provider.embed_query(query), node_ids=node_ids)
            scored = []
            for r in rows:
                similarity = 1.0 - float(r["distance"])  # cosine distance -> similarity
                score = similarity * recency_decay(r["updated_at"], now)
                scored.append({**r, "similarity": similarity, "score": score})
        elif mode == "keyword":
            rows = self.repo.keyword_chunks(query, node_ids=node_ids)
            scored = [
                {**r, "score": 1.0 / (RRF_K + rank + 1) * recency_decay(r["updated_at"], now)}
                for rank, r in enumerate(rows)
            ]
        else:  # hybrid: RRF-fuse both legs, recency decay after fusion
            vec_rows = self.repo.scored_chunks(self.provider.embed_query(query), node_ids=node_ids)
            kw_rows = self.repo.keyword_chunks(query, node_ids=node_ids)
            fused: dict[str, dict] = {}
            for leg in (vec_rows[:100], kw_rows):
                for rank, r in enumerate(leg):
                    entry = fused.setdefault(r["chunk_id"], {**r, "rrf": 0.0})
                    entry["rrf"] += 1.0 / (RRF_K + rank + 1)
            scored = []
            for r in fused.values():
                score = r.pop("rrf") * recency_decay(r["updated_at"], now)
                if "distance" in r:
                    r["similarity"] = 1.0 - float(r["distance"])
                scored.append({**r, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        if self.reranker is not None and len(scored) > 1:
            return self._rerank(query, scored[:rerank_candidates])[:k]
        return scored[:k]

    def _rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """Second-stage re-rank of candidates by a local cross-encoder relevance score.

        Best-effort: on ANY failure (model can't load, fastembed missing, score-count
        mismatch) it returns the input order unchanged, degrading to the bi-encoder ranking
        rather than breaking retrieval. Attaches `rerank_score` for observability.
        """
        if self.reranker is None or len(candidates) <= 1:
            return candidates
        passages = [(c.get("content") or "") for c in candidates]
        try:
            scores = self.reranker.scores(query, passages)
        except Exception:  # noqa: BLE001 - reranker unavailable -> keep bi-encoder order
            return candidates
        if len(scores) != len(candidates):
            return candidates
        ranked = sorted(zip(candidates, scores), key=lambda t: t[1], reverse=True)
        return [{**c, "rerank_score": s} for c, s in ranked]

    # ---- write path: documents -----------------------------------------

    def ingest_document(
        self,
        source: str,
        project: str | None = None,
        title: str | None = None,
        extra_meta: dict | None = None,
    ) -> dict:
        """Convert source to markdown, chunk, embed, and write node + chunks + vectors.
        Links the document to a project when given. Returns the node id and chunk count.
        """
        derived_title, markdown = _to_markdown(source)
        title = title or derived_title
        chunks = chunk_text(markdown)
        # Keep the full markdown on the node (not embedded) so the tome reader shows the
        # original document, not overlap-duplicated chunks.
        node_id = self.repo.add_node(
            "document", title, status="unreviewed",
            meta={"source": source, **(extra_meta or {})}, context_summary=markdown
        )
        for seq, chunk in enumerate(chunks):
            self.repo.add_chunk(node_id, seq, chunk, self.provider.embed(chunk))
        if project:
            proj = self.repo.get_project(project)
            if proj is None:
                proj_id = self.repo.upsert_project(project)
            else:
                proj_id = proj["id"]
            self.repo.link_nodes(node_id, proj_id, "belongs_to")
        return {"node_id": node_id, "title": title, "chunks": len(chunks)}
