# Grimoire retrieval benchmark

Generated 2026-07-18 06:23 UTC by `scripts/benchmark.py`.

## Results

| backend | recall@5 | recall@10 | mrr | scored questions |
|---|---|---|---|---|
| grimoire retrieve (mode=hybrid, BM25+vector RRF) | 0.88 | 0.90 | 0.56 | 50 |
| grimoire retrieve (mode=vector) | 0.84 | 0.90 | 0.64 | 50 |
| grep / term-frequency baseline | 0.66 | 0.84 | 0.39 | 50 |

## Run configuration

- Questions: 50 (from `/home/adyu/apps/grimoire/benchmarks/questions.jsonl`)
- k values: 5, 10
- Embedding provider: `ollama`
- Re-ranker (cross-encoder second stage): enabled
- ripgrep available for the grep baseline: no (pure-python term scan used)
- Store snapshot: nodes=379, edges=363, memory_raw=6, chunks=182, chunk_vectors=182
- Date: 2026-07-18 06:23 UTC

## How to re-run

```bash
.venv/bin/python scripts/benchmark.py \
  --questions benchmarks/questions.jsonl \
  --k 5 10 \
  --out BENCHMARKS.md
```

The script always snapshots `data/grimoire.db` (or `--db`) to a temp file first via `Repository.backup()` and only ever reads/queries that snapshot -- the live store is never opened for writes.

## Notes

- A hit = a returned chunk/file whose `node_id` matches one of a question's `gold_node_ids`. Metrics are computed over unique node ids in rank order (duplicate chunks from the same node collapse to their first, best rank).
- If the grep baseline wins on any metric, that is signal about the current retrieval quality, not a bug in the harness -- it is kept in the table either way.
