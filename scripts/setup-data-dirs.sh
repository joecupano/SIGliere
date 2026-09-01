#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || {
  echo "Run with sudo." >&2
  exit 1
}

OWNER="${1:-${SUDO_USER:-}}"
[[ -n "${OWNER}" ]] || {
  echo "Provide owner[:group] or run through sudo." >&2
  exit 1
}

for path in   /data/models   /data/corpus/source   /data/corpus/processed   /data/reference/sigid   /data/reference/mac-vendors   /data/imagery   /data/audio; do
  install -d -m 0750 -o "${OWNER%%:*}" -g "${OWNER#*:}" "${path}"
done

if id ollama >/dev/null 2>&1; then
  chown -R ollama:ollama /data/models
fi

echo "Created AI/reference data directories only. Collection data belongs to SIGedge."

