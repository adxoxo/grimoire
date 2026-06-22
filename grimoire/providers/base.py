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
        """Embed a document/passage into an embed_dim-length vector."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query. Defaults to embed(); asymmetric models override it
        (e.g. nomic-embed-text needs distinct query/document prefixes)."""
        return self.embed(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents. Default loops; override if the backend batches."""
        return [self.embed(t) for t in texts]

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        """Single-shot text completion. json_mode forces syntactically valid JSON output
        (used by distillation), where the backend supports it."""
