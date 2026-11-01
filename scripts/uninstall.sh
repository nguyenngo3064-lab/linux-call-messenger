#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/messenger-call-keeper}"
PURGE=false
if [[ "${1:-}" == "--purge" ]]; then PURGE=true; fi
if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root, for example: sudo bash scripts/uninstall.sh" >&2
  exit 1
fi
systemctl disable --now messenger-call-keeper.service messenger-call-keeper-xvfb.service 2>/dev/null || true
systemctl disable --now messenger-call-keeper-websockify.service messenger-call-keeper-vnc.service 2>/dev/null || true
rm -f /etc/systemd/system/messenger-call-keeper.service
rm -f /etc/systemd/system/messenger-call-keeper-xvfb.service
rm -f /etc/systemd/system/messenger-call-keeper-vnc.service
rm -f /etc/systemd/system/messenger-call-keeper-websockify.service
systemctl daemon-reload
rm -rf -- "$INSTALL_DIR"
if [[ "$PURGE" == true ]]; then
  rm -rf -- /var/lib/messenger-call-keeper /var/log/messenger-call-keeper /etc/messenger-call-keeper
  if id messenger-call-keeper >/dev/null 2>&1; then userdel messenger-call-keeper; fi
  echo "Application and stored profile/configuration removed."
else
  echo "Application removed; database and browser profile are preserved under /var/lib/messenger-call-keeper."
  echo "Configuration is preserved under /etc/messenger-call-keeper. Use --purge only to erase them."
fi
