#!/bin/sh
# Remove the per-user cryptobot launchd agents. No sudo.
set -eu
AGENTS="$HOME/Library/LaunchAgents"
UID_N="$(id -u)"
for label in com.cryptobot.recorder com.cryptobot.refresh \
    com.cryptobot.autopilot com.cryptobot.adjudicate \
    com.cryptobot.watchdog
do
  dest="$AGENTS/$label.plist"
  if [ -f "$dest" ]; then
    launchctl bootout "gui/$UID_N" "$dest" >/dev/null 2>&1 || true
    rm -f "$dest"
    echo "removed $label"
  fi
done
