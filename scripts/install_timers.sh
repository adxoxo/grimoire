#!/usr/bin/env bash
# Install/refresh the Grimoire maintenance timers (compact weekly, re-embed monthly,
# backup daily) as systemd USER units. Safe to re-run (idempotent).
#
#   bash scripts/install_timers.sh
#
# Logs: journalctl --user -u grimoire-compact -f  (or -reembed / -backup)
#       data/logs/grimoire-{compact,reembed,backup}.log
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p data/logs
mkdir -p ~/.config/systemd/user

# compaction now runs in-process via the API lifespan scheduler (see grimoire/scheduler.py)
# grimoire-compact.service grimoire-compact.timer \
for unit in grimoire-reembed.service grimoire-reembed.timer \
            grimoire-backup.service grimoire-backup.timer; do
  cp "deploy/$unit" ~/.config/systemd/user/
done

systemctl --user daemon-reload
# compaction now runs in-process via the API lifespan scheduler (see grimoire/scheduler.py)
# systemctl --user enable --now grimoire-compact.timer
systemctl --user enable --now grimoire-reembed.timer
systemctl --user enable --now grimoire-backup.timer

echo "installed. current timers:"
systemctl --user list-timers 'grimoire-*'
