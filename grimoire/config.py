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

    # Groq (optional). When a key is set, completion uses Groq first and falls back to
    # Ollama on rate-limit/timeout. Embeddings always stay on Ollama (Groq has none).
    groq_api_key: str = ""
    groq_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"

    # Embedding dimensions. Must match the vec0 schema (chunk_vectors.embedding float[768]).
    embed_dim: int = 768

    # --- Remote MCP hosting (optional) ---
    # stdio (default) = local subprocess launched per-agent by the MCP client.
    # http            = a long-running network daemon other agents reach by URL.
    mcp_transport: str = "stdio"
    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8730
    mcp_http_path: str = "/mcp"
    # Bearer token required on the HTTP MCP endpoint. Empty = no check (local only).
    # Always set this when exposing the server beyond localhost.
    mcp_token: str = ""

    # Extra browser origins allowed to call the REST API (comma-separated),
    # e.g. "https://grimoire.aquryu.space". localhost dev origins are always allowed.
    public_origins: str = ""


settings = Settings()
