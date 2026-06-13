"""Provider package + factory. Callers ask for a provider by name; nothing else
constructs a vendor implementation directly.
"""

from __future__ import annotations

from grimoire.config import Settings, settings
from grimoire.providers.base import Provider
from grimoire.providers.fake import FakeProvider
from grimoire.providers.ollama import OllamaProvider

__all__ = ["Provider", "OllamaProvider", "FakeProvider", "get_provider"]


def get_provider(name: str | None = None, config: Settings = settings) -> Provider:
    name = name or config.provider
    if name == "ollama":
        return OllamaProvider(
            url=config.ollama_url,
            embed_model=config.embed_model,
            llm_model=config.llm_model,
            embed_dim=config.embed_dim,
        )
    if name == "fake":
        return FakeProvider(embed_dim=config.embed_dim)
    raise ValueError(f"unknown provider: {name!r} (expected 'ollama' or 'fake')")
