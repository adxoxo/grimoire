"""Re-embedding routine. Stubbed in Phase 0, promoted to a full scheduled job in
Phase 5. It exists from day one so that changing embedding models later is a routine
afternoon, not a rewrite.

It walks every chunk and re-embeds it through the provider interface, swapping the new
vector in. The provider interface keeps calling code stable; this routine handles the
data-side migration.
"""

from __future__ import annotations

from typing import Callable

from grimoire.providers.base import Provider
from grimoire.store import Repository


def reembed_all(
    repo: Repository,
    provider: Provider,
    progress: Callable[[int, dict], None] | None = None,
) -> dict[str, int]:
    """Re-embed every chunk and every scope routing summary. Returns
    {"chunks": <n>, "scopes": <m>}.

    Phase 0 limitation: this re-embeds in place at the current dimension. Changing the
    dimension also requires recreating the vec0 table (float[N]) and doing the swap
    transactionally; that is Phase 5's job. Guarded here so the mismatch is loud.

    A model change also invalidates the scope_vectors that routing depends on, so those
    are re-embedded here too (from each scope's stored summary); otherwise routing
    silently breaks until each scope is manually refreshed.
    """
    if provider.embed_dim != repo.embed_dim:
        raise ValueError(
            f"provider emits {provider.embed_dim} dims but the store expects "
            f"{repo.embed_dim}. Changing dimensions requires recreating the vector "
            "table (Phase 5 re-embedding job), not just re-running this."
        )
    count = 0
    for chunk in repo.iter_chunks():
        repo.update_vector(chunk["id"], provider.embed(chunk["content"]))
        count += 1
        if progress is not None:
            progress(count, chunk)
    scope_count = 0
    scopes = repo.list_scopes()
    for domain in scopes.get("domains", []):
        for scope in [domain, *domain.get("indexes", [])]:
            summary = (scope.get("summary") or "").strip()
            if not summary:
                continue
            repo.set_scope_summary(scope["id"], summary, embedding=provider.embed(summary))
            scope_count += 1
    return {"chunks": count, "scopes": scope_count}
