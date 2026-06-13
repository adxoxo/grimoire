"""Runtime configuration, read from the environment (GRIMOIRE_ prefix) or a .env file.

Components accept explicit arguments (db_path, provider name) so tests can override
without touching this global. `settings` is just the default the app entrypoints use.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRIMOIRE_", env_file=".env", extra="ignore")

    # Store
    db_path: Path = Path("data/grimoire.db")

    # Provider interface selection: 'ollama' (real local) or 'fake' (offline, deterministic)
    provider: str = "ollama"

    # Ollama
    ollama_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    llm_model: str = "llama3.2"

    # Embedding dimensions. Must match the vec0 schema (chunk_vectors.embedding float[768]).
    embed_dim: int = 768


settings = Settings()
