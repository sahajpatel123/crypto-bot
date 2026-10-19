#!/usr/bin/env bash
# F2.4: Ubuntu host bootstrap. Run as root on a fresh VM.
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl git python3.12 python3.12-venv python3-pip \
  chrony logrotate ufw jq
# Clock discipline is a hard prerequisite for signed requests.
systemctl enable --now chrony
timedatectl set-ntp true
# Raise file descriptors for the recorder + websocket fan-out.
cat >/etc/security/limits.d/cryptobot.conf <<'EOF'
cryptobot soft nofile 65536
cryptobot hard nofile 65536
EOF
# Minimal host firewall: outbound only; no inbound bot port.
ufw default deny incoming
ufw default allow outgoing
ufw --force enable || true
# Application user + directories.
id cryptobot >/dev/null 2>&1 || useradd -r -m -d /opt/cryptobot cryptobot
install -d -o cryptobot -g cryptobot /opt/cryptobot /var/lib/cryptobot
install -d -o cryptobot -g cryptobot /opt/cryptobot/data/recorder
install -d -o cryptobot -g cryptobot /opt/cryptobot/data/vault
echo "bootstrap: OK; copy the repo to /opt/cryptobot, then install systemd units."
