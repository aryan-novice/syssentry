#!/usr/bin/env bash
# Installs SysSentry as a systemd service on Ubuntu/Debian/RHEL-style hosts.
#   sudo ./scripts/install.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX=/opt/syssentry

echo "[1/5] creating service user and directories"
id syssentry >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin syssentry
# adm group can read /var/log/auth.log and syslog on Debian/Ubuntu
getent group adm >/dev/null && usermod -aG adm syssentry
install -d -o syssentry -g syssentry /var/lib/syssentry /var/log/syssentry
install -d /etc/syssentry "$PREFIX"

echo "[2/5] copying application to $PREFIX"
cp -r "$SRC/syssentry" "$SRC/requirements.txt" "$PREFIX/"

echo "[3/5] creating virtualenv"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q -r "$PREFIX/requirements.txt"

echo "[4/5] installing config (kept if it already exists)"
[ -f /etc/syssentry/config.yaml ] || cp "$SRC/config.example.yaml" /etc/syssentry/config.yaml

echo "[5/5] enabling systemd unit"
cp "$SRC/deploy/syssentry.service" /etc/systemd/system/syssentry.service
systemctl daemon-reload
systemctl enable --now syssentry.service
systemctl --no-pager status syssentry.service | head -5
echo "done: dashboard on http://<host>:8085, logs with: journalctl -u syssentry -f"
