"""Auto-file gate picks an index by NUMBER, not by echoing a 32-char hex id.

Regression for the observed failure where a model chose the right index but mangled
one character of the opaque id (e.g. dropped a leading zero), so `id in reply` missed
and a correct pick was silently demoted to "needs review". Numbered options are
parseable even from the small Ollama fallback model, so a real pick is honoured.

FakeProvider embeddings are not semantic, so the two indexes are ranked deterministically
by embedding each index summary from the exact text the note builds (match ~1.0) versus an
unrelated string (near-orthogonal). Control flow is what these prove.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.providers.fake import FakeProvider
from grimoire.service import KnowledgeService
from grimoire.store import Repository


class ScriptedProvider(FakeProvider):
    """Fake embeddings + a scripted completion reply, to drive the LLM gate."""

    def __init__(self, reply: str) -> None:
        super().__init__()
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        return self.reply


class BrokenLLMProvider(FakeProvider):
    """Embeddings work, but completion raises (the provider is down)."""

    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        raise RuntimeError("llm unavailable")


# The note auto_classify_node scores is "{title}\n\n{context_summary}".
TITLE = "youtube thumbnails"
BODY = "how to design thumbnails that get clicks"
NOTE_TEXT = f"{TITLE}\n\n{BODY}"


def _seed(repo: Repository, provider: FakeProvider) -> tuple[str, str, str]:
    """Two ranked indexes (A matches the note, B does not) + one unclassified node.
    Returns (index_a, index_b, node_id)."""
    dom = repo.add_scope("domain", "Content")
    a = repo.add_scope("index", "YouTube", domain_id=dom)
    b = repo.add_scope("index", "Taxes", domain_id=dom)
    repo.set_scope_summary(a, "youtube", provider.embed(NOTE_TEXT))          # sim ~1.0 -> ranks #1
    repo.set_scope_summary(b, "taxes", provider.embed("quarterly tax deadlines"))  # unrelated -> #2
    nid = repo.add_node("memory", TITLE, context_summary=BODY)
    return a, b, nid


@pytest.fixture
def repo(tmp_path: Path):
    r = Repository(tmp_path / "g.db")
    yield r
    r.close()


def test_number_reply_files_the_chosen_candidate(repo):
    """reply "1" files into the top-ranked candidate (the whole point of the fix)."""
    prov = ScriptedProvider(reply="1")
    a, _b, nid = _seed(repo, prov)
    svc = KnowledgeService(repo, prov)
    res = svc.auto_classify_node(nid)
    assert res["filed"] is True
    assert res["index_id"] == a
    assert repo.get_node(nid)["index_id"] == a


def test_number_two_files_second_candidate(repo):
    """reply "2" files into the second candidate, not the first."""
    prov = ScriptedProvider(reply="2")
    _a, b, nid = _seed(repo, prov)
    svc = KnowledgeService(repo, prov)
    res = svc.auto_classify_node(nid)
    assert res["filed"] is True
    assert res["index_id"] == b


def test_none_reply_abstains(repo):
    """reply "NONE" leaves the node unclassified for human review."""
    prov = ScriptedProvider(reply="NONE")
    _a, _b, nid = _seed(repo, prov)
    svc = KnowledgeService(repo, prov)
    res = svc.auto_classify_node(nid)
    assert res["filed"] is False
    assert repo.get_node(nid)["index_id"] is None


def test_number_embedded_in_prose_is_parsed(repo):
    """A chatty reply like "I'd file this under 1)" still resolves to candidate 1."""
    prov = ScriptedProvider(reply="I'd file this under 1) YouTube.")
    a, _b, nid = _seed(repo, prov)
    svc = KnowledgeService(repo, prov)
    res = svc.auto_classify_node(nid)
    assert res["filed"] is True
    assert res["index_id"] == a


def test_out_of_range_number_abstains(repo):
    """A number with no matching candidate (e.g. "9") does not file into a wrong index."""
    prov = ScriptedProvider(reply="9")
    _a, _b, nid = _seed(repo, prov)
    svc = KnowledgeService(repo, prov)
    res = svc.auto_classify_node(nid)
    assert res["filed"] is False


def test_llm_failure_falls_back_to_high_vector_confidence(repo):
    """When the LLM is unreachable (not merely abstaining), a top vector score above the
    threshold still files, so a provider outage does not stall the whole inbox. This is
    the other half of the gate from the abstention case above."""
    prov = BrokenLLMProvider()
    a, _b, nid = _seed(repo, prov)  # index A summary == note text -> similarity ~1.0
    svc = KnowledgeService(repo, prov)
    res = svc.auto_classify_node(nid)
    assert res["filed"] is True
    assert res["index_id"] == a
    assert res["reason"] == "high vector confidence"
