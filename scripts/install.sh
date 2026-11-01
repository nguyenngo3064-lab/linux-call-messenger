#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/messenger-call-keeper}"
SERVICE_USER="messenger-call-keeper"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root, for example: sudo bash scripts/install.sh" >&2
  exit 1
fi
if [[ -f /etc/messenger-call-keeper/mck.env && "${MCK_UPGRADE:-0}" != "1" ]]; then
  echo "Existing installation detected. Use scripts/deploy.sh to back up data before upgrading." >&2
  exit 1
fi
if [[ ! -r /etc/os-release ]]; then
  echo "Cannot identify Linux distribution." >&2
  exit 1
fi
source /etc/os-release
case "$(uname -m)" in
  x86_64|aarch64) ;;
  *) echo "Unsupported CPU architecture: $(uname -m)" >&2; exit 1 ;;
esac
case "${ID:-}" in
  debian|ubuntu) ;;
  *) echo "Supported distributions: Debian and Ubuntu." >&2; exit 1 ;;
esac

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gpg novnc python3 python3-pip python3-venv rsync websockify x11vnc xvfb
if [[ "$ID" == "ubuntu" ]]; then
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://packages.mozilla.org/apt/repo-signing-key.gpg \
    | gpg --dearmor --yes -o /etc/apt/keyrings/packages.mozilla.org.gpg
  chmod 0644 /etc/apt/keyrings/packages.mozilla.org.gpg
  printf '%s\n' \
    'deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.gpg] https://packages.mozilla.org/apt mozilla main' \
    > /etc/apt/sources.list.d/mozilla.list
  printf '%s\n' \
    'Package: *' \
    'Pin: origin packages.mozilla.org' \
    'Pin-Priority: 1000' \
    > /etc/apt/preferences.d/mozilla
  apt-get update
fi
apt-get install -y firefox-esr

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/messenger-call-keeper \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 /var/lib/messenger-call-keeper
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 /var/log/messenger-call-keeper
install -d -o root -g "$SERVICE_USER" -m 0750 /etc/messenger-call-keeper
install -d -o root -g root -m 0755 "$INSTALL_DIR"
rsync -a \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='data/' \
  --exclude='logs/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  "$REPO_DIR/" "$INSTALL_DIR/"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --no-cache-dir -r "$INSTALL_DIR/requirements.txt"
chown -R root:root "$INSTALL_DIR"
chmod -R go-w "$INSTALL_DIR"
install -m 0644 "$INSTALL_DIR/systemd/messenger-call-keeper.service" \
  /etc/systemd/system/messenger-call-keeper.service
install -m 0644 "$INSTALL_DIR/systemd/messenger-call-keeper-xvfb.service" \
  /etc/systemd/system/messenger-call-keeper-xvfb.service
install -m 0644 "$INSTALL_DIR/systemd/messenger-call-keeper-vnc.service" \
  /etc/systemd/system/messenger-call-keeper-vnc.service
install -m 0644 "$INSTALL_DIR/systemd/messenger-call-keeper-websockify.service" \
  /etc/systemd/system/messenger-call-keeper-websockify.service
systemctl daemon-reload
printf 'Code and dependencies installed in %s.\n' "$INSTALL_DIR"
printf 'Next: sudo bash %s/setup.sh\n' "$SCRIPT_DIR"
