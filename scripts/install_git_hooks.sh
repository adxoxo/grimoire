#!/usr/bin/env bash
# Install/refresh the Grimoire git hooks into this repo's .git/hooks/. Safe to
# re-run (idempotent): copies over whatever is already there and re-marks it
# executable.
#
#   bash scripts/install_git_hooks.sh
set -euo pipefail
cd "$(dirname "$0")/.."

GIT_DIR="$(git rev-parse --git-dir)"
mkdir -p "$GIT_DIR/hooks"

cp deploy/hooks/post-commit "$GIT_DIR/hooks/post-commit"
chmod +x "$GIT_DIR/hooks/post-commit"

echo "installed $GIT_DIR/hooks/post-commit"
ls -l "$GIT_DIR/hooks/post-commit"
