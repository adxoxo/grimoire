"""Ollama-backed provider: local 768-dim embeddings + local completion.

The locked default. Reached only through the Provider interface, never imported by
name elsewhere.
"""

from __future__ import annotations

import httpx

from grimoire.providers.base import Provider


class OllamaProvider(Provider):
    def __init__(
        self,
        url: str = "http://localhost:11434",
        embed_model: str = "nomic-embed-text",
        llm_model: str = "llama3.2",
        embed_dim: int = 768,
        timeout: float = 120.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._embed_model = embed_model
        self._llm_model = llm_model
        self._embed_dim = embed_dim
        # nomic-embed-text is asymmetric: it needs task prefixes on inputs. Other
        # models (e.g. bge) use their own scheme, so only prefix when running nomic.
        self._nomic = "nomic" in embed_model.lower()
        self._client = httpx.Client(base_url=self._url, timeout=timeout)

    @property
    def embed_dim(self) -> int:
        return self._embed_dim

    def embed(self, text: str) -> list[float]:
        return self._embed(f"search_document: {text}" if self._nomic else text)

    def embed_query(self, text: str) -> list[float]:
        return self._embed(f"search_query: {text}" if self._nomic else text)

    def _embed(self, text: str) -> list[float]:
        resp = self._client.post("/api/embeddings", json={"model": self._embed_model, "prompt": text})
        resp.raise_for_status()
        vec = resp.json()["embedding"]
        if len(vec) != self._embed_dim:
            raise ValueError(
                f"{self._embed_model} returned {len(vec)} dims, expected {self._embed_dim}; "
                "embed_dim and the store schema must agree"
            )
        return vec

    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        body: dict[str, object] = {"model": self._llm_model, "prompt": prompt, "stream": False}
        if system is not None:
            body["system"] = system
        if json_mode:
            body["format"] = "json"
        resp = self._client.post("/api/generate", json=body)
        resp.raise_for_status()
        return resp.json()["response"]

    def close(self) -> None:
        self._client.close()
