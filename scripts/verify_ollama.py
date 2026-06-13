"""Verify the real Ollama embed (+ optional complete) round-trip through the provider
interface. This is the Phase 0 "verify embed round-trip" check against a live model.

Prereqs (no sudo needed, see README):
    ollama serve &                 # if not already running
    ollama pull nomic-embed-text
    .venv/bin/python scripts/verify_ollama.py
"""

from __future__ import annotations

from grimoire.providers import get_provider


def main() -> None:
    p = get_provider("ollama")

    vec = p.embed("the grimoire stores distilled knowledge linked to projects")
    print(f"embed: got {len(vec)} dims (expected {p.embed_dim})")
    assert len(vec) == p.embed_dim, "dimension mismatch: fix GRIMOIRE_EMBED_DIM or the model"
    print("embed round-trip: OK")

    # completion needs an LLM model pulled; report but do not hard-fail Phase 0 on it.
    try:
        out = p.complete("Reply with the single word: ok")
        print(f"complete round-trip: OK ({out[:60]!r})")
    except Exception as exc:  # noqa: BLE001 - informational only
        print(f"complete skipped (is GRIMOIRE_LLM_MODEL pulled?): {exc}")


if __name__ == "__main__":
    main()
