"""Local cross-encoder re-ranker: the optional second stage of retrieval.

The bi-encoder (embeddings) recalls broadly by cosine similarity; a cross-encoder scores
each query-passage PAIR jointly, which is far more precise but too heavy to run over the
whole store. So retrieval recalls the top candidates cheaply, then re-ranks just those.

This is a small ONNX model via fastembed (ms-marco MiniLM by default, ~240 MB RAM,
CPU-only, no torch, no GPU) so it runs on a modest VPS entirely offline. It is a separate
seam from the Provider (which is embeddings + LLM completion): a re-ranker is neither.

The model is loaded lazily on first use, so importing this module — and booting the app —
never forces a model download or a 240 MB allocation. If fastembed is not installed or the
model can't load, the caller (service.retrieve) catches it and falls back to the bi-encoder
order, so retrieval never depends on the re-ranker being available.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


class Reranker(ABC):
    @abstractmethod
    def scores(self, query: str, passages: list[str]) -> list[float]:
        """Relevance score per passage (higher = more relevant), aligned to input order."""


class FastembedReranker(Reranker):
    """fastembed TextCrossEncoder (ONNX Runtime, CPU). Lazily loads the model on first call."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._encoder = None  # loaded on first scores() call

    def scores(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        if self._encoder is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._encoder = TextCrossEncoder(model_name=self._model_name)
        return [float(s) for s in self._encoder.rerank(query, passages)]


def get_reranker(enabled: bool = True, model_name: str = DEFAULT_MODEL) -> Reranker | None:
    """Build the configured re-ranker, or None when disabled. Construction is cheap (the
    model loads lazily), so this is safe to call once at startup."""
    if not enabled:
        return None
    return FastembedReranker(model_name)
