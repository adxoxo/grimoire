"""Backup-and-restore routine. Non-negotiable per ARCHITECTURE: a backup is verified
by opening and integrity-checking it, never assumed. Built before real data lands.

CLI (the basis for cron/n8n scheduling):
    python -m grimoire.backup backup
    python -m grimoire.backup restore backups/grimoire-<ts>.db
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from grimoire.config import settings
from grimoire.store import Repository, restore, verify_store


def make_backup(db_path: str | Path | None = None, backup_dir: str | Path = "backups") -> Path:
    """Create a timestamped, verified backup. Raises if verification fails."""
    db_path = Path(db_path or settings.db_path)
    backup_dir = Path(backup_dir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = backup_dir / f"grimoire-{ts}.db"

    repo = Repository(db_path)
    try:
        repo.backup(dest)
    finally:
        repo.close()

    if not verify_store(dest):
        raise RuntimeError(f"backup verification failed (integrity_check): {dest}")
    return dest


def restore_backup(backup_path: str | Path, db_path: str | Path | None = None) -> Path:
    """Restore a backup over the live store, then verify the restored store."""
    db_path = Path(db_path or settings.db_path)
    restore(backup_path, db_path)
    if not verify_store(db_path):
        raise RuntimeError(f"restored store failed integrity_check: {db_path}")
    return db_path


def prune_backups(backup_dir: str | Path = "backups", retain: int = 14) -> list[Path]:
    """Delete all but the `retain` most recent grimoire-*.db backups. Returns deleted paths."""
    backup_dir = Path(backup_dir)
    backups = sorted(backup_dir.glob("grimoire-*.db"), key=lambda p: p.name, reverse=True)
    stale = backups[retain:]
    for path in stale:
        path.unlink()
    return stale


def _main() -> None:
    parser = argparse.ArgumentParser(description="Grimoire backup/restore")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup", help="create a verified backup")
    b.add_argument("--retain", type=int, default=14, help="keep only the N most recent backups (default 14)")
    r = sub.add_parser("restore", help="restore a backup over the live store")
    r.add_argument("path", help="backup file to restore")
    args = parser.parse_args()

    if args.cmd == "backup":
        print(f"backup written and verified: {make_backup()}")
        stale = prune_backups(retain=args.retain)
        if stale:
            print(f"pruned {len(stale)} old backup(s): {', '.join(p.name for p in stale)}")
    elif args.cmd == "restore":
        print(f"restored and verified: {restore_backup(args.path)}")


if __name__ == "__main__":
    _main()
