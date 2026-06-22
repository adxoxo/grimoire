"""Compaction job (Phase 5). Run on a schedule (cron or n8n).

    .venv/bin/python scripts/compact.py            # compact + refresh context, all projects
    .venv/bin/python scripts/compact.py --reembed  # also re-embed the whole store

Re-embedding is the maintenance path for changing embedding models; it lives here
because both are scheduled store-maintenance jobs.
"""

from __future__ import annotations

import sys

from grimoire.compaction import compact_project, consolidate_context
from grimoire.config import settings
from grimoire.providers import get_provider
from grimoire.reembed import reembed_all
from grimoire.service import KnowledgeService
from grimoire.store import Repository


def main() -> None:
    do_reembed = "--reembed" in sys.argv
    repo = Repository(settings.db_path)
    svc = KnowledgeService(repo, get_provider())
    try:
        for project in [n["title"] for n in repo.list_nodes(type="project")]:
            stats = compact_project(svc, project)
            ctx = consolidate_context(svc, project)
            print(
                f"{project}: merged {stats['clusters_merged']} clusters, "
                f"archived {stats['originals_archived']}; "
                f"context {'refreshed' if ctx else 'unchanged'}"
            )
        if do_reembed:
            print(f"re-embedded {reembed_all(repo, svc.provider)} chunks")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
