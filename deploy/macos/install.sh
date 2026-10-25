#!/bin/sh
# Per-user launchd agents. No sudo. Public data only.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
PY="${CRYPTOBOT_PYTHON:-$ROOT/.venv/bin/python}"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/cryptobot"
UID_N="$(id -u)"
mkdir -p "$AGENTS" "$LOGS" "$ROOT/data/recorder" "$ROOT/data/lake/forward" "$ROOT/data/pnl"
install_one() {
  label="$1"
  body="$2"
  dest="$AGENTS/$label.plist"
  printf '%s\n' "$body" > "$dest"
  launchctl bootout "gui/$UID_N" "$dest" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$UID_N" "$dest"
  echo "installed $label"
}
COMMON="
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>$ROOT/src</string>
    <key>CRYPTOBOT_ROOT</key><string>$ROOT</string>
  </dict>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StandardOutPath</key><string>$LOGS/PLACE.log</string>
  <key>StandardErrorPath</key><string>$LOGS/PLACE.err</string>
"
install_one com.cryptobot.recorder "$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cryptobot.recorder</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-is</string>
    <string>/usr/bin/nice</string><string>-n</string><string>10</string>
    <string>$PY</string><string>-m</string><string>cryptobot.cli</string>
    <string>recorder</string><string>start</string>
    <string>--out</string><string>$ROOT/data/recorder</string>
    <string>--symbols</string><string>BTCUSDT,ETHUSDT</string>
    <string>--chunk-seconds</string><string>300</string>
    <string>--disk-budget-mb</string><string>8192</string>
  </array>
  <key>KeepAlive</key><true/>
  <key>Nice</key><integer>10</integer>
  ${COMMON//PLACE/recorder}
</dict></plist>
EOF
)"
install_one com.cryptobot.refresh "$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cryptobot.refresh</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>$ROOT/tools/forward_refresh.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>15</integer></dict>
  ${COMMON//PLACE/refresh}
</dict></plist>
EOF
)"
install_one com.cryptobot.autopilot "$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cryptobot.autopilot</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>-m</string><string>cryptobot.cli</string>
    <string>autopilot</string><string>run-once</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>
  ${COMMON//PLACE/autopilot}
</dict></plist>
EOF
)"
install_one com.cryptobot.adjudicate "$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cryptobot.adjudicate</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>-m</string><string>cryptobot.cli</string>
    <string>adjudicate</string><string>--no-notify</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>45</integer></dict>
  ${COMMON//PLACE/adjudicate}
</dict></plist>
EOF
)"
install_one com.cryptobot.verdict-watch "$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cryptobot.verdict-watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>-m</string><string>cryptobot.cli</string>
    <string>verdict-watch</string><string>--once</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>
  ${COMMON//PLACE/verdict-watch}
</dict></plist>
EOF
)"
install_one com.cryptobot.pnl "$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cryptobot.pnl</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>-m</string><string>cryptobot.cli</string>
    <string>pnl</string><string>daily</string><string>--out</string>
    <string>$ROOT/data/pnl/daily.json</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>15</integer></dict>
  ${COMMON//PLACE/pnl}
</dict></plist>
EOF
)"
install_one com.cryptobot.watchdog "$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cryptobot.watchdog</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>$ROOT/deploy/macos/watchdog.py</string>
  </array>
  <key>StartInterval</key><integer>60</integer>
  ${COMMON//PLACE/watchdog}
</dict></plist>
EOF
)"
echo "logs: $LOGS"
