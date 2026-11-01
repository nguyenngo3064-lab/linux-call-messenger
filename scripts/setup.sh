#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/messenger-call-keeper}"
CONFIG_DIR="/etc/messenger-call-keeper"
SERVICE_USER="messenger-call-keeper"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root, for example: sudo bash scripts/setup.sh" >&2
  exit 1
fi
"$SCRIPT_DIR/install.sh"
if [[ -e "$CONFIG_DIR/mck.env" ]]; then
  echo "Existing configuration preserved at $CONFIG_DIR/mck.env."
else
  echo "Create a unique administrator password; it will only be stored as an Argon2id hash."
  ADMIN_PASSWORD_HASH="$("$INSTALL_DIR/.venv/bin/python" -m backend.security hash-password)"
  SESSION_SECRET_KEY="$("$INSTALL_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  temporary="$(mktemp "$CONFIG_DIR/mck.env.XXXXXX")"
  trap 'rm -f -- "$temporary"' EXIT
  umask 077
  printf '%s\n' \
    "ADMIN_PASSWORD_HASH=$ADMIN_PASSWORD_HASH" \
    "SESSION_SECRET_KEY=$SESSION_SECRET_KEY" \
    'SESSION_HTTPS_ONLY=true' \
    'BROWSER_NAME=firefox-esr' \
    'BROWSER_PROFILE_DIR=/var/lib/messenger-call-keeper/browser-profile' \
    'BROWSER_AUTO_RESTART=true' \
    'BROWSER_HEADLESS=false' \
    'DISPLAY=:99' \
    'MCK_DATA_DIR=/var/lib/messenger-call-keeper' \
    'MCK_LOG_DIR=/var/log/messenger-call-keeper' \
    > "$temporary"
  chmod 0640 "$temporary"
  chown "root:$SERVICE_USER" "$temporary"
  mv -- "$temporary" "$CONFIG_DIR/mck.env"
  trap - EXIT
fi
systemctl enable --now messenger-call-keeper-xvfb.service
systemctl enable --now messenger-call-keeper.service
printf '%s\n' \
  'Setup complete. The backend listens on 127.0.0.1:8000.' \
  'Put it behind an HTTPS reverse proxy before remote access.'
