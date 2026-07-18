"""Runtime configuration, read from the environment (GRIMOIRE_ prefix) or a .env file.

Components accept explicit arguments (db_path, provider name) so tests can override
without touching this global. `settings` is just the default the app entrypoints use.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


def _resolve_wsl_ollama_url() -> str:
    """Resolve the Windows-host Ollama URL from inside WSL2 via the default route.

    WSL2 output looks like: "default via 172.x.x.1 dev eth0 ...". Falls back to
    localhost on any failure (command missing, no match, unexpected output).
    """
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout
        match = re.search(r"default via (\S+)", out)
        if match:
            return f"http://{match.group(1)}:11434"
    except Exception:
        pass
    return _DEFAULT_OLLAMA_URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRIMOIRE_", env_file=".env", extra="ignore")

    # Store
    db_path: Path = Path("data/grimoire.db")

    # Provider interface selection: 'ollama' (real local) or 'fake' (offline, deterministic)
    provider: str = "ollama"

    # Ollama. "auto" (default) resolves the WSL2 host gateway at startup; an explicit
    # URL passes through untouched.
    ollama_url: str = "auto"
    embed_model: str = "nomic-embed-text"
    llm_model: str = "llama3.2"

    @model_validator(mode="after")
    def _resolve_ollama_url(self) -> "Settings":
        if self.ollama_url in ("", "auto"):
            self.ollama_url = _resolve_wsl_ollama_url()
        return self

    # Groq (optional). When a key is set, completion uses Groq first and falls back to
    # Ollama on rate-limit/timeout. Embeddings always stay on Ollama (Groq has none).
    groq_api_key: str = ""
    groq_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"

    # Embedding dimensions. Must match the vec0 schema (chunk_vectors.embedding float[768]).
    embed_dim: int = 768

    # --- Re-ranker (optional second-stage retrieval) ---
    # After bi-encoder recall + recency scoring, a LOCAL ONNX cross-encoder (via fastembed,
    # CPU-only, no torch/GPU) re-scores the top candidates for precision. Best-effort: any
    # failure falls back to the bi-encoder order. Default model ~240 MB RAM, loaded lazily
    # on first query. Set rerank_enabled=false to disable, or shrink rerank_candidates.
    rerank_enabled: bool = True
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = 25

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

    # Bearer token required on write-capable REST routes (/api/capture and every
    # POST/PUT/PATCH/DELETE). Empty = no check (local only). Set it before exposing
    # the API beyond localhost.
    api_token: str = ""

    # Extra browser origins allowed to call the REST API (comma-separated),
    # e.g. "https://grimoire.aquryu.space". localhost dev origins are always allowed.
    public_origins: str = ""


settings = Settings()
