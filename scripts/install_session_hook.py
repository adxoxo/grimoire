#!/usr/bin/env python3
"""Install the Grimoire session-context bootstrap as a Claude Code SessionStart hook.

Merges into ~/.claude/settings.json (never replaces it), backing the file up first.
Idempotent: skips if a hook running this exact command is already present under
SessionStart.

    python3 scripts/install_session_hook.py
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
HOOK_COMMAND = "python3 /home/adyu/apps/grimoire/scripts/session_context.py"


def main() -> None:
    if not SETTINGS_PATH.exists():
        print(f"error: {SETTINGS_PATH} does not exist; create it first")
        raise SystemExit(2)

    settings = json.loads(SETTINGS_PATH.read_text())

    hooks = settings.setdefault("hooks", {})
    session_start = hooks.setdefault("SessionStart", [])

    for entry in session_start:
        for h in entry.get("hooks", []):
            if h.get("type") == "command" and h.get("command") == HOOK_COMMAND:
                print(f"already installed in {SETTINGS_PATH}; nothing to do")
                return

    backup_path = SETTINGS_PATH.with_name(
        f"settings.json.bak-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    shutil.copy(SETTINGS_PATH, backup_path)

    session_start.append({"hooks": [{"type": "command", "command": HOOK_COMMAND}]})

    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"backed up {SETTINGS_PATH} -> {backup_path}")
    print(f"added SessionStart hook to {SETTINGS_PATH}: {HOOK_COMMAND}")


if __name__ == "__main__":
    main()
