#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || {
  echo "Run with sudo." >&2
  exit 1
}

apt update
apt install -y ufw unattended-upgrades fail2ban
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 8443/tcp comment 'Sigliere Caddy TLS ingress'
ufw --force enable

echo "Only SSH and Caddy HTTPS are allowed inbound."
echo "Ollama (11434), Open WebUI (8080), Caddy private routing (8180),"
echo "and the SIGedge gateway (8140) must remain loopback-only."

