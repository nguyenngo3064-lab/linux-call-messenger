#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/messenger-call-keeper}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/messenger-call-keeper}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root, for example: sudo bash scripts/deploy.sh" >&2
  exit 1
fi
if [[ ! -d /var/lib/messenger-call-keeper || ! -f /etc/messenger-call-keeper/mck.env ]]; then
  echo "Existing installation/configuration not found; use scripts/setup.sh first." >&2
  exit 1
fi
install -d -o root -g root -m 0700 "$BACKUP_DIR"
backup="$BACKUP_DIR/backup-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -C / -czf "$backup" var/lib/messenger-call-keeper etc/messenger-call-keeper
chmod 0600 "$backup"
MCK_UPGRADE=1 "$SCRIPT_DIR/install.sh"
systemctl restart messenger-call-keeper-xvfb.service messenger-call-keeper.service
printf 'Updated. Protected data/config backup: %s\n' "$backup"
