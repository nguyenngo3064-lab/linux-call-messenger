#!/usr/bin/env bash
set -Eeuo pipefail

ACTION="${1:-}"
if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root, for example: sudo bash scripts/gui-login.sh start" >&2
  exit 1
fi
case "$ACTION" in
  start)
    systemctl start messenger-call-keeper-vnc.service messenger-call-keeper-websockify.service
    printf '%s\n' \
      'GUI login is available only on 127.0.0.1:6080.' \
      'Create an SSH tunnel to port 6080 before opening noVNC; never expose this port publicly.'
    ;;
  stop)
    systemctl stop messenger-call-keeper-websockify.service messenger-call-keeper-vnc.service
    ;;
  *)
    echo "Usage: sudo bash scripts/gui-login.sh {start|stop}" >&2
    exit 2
    ;;
esac
