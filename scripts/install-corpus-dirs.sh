#!/usr/bin/env bash
# scripts/install-corpus-dirs.sh
#
# Foundational — builds the whole /data corpus tree (see
# docs/data-layout.md) up front, before Ollama or any optional
# ai-ingest/reference-mirror feature runs. Every current and future
# consumer of that tree (install-ollama.sh's /data/models, install-ai-ingest.sh,
# install-mac-mirror.sh, install-sigid-mirror.sh) assumes this has already
# run — creating it here, once, keeps that assumption true instead of
# leaving each consumer to create its own piece ad hoc with inconsistent
# ownership/permissions.
#
# Run right after install-os-packages.sh, with sudo — the owner defaults
# to $SUDO_USER, or pass owner[:group] explicitly as $1.
#
# Usage: sudo ./scripts/install-corpus-dirs.sh [owner[:group]]

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

for path in   /data/models   /data/corpus/source   /data/corpus/processed   /data/imagery   /data/audio; do
  install -d -m 0750 -o "${OWNER%%:*}" -g "${OWNER#*:}" "${path}"
done

# /data/reference/* is public reference data (MAC vendor + SigID mirrors)
# mounted read-only into Open WebUI's container under a different,
# UID-mapped identity — neither this directory's owner nor its group. That
# identity needs "other" traverse/read access, so this subtree (and the
# /data, /data/reference path segments leading to it) gets 0755 instead of
# the 0750 the rest of /data uses. This doesn't expose sibling directories'
# contents — /data/models, /data/corpus, etc. keep their own tighter mode
# above regardless of /data itself being traversable.
install -d -m 0755 -o "${OWNER%%:*}" -g "${OWNER#*:}" /data /data/reference
for path in   /data/reference/sigid/images   /data/reference/sigid/audio   /data/reference/sigid/metadata   /data/reference/mac-vendors; do
  install -d -m 0755 -o "${OWNER%%:*}" -g "${OWNER#*:}" "${path}"
done

if id ollama >/dev/null 2>&1; then
  chown -R ollama:ollama /data/models
fi

echo "Created AI/reference data directories only. Collection data belongs to SIGedge."

