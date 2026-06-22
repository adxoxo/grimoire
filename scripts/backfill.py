"""One-time history backfill: seed the store from a claude.ai data export.

Each conversation is distilled (the same call as live capture) into a chronicle dated
to the original conversation, linked to a project when its name is identifiable, else
parked in the "Unsorted" triage project. All backfilled nodes are unreviewed; skim the
review queue afterwards. Distillation is one cheap LLM call per conversation.

    .venv/bin/python scripts/backfill.py path/to/conversations.json

Export: claude.ai Settings -> Privacy -> Export data; the emailed zip has conversations.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from grimoire.config import settings
from grimoire.distill import capture_session
from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository

# Projects whose names, if they appear in a conversation, claim it. Extend as needed.
KNOWN_PROJECTS = ["ROAR", "FTV Mushrooms", "GoatedTracking", "Grimoire"]
TRIAGE_PROJECT = "Unsorted"


def _turns(conv: dict) -> list[dict]:
    messages = conv.get("chat_messages") or conv.get("messages") or []
    turns = []
    for m in messages:
        sender = m.get("sender") or m.get("role") or "user"
        role = "user" if sender in ("human", "user") else "assistant"
        text = m.get("text")
        if not text and isinstance(m.get("content"), list):
            text = " ".join(p.get("text", "") for p in m["content"] if isinstance(p, dict))
        if text:
            turns.append({"role": role, "content": text})
    return turns


def _identify_project(conv: dict, turns: list[dict]) -> str:
    haystack = (conv.get("name") or conv.get("title") or "").lower()
    haystack += " " + " ".join(t["content"] for t in turns).lower()
    for name in KNOWN_PROJECTS:
        if name.lower() in haystack:
            return name
    return TRIAGE_PROJECT


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: backfill.py path/to/conversations.json")
        raise SystemExit(2)
    export = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    repo = Repository(settings.db_path)
    svc = KnowledgeService(repo, get_provider())
    for name in [*KNOWN_PROJECTS, TRIAGE_PROJECT]:
        repo.upsert_project(name)

    counts: dict[str, int] = {}
    for i, conv in enumerate(export, 1):
        turns = _turns(conv)
        if not turns:
            continue
        project = _identify_project(conv, turns)
        created_at = conv.get("created_at") or conv.get("created")
        capture_session(svc, project, turns, created_at=created_at)
        counts[project] = counts.get(project, 0) + 1
        print(f"  [{i}] -> {project}  ({conv.get('name') or conv.get('title') or 'untitled'})")

    repo.close()
    print(f"\nbackfilled {sum(counts.values())} conversations: {counts}")
    print("all unreviewed; triage the review queue and fix any mislinked projects.")


if __name__ == "__main__":
    main()
