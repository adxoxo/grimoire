"""Provider package + factory. Callers ask for a provider by name; nothing else
constructs a vendor implementation directly.
"""

from __future__ import annotations

from grimoire.config import Settings, settings
from grimoire.providers.base import Provider
from grimoire.providers.fake import FakeProvider
from grimoire.providers.fallback import FallbackProvider
from grimoire.providers.groq import GroqProvider
from grimoire.providers.ollama import OllamaProvider

__all__ = ["Provider", "OllamaProvider", "FakeProvider", "GroqProvider", "FallbackProvider", "get_provider"]


def get_provider(name: str | None = None, config: Settings = settings) -> Provider:
    name = name or config.provider
    if name == "fake":
        return FakeProvider(embed_dim=config.embed_dim)
    if name == "ollama":
        ollama = OllamaProvider(
            url=config.ollama_url,
            embed_model=config.embed_model,
            llm_model=config.llm_model,
            embed_dim=config.embed_dim,
        )
        # With a DeepSeek and/or Groq key, route completion DeepSeek -> Groq -> Ollama;
        # embeddings stay on Ollama. DeepSeek reuses the OpenAI-compatible Groq client.
        completers: list[Provider] = []
        if config.deepseek_api_key:
            completers.append(GroqProvider(
                api_key=config.deepseek_api_key,
                url=config.deepseek_url,
                model=config.deepseek_model,
                embed_dim=config.embed_dim,
            ))
        if config.groq_api_key:
            completers.append(GroqProvider(
                api_key=config.groq_api_key,
                url=config.groq_url,
                model=config.groq_model,
                embed_dim=config.embed_dim,
            ))
        if completers:
            return FallbackProvider(embedder=ollama, completers=[*completers, ollama])
        return ollama
    raise ValueError(f"unknown provider: {name!r} (expected 'ollama' or 'fake')")
