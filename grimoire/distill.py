"""Conversation distillation: one cheap LLM call turning raw session turns into a
structured memory (summary, decisions, open questions, entities), then writing it as a
chronicle. Used by live capture (Phase 4 webhook) and the history backfill (Phase 3b).
"""

from __future__ import annotations

import json
import re

from grimoire.providers.base import Provider
from grimoire.service import KnowledgeService

_SYSTEM = (
    "You distil a session or document into a compact JSON record for a holistic second "
    "brain. Content may be technical (code, configs, architecture) or personal (life "
    "history, goals, emotions, relationships, writing voice and rules). Treat personal, "
    "emotional, and relational information with the SAME priority and care as technical "
    "detail; never filter it out or downrank it. Output ONLY JSON, no prose."
)

_PROMPT = """Read the content below and return a single JSON object with exactly these keys:
- "summary": 2 to 5 sentences capturing what matters - decisions, outcomes, personal context, feelings, history, or rules. Not a transcript. Preserve emotional and relational nuance when present.
- "decisions": array of decisions, commitments, or stated preferences and rules (may be empty).
- "open_questions": array of unresolved questions or tensions (may be empty).
- "entities": array of named things worth remembering across sessions - people, relationships, places, organisations, APIs, tools, services, projects.

Map personal and non-technical information as expertly and completely as technical information.

Content:
{conversation}

JSON:"""


def _format_turns(turns: list[dict]) -> str:
    return "\n".join(f"{t.get('role', '?')}: {t.get('content', '')}" for t in turns)


def _parse_json(text: str) -> dict | None:
    # Models often wrap JSON in ``` or ```json fences; strip them, then take the object.
    cleaned = re.sub(r"```(?:json)?", "", text)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def distill_session(provider: Provider, turns: list[dict]) -> dict:
    """One LLM call -> structured record. Degrades to a raw-text summary if the model
    does not return parseable JSON, so capture never hard-fails on a bad completion.
    """
    conversation = _format_turns(turns)
    raw = provider.complete(_PROMPT.format(conversation=conversation), system=_SYSTEM, json_mode=True)
    data = _parse_json(raw) or {}
    summary = str(data.get("summary") or "").strip()
    if not summary:
        summary = conversation[:500].strip() or "Session with no distilled summary."
    return {
        "summary": summary,
        "decisions": _as_str_list(data.get("decisions")),
        "open_questions": _as_str_list(data.get("open_questions")),
        "entities": _as_str_list(data.get("entities")),
    }


def capture_session(
    service: KnowledgeService,
    project: str,
    turns: list[dict],
    created_at: str | None = None,
) -> dict:
    """Distil a session and write it as a chronicle: summary embedded and retrievable,
    raw turns kept in the raw layer, open questions in meta, status unreviewed.
    """
    distilled = distill_session(service.provider, turns)
    mem_id = service.repo.write_memory(
        project=project,
        summary=distilled["summary"],
        decisions=distilled["decisions"],
        entities=distilled["entities"],
        raw_turns=turns,
        summary_embedding=service.provider.embed(distilled["summary"]),
        created_at=created_at,
        extra_meta={"open_questions": distilled["open_questions"]},
    )
    return {"node_id": mem_id, **distilled}
