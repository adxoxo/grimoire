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
from typing import Callable

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
        max_hops: int = 1,
    ) -> list[dict]:
        """Graph-narrow, then search by `mode`, then (if a re-ranker is configured) a
        local cross-encoder re-rank of the top candidates.

        Modes: 'hybrid' (default) fuses BM25 keyword search with vector search via
        reciprocal rank fusion (k=60) and applies recency decay after fusion — vector
        recall plus exact-identifier precision. 'vector' is the pure bi-encoder path
        (similarity x recency, the pre-hybrid behaviour). 'keyword' is BM25 only and
        needs no embedding provider at all.

        With a project, candidates are narrowed to its `max_hops` neighbourhood (entity
        cap applied in the repository) before scoring. Without one, all chunks score. The
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
            node_ids = self.repo.candidate_node_ids(proj["id"], max_hops=max_hops)
        return self._search_chunks(query, node_ids, k, mode, rerank_candidates)

    def _search_chunks(
        self,
        query: str,
        node_ids: list[str] | None,
        k: int,
        mode: str,
        rerank_candidates: int,
        q_emb: list[float] | None = None,
    ) -> list[dict]:
        """The scoring core shared by project-scoped, taxonomy-scoped, and global
        retrieval. `node_ids=None` scores all chunks; a list restricts to those nodes.
        `q_emb` lets a caller reuse a query embedding it already computed (routing)."""
        now = datetime.now(timezone.utc)
        if mode == "vector":
            q_emb = q_emb or self.provider.embed_query(query)
            rows = self.repo.scored_chunks(q_emb, node_ids=node_ids)
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
            q_emb = q_emb or self.provider.embed_query(query)
            vec_rows = self.repo.scored_chunks(q_emb, node_ids=node_ids)
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

    def retrieve_scoped(
        self,
        query: str,
        project: str | None = None,
        scope: dict | None = None,
        route: bool = True,
        k: int = 10,
        rerank_candidates: int = 25,
        mode: str = "hybrid",
        route_threshold: float = 0.35,
        route_top_k: int = 2,
        k_min: int = 3,
        project_max_hops: int = 1,
        expand_related: bool = True,
        related_per_hit: int = 6,
        related_min_confidence: float = 0.0,
    ) -> dict:
        """Two-stage scoped retrieval (V2). Returns {"results": [...], "related": [...],
        "routing": {...}}.

        Precedence: an explicit `project` keeps the legacy graph-narrow behaviour; an
        explicit `scope` ({domain_id?/index_id?}) pins the partition; otherwise, when
        `route` is on, the query is routed to the best-matching index(es) by summary
        similarity and searched inside them. If routing selects nothing, or a scoped
        search returns fewer than `k_min` hits, it falls back to unscoped global search
        and says so (routing.mode = 'global_fallback'), never silently empty.
        """
        if mode not in ("hybrid", "vector", "keyword"):
            raise ValueError(f"unknown retrieval mode: {mode!r}")

        # Legacy project scoping stays exactly as before (backward compatible).
        if project:
            results = self.retrieve(query, project=project, k=k,
                                    rerank_candidates=rerank_candidates, mode=mode,
                                    max_hops=project_max_hops)
            related = self._expand_related(
                results, enabled=expand_related,
                per_hit=related_per_hit, min_confidence=related_min_confidence)
            return {"results": results, "related": related,
                    "routing": {"mode": "project", "project": project}}

        q_emb: list[float] | None = None
        node_ids: list[str] | None = None
        routing: dict = {"mode": "global", "matched_indexes": [], "matched_domain": None}

        # Explicit scope wins over auto-routing.
        if scope and (scope.get("index_id") or scope.get("domain_id")):
            if scope.get("index_id"):
                node_ids = self.repo.scope_member_ids(index_ids=[scope["index_id"]])
            else:
                node_ids = self.repo.scope_member_ids(domain_ids=[scope["domain_id"]])
            routing = {"mode": "scoped", "explicit": True,
                       "index_id": scope.get("index_id"),
                       "domain_id": scope.get("domain_id")}
        elif route and mode != "keyword":
            # Auto-route: index-first, then domain (broad questions), then global.
            q_emb = self.provider.embed_query(query)
            idx = self.repo.rank_scopes(q_emb, kind="index", limit=route_top_k)
            matched = [r for r in idx if r["similarity"] >= route_threshold]
            if matched:
                node_ids = self.repo.scope_member_ids(index_ids=[m["scope_id"] for m in matched])
                routing = {"mode": "scoped",
                           "matched_indexes": [
                               {"index_id": m["scope_id"], "index": m["title"],
                                "score": round(m["similarity"], 4)} for m in matched]}
            else:
                dom = self.repo.rank_scopes(q_emb, kind="domain", limit=1)
                if dom and dom[0]["similarity"] >= route_threshold:
                    node_ids = self.repo.scope_member_ids(domain_ids=[dom[0]["scope_id"]])
                    routing = {"mode": "scoped",
                               "matched_domain": {"domain_id": dom[0]["scope_id"],
                                                  "domain": dom[0]["title"],
                                                  "score": round(dom[0]["similarity"], 4)}}
                else:
                    routing = {"mode": "global_fallback", "reason": "no scope over threshold",
                               "matched_indexes": []}

        results = self._search_chunks(query, node_ids, k, mode, rerank_candidates, q_emb=q_emb)

        # Global safety net: a scoped search that comes back too thin re-runs unscoped.
        if node_ids is not None and len(results) < k_min:
            results = self._search_chunks(query, None, k, mode, rerank_candidates, q_emb=q_emb)
            routing = {**routing, "mode": "global_fallback",
                       "reason": f"scoped hits < k_min ({k_min})"}

        # Annotate each hit with the index/domain it came from.
        scopes = self.repo.node_scopes([r["node_id"] for r in results])
        for r in results:
            r["scope"] = scopes.get(r["node_id"], {})
        related = self._expand_related(
            results, enabled=expand_related,
            per_hit=related_per_hit, min_confidence=related_min_confidence)
        return {"results": results, "related": related, "routing": routing}

    def _expand_related(
        self,
        results: list[dict],
        enabled: bool = True,
        per_hit: int = 6,
        min_confidence: float = 0.0,
    ) -> list[dict]:
        """1-hop association expansion from search hits. Mirrors the entity supernode
        cap: does not expand OUT of entity hits (they over-connect). Deduped by
        node_id, excludes nodes already in results, annotated with which hit each came
        from and the neighbor's own scope breadcrumb (may cross partitions)."""
        if not enabled or not results:
            return []
        seeds = [r["node_id"] for r in results if r.get("type") != "entity"]
        result_ids = {r["node_id"] for r in results}
        neigh = self.repo.neighbors(
            seeds, per_node=per_hit, min_confidence=min_confidence, exclude=result_ids
        )
        by_node: dict[str, dict] = {}
        for seed_id in seeds:
            for n in neigh.get(seed_id, []):
                item = {
                    "node_id": n["node_id"], "title": n["title"], "type": n["type"],
                    "rel": n["rel"], "confidence": n["confidence"], "from_node_id": seed_id,
                }
                prev = by_node.get(item["node_id"])
                if prev is None or item["confidence"] > prev["confidence"]:
                    by_node[item["node_id"]] = item
        items = list(by_node.values())
        scopes = self.repo.node_scopes([it["node_id"] for it in items])
        for it in items:
            it["scope"] = scopes.get(it["node_id"], {})
        items.sort(key=lambda x: x["confidence"], reverse=True)
        return items

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

    # ---- classification + scope summaries (V2) --------------------------

    def propose_classification(
        self, text: str, q_emb: list[float] | None = None, route_top_k: int = 2
    ) -> dict | None:
        """Score `text` against index summaries and propose a placement with alternatives.
        Returns None when there is nothing to route against (no embedded scopes) or the
        embedder is unavailable, so a node is simply created unclassified in that case."""
        try:
            q_emb = q_emb or self.provider.embed_query(text)
        except Exception:  # noqa: BLE001 - embedder down: no proposal, node -> inbox
            return None
        ranked = self.repo.rank_scopes(q_emb, kind="index", limit=max(3, route_top_k + 1))
        if not ranked:
            return None
        best = ranked[0]
        dom = self.repo.get_node(best["domain_id"]) if best.get("domain_id") else None
        alternatives: list[dict] = [
            {"index": r["title"], "index_id": r["scope_id"], "confidence": round(r["similarity"], 3)}
            for r in ranked[1:route_top_k + 1]
        ]
        alternatives += [{"option": "create_new_index"}, {"option": "create_new_domain"}]
        return {
            "proposed": {
                "domain": dom["title"] if dom else None,
                "domain_id": best.get("domain_id"),
                "index": best["title"],
                "index_id": best["scope_id"],
            },
            "confidence": round(best["similarity"], 3),
            "alternatives": alternatives,
        }

    def classify_new_node(
        self,
        node_id: str,
        text: str,
        q_emb: list[float] | None = None,
        autofile_threshold: float = 0.75,
        route_top_k: int = 2,
    ) -> dict:
        """Propose a placement for a freshly created node and either auto-file it (when
        the top index clears `autofile_threshold`) or stash the proposal on the node so
        it surfaces in the inbox. Returns the classification block for the response."""
        proposal = self.propose_classification(text, q_emb=q_emb, route_top_k=route_top_k)
        if proposal is None:
            return {"status": "unclassified"}
        if proposal["confidence"] >= autofile_threshold and proposal["proposed"].get("index_id"):
            placed = self.repo.classify_node(node_id, proposal["proposed"]["index_id"])
            return {"status": "filed", **proposal, "placement": placed}
        self.repo.update_node_meta(node_id, {"classification": proposal})
        return {"status": "proposed", **proposal}

    def _filed_result(self, node_id: str, index_id: str, score: float, reason: str) -> dict:
        """File a node into an index and build the auto-classify success payload."""
        self.repo.classify_node(node_id, index_id)
        crumb = self.repo.node_breadcrumb(node_id)
        return {"node_id": node_id, "filed": True, "index_id": index_id,
                "index": crumb.get("index"), "domain": crumb.get("domain"),
                "score": score, "reason": reason}

    def auto_classify_node(
        self, node_id: str, use_llm: bool = True, autofile_threshold: float = 0.75
    ) -> dict:
        """Auto-file one unclassified content node into its best index. An LLM chooses
        among the top vector-ranked candidate indexes; on any LLM failure it degrades to
        the vector path (file only when the top vector score clears autofile_threshold).
        An LLM pick is trusted even below the vector bar; an LLM that abstains blocks a
        weak-vector auto-file. Returns
        {"node_id", "filed", "index_id", "index", "domain", "score", "reason"}."""
        base = {"node_id": node_id, "filed": False, "index_id": None,
                "index": None, "domain": None, "score": 0.0, "reason": ""}
        node = self.repo.get_node(node_id)
        if node is None:
            return {**base, "reason": "node not found"}
        if node.get("node_kind") not in (None, "node"):
            return {**base, "reason": "not an unclassified content node"}
        if node.get("index_id"):
            return {**base, "reason": "already classified"}

        title = node.get("title") or ""
        snippet = (node.get("context_summary") or "").strip()[:1500]
        text = f"{title}\n\n{snippet}".strip()

        proposal = self.propose_classification(text, route_top_k=5)
        if proposal is None:
            scopes = self.repo.list_scopes()
            has_index = any(d.get("indexes") for d in scopes.get("domains", []))
            reason = "routing unavailable, needs review" if has_index else "no indexes exist yet"
            return {**base, "reason": reason}

        # Candidate indexes, highest vector similarity first (drop the create-new options).
        candidates = [{
            "index_id": proposal["proposed"]["index_id"],
            "index": proposal["proposed"]["index"],
            "confidence": float(proposal["confidence"]),
        }]
        for alt in proposal.get("alternatives", []):
            if alt.get("index_id"):
                candidates.append({"index_id": alt["index_id"], "index": alt["index"],
                                   "confidence": float(alt["confidence"])})
        top = candidates[0]

        # LLM pick among the listed candidates (best-effort; abstains with NONE).
        llm_pick: str | None = None
        llm_consulted = False
        if use_llm and candidates:
            for c in candidates:
                scope = self.repo.get_node(c["index_id"])
                c["summary"] = ((scope or {}).get("summary") or "")[:300]
            options = "\n".join(
                f"- id={c['index_id']} | {c['index']}: {c['summary'] or '(no summary)'}"
                for c in candidates
            )
            prompt = (
                "File this note into the single most relevant index, or reply NONE if "
                "none fit.\n\n"
                f"Note title: {title}\n"
                f"Note content:\n{snippet or '(no body)'}\n\n"
                "Candidate indexes (pick exactly one id, or NONE):\n"
                f"{options}\n\n"
                "Reply with ONLY the chosen id, or NONE."
            )
            try:
                reply = self.provider.complete(
                    prompt,
                    system="You file notes into the single best index of a knowledge base. "
                           "Answer with one id from the list, or NONE.",
                ).strip().lower()
                for c in candidates:
                    if c["index_id"].lower() in reply:
                        llm_pick = c["index_id"]
                        break
                llm_consulted = True
            except Exception:  # noqa: BLE001 - LLM down: fall back to the vector path
                llm_pick = None
                llm_consulted = False

        if llm_pick is not None:
            chosen = next(c for c in candidates if c["index_id"] == llm_pick)
            return self._filed_result(node_id, chosen["index_id"], chosen["confidence"],
                                      "LLM matched")
        if not llm_consulted and top["confidence"] >= autofile_threshold:
            return self._filed_result(node_id, top["index_id"], top["confidence"],
                                      "high vector confidence")
        return {**base, "score": top["confidence"], "reason": "no confident match, needs review"}

    def auto_classify_inbox(
        self, limit: int | None = None, use_llm: bool = True, autofile_threshold: float = 0.75,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict:
        """Auto-file the classification inbox. Runs auto_classify_node over each
        unclassified node and splits the outcomes. Returns
        {"filed_count", "skipped_count", "filed": [...], "skipped": [...]}.

        progress(done, total), when given, is called before each item and once more at the
        end, so a background caller can report how far the pass has got."""
        # limit=None means the whole inbox; resolve to the live count (SQLite rejects a
        # NULL LIMIT), so a single call files everything waiting.
        if limit is None:
            limit = self.repo.unclassified_count()
        items = self.repo.unclassified_nodes(limit=limit)
        total = len(items)
        filed: list[dict] = []
        skipped: list[dict] = []
        for i, it in enumerate(items):
            if progress is not None:
                progress(i, total)
            res = self.auto_classify_node(
                it["id"], use_llm=use_llm, autofile_threshold=autofile_threshold
            )
            (filed if res["filed"] else skipped).append(res)
        if progress is not None:
            progress(total, total)
        return {"filed_count": len(filed), "skipped_count": len(skipped),
                "filed": filed, "skipped": skipped}

    def read_node_full(self, node_id: str) -> dict | None:
        """Full-fidelity read of one node: its record, its complete chunk text
        (un-truncated), and, for a chronicle, its raw conversation turns. This is the
        drill-down the summary-first retrieval path points at when a distilled summary is
        too thin. It embeds nothing and adds no compute; it returns what the store already
        holds. None when the node does not exist."""
        node = self.repo.get_node(node_id)
        if node is None:
            return None
        return {
            "node": node,
            "chunks": self.repo.node_chunks(node_id),
            "raw_turns": self.repo.get_raw_turns(node_id),
        }

    def refresh_summary(self, scope_id: str, summary_text: str | None = None) -> dict:
        """Regenerate (or accept a client-supplied) scope summary, embed it, store it,
        and stamp the refresh time. Client-generated text is preferred; when omitted the
        server builds one from member titles/chunks (LLM if available, else a heuristic)."""
        scope = self.repo.get_scope(scope_id)
        if scope is None:
            return {"error": f"not a scope: {scope_id}"}
        text = (summary_text or "").strip() or self._generate_scope_summary(scope_id)
        embedding = None
        try:
            embedding = self.provider.embed(text)
        except Exception:  # noqa: BLE001 - summary still stored, just not routable yet
            embedding = None
        self.repo.set_scope_summary(scope_id, text, embedding)
        return {"scope_id": scope_id, "summary": text, "embedded": embedding is not None}

    def _generate_scope_summary(self, scope_id: str) -> str:
        """A routing summary from a scope's members. Tries the LLM; falls back to a
        title-based heuristic so this never hard-depends on a completion provider."""
        sample = self.repo.scope_sample(scope_id)
        titles = sample.get("titles", [])
        heuristic = (
            f"{sample.get('title')}: covers {', '.join(titles[:8])}."
            if titles else f"{sample.get('title')}: (no members yet)."
        )
        chunks = sample.get("chunks", [])[:5]
        prompt = (
            "Write a 3 to 6 sentence summary of this knowledge partition: what lives "
            "here, its key themes, and representative entities. Output only the summary.\n\n"
            f"Partition: {sample.get('title')}\n"
            "Member titles:\n" + "\n".join(f"- {t}" for t in titles[:20])
        )
        if chunks:
            prompt += "\n\nSample content:\n" + "\n---\n".join(chunks)
        try:
            out = self.provider.complete(
                prompt, system="You write concise routing summaries for a knowledge base partition."
            ).strip()
            return out or heuristic
        except Exception:  # noqa: BLE001 - no LLM: heuristic summary is enough to route
            return heuristic

    # ---- write path: documents -----------------------------------------

    def ingest_document(
        self,
        source: str,
        project: str | None = None,
        title: str | None = None,
        extra_meta: dict | None = None,
        classify: bool = True,
        autofile_threshold: float = 0.75,
        route_top_k: int = 2,
    ) -> dict:
        """Convert source to markdown, chunk, embed, and write node + chunks + vectors.
        Links the document to a project when given. When `classify` is on, routes the
        document into the taxonomy (auto-file or inbox proposal). Returns the node id,
        chunk count, and a classification block.
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
        result = {"node_id": node_id, "title": title, "chunks": len(chunks)}
        if classify:
            routing_text = f"{title}\n\n{markdown[:1500]}"
            result["classification"] = self.classify_new_node(
                node_id, routing_text,
                autofile_threshold=autofile_threshold, route_top_k=route_top_k,
            )
        return result
