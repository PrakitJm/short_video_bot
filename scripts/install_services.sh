#!/usr/bin/env bash
# Install the always-on services (run once; safe to rerun after moving the project or changing PATH):
#   autovideo-bot.service    Telegram bot + worker, starts with WSL, restarts itself on crash
#   autovideo-daily.timer    every day at 08:00 queues the next story part (bot then asks you to approve)
# Remove: systemctl --user disable --now autovideo-bot autovideo-daily.timer
set -euo pipefail
cd "$(dirname "$0")/.."
dir=$PWD; uv=$(command -v uv); unit=~/.config/systemd/user
mkdir -p "$unit" data/logs
cat > "$unit/autovideo-bot.service" <<UNIT
[Unit]
Description=autovideo Telegram bot + worker
After=network-online.target

[Service]
WorkingDirectory=$dir
Environment=PATH=$PATH
ExecStart=$uv run autovideo run
Restart=always
RestartSec=30
StandardOutput=append:$dir/data/logs/bot.log
StandardError=append:$dir/data/logs/bot.log

[Install]
WantedBy=default.target
UNIT
cat > "$unit/autovideo-daily.service" <<UNIT
[Unit]
Description=autovideo: queue the next story part

[Service]
Type=oneshot
WorkingDirectory=$dir
Environment=PATH=$PATH
ExecStart=$uv run autovideo story-next
StandardOutput=append:$dir/data/logs/daily.log
StandardError=append:$dir/data/logs/daily.log
UNIT
cat > "$unit/autovideo-daily.timer" <<UNIT
[Unit]
Description=autovideo daily story part

[Timer]
OnCalendar=*-*-* 08:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl --user stop autovideo-bot 2>/dev/null || true   # an older one-off (systemd-run) bot
systemctl --user reset-failed autovideo-bot 2>/dev/null || true
while [ -e /run/user/$(id -u)/systemd/transient/autovideo-bot.service ]; do sleep 1; done
systemctl --user daemon-reload
systemctl --user enable --now autovideo-bot autovideo-daily.timer
systemctl --user --no-pager status autovideo-bot | head -3
systemctl --user list-timers autovideo-daily.timer --no-pager | head -2
