"""Groq-backed completion (OpenAI-compatible endpoint), used as the primary for heavy
reasoning. Groq offers no embedding API, so embed() is unsupported here; the fallback
provider routes embeddings to Ollama.
"""

from __future__ import annotations

import httpx

from grimoire.providers.base import Provider


class GroqError(Exception):
    """Raised on a Groq failure that should trigger fallback (rate-limit, timeout, etc.)."""


class GroqProvider(Provider):
    def __init__(
        self,
        api_key: str,
        url: str = "https://api.groq.com/openai/v1",
        model: str = "llama-3.3-70b-versatile",
        embed_dim: int = 768,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._embed_dim = embed_dim
        self._client = httpx.Client(
            base_url=url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    @property
    def embed_dim(self) -> int:
        return self._embed_dim

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError("Groq has no embeddings API; embeddings run on Ollama")

    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        messages = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, object] = {"model": self._model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.post("/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise GroqError(f"groq timeout: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            # Rate-limit and server errors should fall back; surface others too.
            raise GroqError(f"groq http {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise GroqError(f"groq error: {exc}") from exc
        return resp.json()["choices"][0]["message"]["content"]
