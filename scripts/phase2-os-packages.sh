#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || {
  echo "Run with sudo: sudo ./scripts/phase2-os-packages.sh" >&2
  exit 1
}

TARGET_USER="${SUDO_USER:-}"
[[ -n "${TARGET_USER}" ]] || {
  echo "SUDO_USER is empty; run through sudo from the deployment account." >&2
  exit 1
}

apt update
apt install -y   ca-certificates curl git jq openssl   podman uidmap slirp4netns fuse-overlayfs   python3 python3-pip python3-venv

if ! grep -q "^${TARGET_USER}:" /etc/subuid; then
  usermod --add-subuids 100000-165535 "${TARGET_USER}"
fi
if ! grep -q "^${TARGET_USER}:" /etc/subgid; then
  usermod --add-subgids 100000-165535 "${TARGET_USER}"
fi
loginctl enable-linger "${TARGET_USER}"

echo "AI-tier prerequisites installed for ${TARGET_USER}."
echo "No SDR, DSP, ka9q-radio, OpenWebRX+, or collection packages were installed."

