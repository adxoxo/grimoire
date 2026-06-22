"""Fallback routing across providers. Embeddings always use the local embedder
(Ollama); completion tries each completer in order until one succeeds, so Groq can be
primary with Ollama as the automatic backup on rate-limit/timeout/outage.
"""

from __future__ import annotations

import sys

from grimoire.providers.base import Provider


class FallbackProvider(Provider):
    def __init__(self, embedder: Provider, completers: list[Provider]) -> None:
        if not completers:
            raise ValueError("FallbackProvider needs at least one completer")
        self._embedder = embedder
        self._completers = completers

    @property
    def embed_dim(self) -> int:
        return self._embedder.embed_dim

    def embed(self, text: str) -> list[float]:
        return self._embedder.embed(text)

    def embed_query(self, text: str) -> list[float]:
        return self._embedder.embed_query(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed_many(texts)

    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        last_error: Exception | None = None
        for completer in self._completers:
            try:
                return completer.complete(prompt, system, json_mode=json_mode)
            except Exception as exc:  # noqa: BLE001 - any failure routes to the next provider
                last_error = exc
                sys.stderr.write(
                    f"[provider] {type(completer).__name__} completion failed ({exc}); falling back\n"
                )
        raise last_error if last_error else RuntimeError("no completer succeeded")
