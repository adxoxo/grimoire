#!/usr/bin/env python3
"""Retrieval benchmark harness (Phase 8).

Compares grimoire retrieve() -- hybrid and vector modes, when the running
codebase supports them -- against a grep/term-frequency baseline over a
markdown export, on a hand-graded question set (benchmarks/questions.jsonl).

Read-only by construction: the live store (data/grimoire.db) is snapshotted to
a temp file with Repository.backup() before anything else runs, and every
retrieve/export/grep call below operates on that snapshot, never the original.

Run:
    .venv/bin/python scripts/benchmark.py
    .venv/bin/python scripts/benchmark.py --k 5 10 --out BENCHMARKS.md
"""

from __future__ import annotations

import argparse
import inspect
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json  # noqa: E402

from grimoire.config import settings  # noqa: E402
from grimoire.providers import get_provider  # noqa: E402
from grimoire.providers.fake import FakeProvider  # noqa: E402
from grimoire.rerank import get_reranker  # noqa: E402
from grimoire.service import KnowledgeService  # noqa: E402
from grimoire.store import Repository  # noqa: E402

DEFAULT_K = (5, 10)
STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "but", "by", "did", "do",
    "does", "for", "from", "has", "have", "how", "in", "into", "is", "it",
    "its", "of", "on", "or", "per", "que", "such", "that", "the", "their",
    "this", "to", "was", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "you", "your",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9_./@$-]{3,}")


# ---- store snapshot (never touches the live file) -------------------------


def snapshot_db(live_db: Path, dest: Path) -> None:
    """Copy the store via Repository.backup(). Opens live_db, writes to dest only."""
    repo = Repository(live_db)
    try:
        repo.backup(dest)
    finally:
        repo.close()


# ---- questions --------------------------------------------------------------


def load_questions(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


# ---- provider selection: real first, fake fallback (loud) ------------------


def resolve_provider():
    """Try the configured provider with one cheap embed call; fall back to fake.
    Returns (provider, name, is_fake)."""
    configured = settings.provider
    if configured == "fake":
        return FakeProvider(embed_dim=settings.embed_dim), "fake", True
    try:
        from grimoire.providers.ollama import verify_reachable

        verify_reachable(settings.ollama_url, timeout=3.0)
        provider = get_provider(configured)
        provider.embed_query("healthcheck")  # cheap real call; surfaces model errors early
        return provider, configured, False
    except Exception as exc:  # noqa: BLE001 - any failure means "use fake instead"
        print(
            f"[benchmark] real provider '{configured}' unreachable/failed ({exc}); "
            "falling back to the fake provider",
            file=sys.stderr,
        )
        return FakeProvider(embed_dim=settings.embed_dim), "fake", True


# ---- grimoire retrieve backends (hybrid / vector) ---------------------------


def retrieve_supports_mode() -> bool:
    try:
        sig = inspect.signature(KnowledgeService.retrieve)
        return "mode" in sig.parameters
    except (TypeError, ValueError):
        return False


def run_grimoire_backend(
    service: KnowledgeService, mode: str | None, query: str, k: int
) -> tuple[list[str] | None, str | None]:
    """Returns (ranked unique node_ids best-first, error) for one query."""
    kwargs: dict = {"k": k}
    if mode is not None:
        kwargs["mode"] = mode
    try:
        hits = service.retrieve(query, **kwargs)
    except Exception as exc:  # noqa: BLE001 - a failed query just scores as a miss
        return None, str(exc)
    ranked: list[str] = []
    seen: set[str] = set()
    for h in hits:
        nid = h.get("node_id")
        if nid and nid not in seen:
            seen.add(nid)
            ranked.append(nid)
    return ranked, None


# ---- grep / term-frequency baseline -----------------------------------------


def build_export_corpus(snapshot_path: Path, export_dir: Path) -> dict[Path, str] | None:
    """Export the snapshot to markdown (grimoire.export, imported lazily) and map
    each file back to its node id via the grimoire_id frontmatter. Returns None
    if the export module isn't available yet (parallel workstream not landed)."""
    try:
        from grimoire.export import export_store  # type: ignore
    except ImportError:
        return None
    repo = Repository(snapshot_path)
    try:
        export_store(repo, export_dir)
    finally:
        repo.close()
    mapping: dict[Path, str] = {}
    for md in export_dir.rglob("*.md"):
        text = md.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"grimoire_id:\s*[\"']?([A-Za-z0-9_-]+)", text)
        if m:
            mapping[md] = m.group(1)
    return mapping


def tokenize(query: str) -> list[str]:
    terms = [t.lower() for t in TOKEN_RE.findall(query)]
    return [t for t in terms if t not in STOPWORDS]


def grep_rank(
    query: str, mapping: dict[Path, str], export_dir: Path, has_rg: bool
) -> list[str]:
    """Rank exported files by naive term frequency, then map to unique node ids."""
    terms = tokenize(query)
    if not terms:
        return []
    scores: Counter[Path] = Counter()
    if has_rg:
        for term in terms:
            try:
                proc = subprocess.run(
                    ["rg", "-i", "-c", "-F", "--", term, str(export_dir)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:  # noqa: BLE001 - a failed rg call just skips this term
                continue
            for line in proc.stdout.splitlines():
                path_str, sep, count_str = line.rpartition(":")
                if not sep:
                    continue
                try:
                    scores[Path(path_str)] += int(count_str)
                except ValueError:
                    continue
    else:
        for md in mapping:
            text = md.read_text(encoding="utf-8", errors="replace").lower()
            total = sum(text.count(term) for term in terms)
            if total:
                scores[md] = total
    ranked: list[str] = []
    seen: set[str] = set()
    for path, _ in scores.most_common():
        nid = mapping.get(path)
        if nid and nid not in seen:
            seen.add(nid)
            ranked.append(nid)
    return ranked


# ---- metrics ------------------------------------------------------------


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    return 1.0 if any(n in gold for n in ranked[:k]) else 0.0


def mrr(ranked: list[str], gold: set[str]) -> float:
    for i, n in enumerate(ranked, start=1):
        if n in gold:
            return 1.0 / i
    return 0.0


def score_backend(
    rankings: list[list[str] | None], questions: list[dict], k_values: list[int]
) -> dict[str, float]:
    row: dict[str, float] = {}
    scored = [(q, r) for q, r in zip(questions, rankings) if r is not None]
    n = len(scored)
    for k in k_values:
        row[f"recall@{k}"] = (
            sum(recall_at_k(r, set(q["gold_node_ids"]), k) for q, r in scored) / n if n else 0.0
        )
    row["mrr"] = sum(mrr(r, set(q["gold_node_ids"])) for q, r in scored) / n if n else 0.0
    row["scored_questions"] = n
    return row


# ---- report ------------------------------------------------------------


BACKEND_LABELS = {
    "hybrid": "grimoire retrieve (mode=hybrid, BM25+vector RRF)",
    "vector": "grimoire retrieve (mode=vector)",
    "grep": "grep / term-frequency baseline",
}


def write_report(
    out_path: Path,
    metrics: dict[str, dict[str, float]],
    k_values: list[int],
    questions_path: Path,
    n_questions: int,
    counts: dict[str, int],
    provider_name: str,
    is_fake: bool,
    rerank_enabled: bool,
    pending: list[str],
    has_rg: bool,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append("# Grimoire retrieval benchmark")
    lines.append("")
    lines.append(f"Generated {now} by `scripts/benchmark.py`.")
    lines.append("")

    if is_fake:
        lines.append(
            "> **Caveat: fake embedding provider.** The real provider "
            f"(`{settings.provider}`) was unreachable or failed at run time, so this run "
            "fell back to `FakeProvider` (a deterministic hash-expanded vector, not a "
            "trained embedding model). Any recall/MRR numbers for the vector or hybrid "
            "backends below are **mechanics-only** -- they prove the retrieval "
            "pipeline runs end to end, not that it retrieves anything meaningful. "
            "Re-run with Ollama reachable for real scores."
        )
        lines.append("")

    if pending:
        lines.append("> **Pending backends / caveats:**")
        for p in pending:
            lines.append(f"> - {p}")
        lines.append("")

    lines.append("## Results")
    lines.append("")
    header = ["backend"] + [f"recall@{k}" for k in k_values] + ["mrr", "scored questions"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for backend, row in metrics.items():
        label = BACKEND_LABELS.get(backend, backend)
        cells = [label]
        for k in k_values:
            cells.append(f"{row.get(f'recall@{k}', 0.0):.2f}")
        cells.append(f"{row.get('mrr', 0.0):.2f}")
        cells.append(str(row.get("scored_questions", 0)))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Run configuration")
    lines.append("")
    lines.append(f"- Questions: {n_questions} (from `{questions_path}`)")
    lines.append(f"- k values: {', '.join(str(k) for k in k_values)}")
    lines.append(f"- Embedding provider: `{provider_name}`{' (fallback, see caveat above)' if is_fake else ''}")
    lines.append(f"- Re-ranker (cross-encoder second stage): {'enabled' if rerank_enabled else 'disabled'}")
    lines.append(f"- ripgrep available for the grep baseline: {'yes' if has_rg else 'no (pure-python term scan used)'}")
    lines.append(
        "- Store snapshot: "
        + ", ".join(f"{k}={v}" for k, v in counts.items())
    )
    lines.append(f"- Date: {now}")
    lines.append("")

    lines.append("## How to re-run")
    lines.append("")
    lines.append("```bash")
    lines.append(".venv/bin/python scripts/benchmark.py \\")
    lines.append("  --questions benchmarks/questions.jsonl \\")
    lines.append("  --k 5 10 \\")
    lines.append("  --out BENCHMARKS.md")
    lines.append("```")
    lines.append("")
    lines.append(
        "The script always snapshots `data/grimoire.db` (or `--db`) to a temp file "
        "first via `Repository.backup()` and only ever reads/queries that snapshot -- "
        "the live store is never opened for writes."
    )
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- A hit = a returned chunk/file whose `node_id` matches one of a question's "
        "`gold_node_ids`. Metrics are computed over unique node ids in rank order "
        "(duplicate chunks from the same node collapse to their first, best rank)."
    )
    lines.append(
        "- If the grep baseline wins on any metric, that is signal about the "
        "current retrieval quality, not a bug in the harness -- it is kept in the "
        "table either way."
    )
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---- main ------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default=None,
        help="Source store to snapshot from (default: settings.db_path / data/grimoire.db). "
        "Never written to -- a temp-file backup is queried instead.",
    )
    parser.add_argument(
        "--questions", default=str(ROOT / "benchmarks" / "questions.jsonl"),
    )
    parser.add_argument("--k", type=int, nargs="+", default=list(DEFAULT_K))
    parser.add_argument("--out", default=str(ROOT / "BENCHMARKS.md"))
    parser.add_argument(
        "--export-dir", default=None,
        help="Directory for the grep-baseline markdown export (default: a temp dir).",
    )
    args = parser.parse_args()

    live_db = Path(args.db) if args.db else settings.db_path
    questions_path = Path(args.questions)
    out_path = Path(args.out)
    k_values = sorted(set(args.k))
    max_k = max(k_values)

    questions = load_questions(questions_path)
    if not questions:
        print(f"[benchmark] no questions found in {questions_path}", file=sys.stderr)
        sys.exit(1)

    mode_supported = retrieve_supports_mode()
    backend_names = ["hybrid", "vector"] if mode_supported else ["vector"]
    pending: list[str] = []
    if not mode_supported:
        pending.append(
            "hybrid (KnowledgeService.retrieve has no `mode` parameter in this checkout yet; "
            "ran vector-only and skipped hybrid)"
        )

    with tempfile.TemporaryDirectory(prefix="grimoire-benchmark-") as tmp:
        tmp_path = Path(tmp)
        snapshot_path = tmp_path / "snapshot.db"
        print(f"[benchmark] snapshotting {live_db} -> {snapshot_path} (live store is never written to)")
        snapshot_db(live_db, snapshot_path)

        repo = Repository(snapshot_path)
        try:
            counts = repo.counts()
            provider, provider_name, is_fake = resolve_provider()
            reranker = get_reranker(settings.rerank_enabled, settings.rerank_model)
            service = KnowledgeService(repo, provider, reranker)

            per_backend_rankings: dict[str, list[list[str] | None]] = {b: [] for b in backend_names}
            for q in questions:
                for b in backend_names:
                    mode = b if mode_supported else None
                    ranked, err = run_grimoire_backend(service, mode, q["q"], max_k)
                    per_backend_rankings[b].append(ranked)
                    if err:
                        print(f"[benchmark] {b} query failed ({err[:120]}): {q['q'][:60]!r}", file=sys.stderr)

            # grep baseline
            export_dir = Path(args.export_dir) if args.export_dir else tmp_path / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            mapping = build_export_corpus(snapshot_path, export_dir)
            has_rg = shutil.which("rg") is not None
            if mapping is None:
                pending.append("grep baseline (grimoire.export is not available in this checkout yet)")
            elif not mapping:
                pending.append("grep baseline (export produced no markdown files with a grimoire_id)")
            else:
                per_backend_rankings["grep"] = [
                    grep_rank(q["q"], mapping, export_dir, has_rg) for q in questions
                ]
        finally:
            repo.close()

    metrics = {
        b: score_backend(rankings, questions, k_values)
        for b, rankings in per_backend_rankings.items()
    }

    write_report(
        out_path=out_path,
        metrics=metrics,
        k_values=k_values,
        questions_path=questions_path,
        n_questions=len(questions),
        counts=counts,
        provider_name=provider_name,
        is_fake=is_fake,
        rerank_enabled=settings.rerank_enabled,
        pending=pending,
        has_rg=has_rg,
    )
    print(f"[benchmark] wrote {out_path}")


if __name__ == "__main__":
    main()
