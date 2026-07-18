"""Export the whole grimoire to a read-only Obsidian vault (Phase 6).

One markdown file per node (project/document/memory/entity), with YAML
frontmatter and edges rendered as [[wikilinks]]. One-way: this never reads
Obsidian back into the store. Re-running wipes and rewrites output_dir.

    .venv/bin/python scripts/export_markdown.py path/to/vault
    .venv/bin/python scripts/export_markdown.py path/to/vault --db data/grimoire.db
"""

from __future__ import annotations

import argparse
from pathlib import Path

from grimoire.config import settings
from grimoire.export import export_store
from grimoire.store import Repository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output_dir")
    parser.add_argument("--db", dest="db", default=None, help="override the store path (for testing)")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else Path(settings.db_path)
    repo = Repository(db_path)
    try:
        result = export_store(repo, args.output_dir)
    finally:
        repo.close()

    print(f"exported {result['nodes']} nodes, {result['edges']} edges -> {result['output_dir']}")


if __name__ == "__main__":
    main()
