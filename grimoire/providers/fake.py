"""Deterministic offline provider for tests and CI.

No network, no model download. embed() is a hash-expanded unit vector: stable for a
given text, correct length, valid for exercising the store's KNN mechanics. It is NOT
semantically meaningful, so it proves the plumbing (Phase 0), never retrieval quality
(that needs the real Ollama provider, verified in Phase 1).
"""

from __future__ import annotations

import hashlib
import math

from grimoire.providers.base import Provider


class FakeProvider(Provider):
    def __init__(self, embed_dim: int = 768) -> None:
        self._embed_dim = embed_dim

    @property
    def embed_dim(self) -> int:
        return self._embed_dim

    def embed(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        vals: list[float] = []
        counter = 0
        while len(vals) < self._embed_dim:
            block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for i in range(0, len(block), 4):
                if len(vals) >= self._embed_dim:
                    break
                n = int.from_bytes(block[i:i + 4], "big")
                vals.append((n / 2**32) * 2 - 1)  # map to [-1, 1)
            counter += 1
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]

    def complete(self, prompt: str, system: str | None = None) -> str:
        digest = hashlib.sha256((system or "") .encode() + prompt.encode()).hexdigest()[:12]
        return f"[fake completion {digest} for {len(prompt)} chars]"
