"""The provider interface: the ONLY seam through which embeddings and LLM calls flow.

Hard rule (ARCHITECTURE / CLAUDE.md): no other module references a vendor or a model
name directly. Swapping embedding models or LLM vendors is a config change behind this
interface, not a rewrite. This is the data-side insurance the re-embedding routine
relies on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Provider(ABC):
    """Embeddings + text completion. Implementations bind to a concrete vendor/model."""

    @property
    @abstractmethod
    def embed_dim(self) -> int:
        """Dimension of vectors this provider emits. Must match the store schema."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed one piece of text into an embed_dim-length vector."""

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch. Default loops; override if the backend supports batching."""
        return [self.embed(t) for t in texts]

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """Single-shot text completion (used for distillation/compaction)."""
