#!/usr/bin/env bash
# scripts/install-mac-mirror.sh
#
# Optional MAC vendor (OUI/CID) database mirror.
# Sets up the /data/reference/mac-vendors layout and installs a
# systemd --user timer for weekly re-sync. reference/mac_mirror.py's only
# dependency is `requests`, already in the reference venv from
# the SigID mirror — nothing new to install there.
#
# Run as your normal user, NOT with sudo — same rootless pattern as
# the other rootless user services.
#
# This script sets up the SCHEDULE. It also runs one sync immediately so
# there's real data to validate against — run
# scripts/validate-mac-mirror.sh afterward.
#
# Usage: ./scripts/install-mac-mirror.sh

set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Do not run this as root/sudo — the systemd --user timer needs to be" >&2
  echo "owned by and run as your normal user. Re-run without sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${HOME}/.local/share/sigliere/venvs/reference/bin/python3"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

echo "== MAC vendor database mirror =="

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "ERROR: expected venv interpreter not found at ${VENV_PYTHON}" >&2
  echo "       Run scripts/install-sigid-mirror.sh (or setup-venvs.sh reference)" >&2
  echo "       first — this mirror shares that venv." >&2
  exit 1
fi

if ! "${VENV_PYTHON}" -c "import requests" >/dev/null 2>&1; then
  echo "ERROR: 'requests' not importable in ${VENV_PYTHON}" >&2
  echo "       Run: ${REPO_ROOT}/scripts/setup-venvs.sh reference" >&2
  exit 1
fi

# ---------------------------------------------------------------------
# /data/reference/mac-vendors layout — created up front by
# scripts/install-corpus-dirs.sh (run during host prerequisites, before
# any of this), not here. Check rather than assume, so a skipped step
# fails with a clear message instead of a confusing one later.
# ---------------------------------------------------------------------
if [[ ! -d /data/reference/mac-vendors ]]; then
  echo "ERROR: /data/reference/mac-vendors does not exist." >&2
  echo "       Run scripts/install-corpus-dirs.sh first." >&2
  exit 1
fi

# Same reasoning as the SigID tree (scripts/install-corpus-dirs.sh): the Open
# WebUI container reads this as a non-owner UID under rootless Podman, and
# this is public reference data, so make the traversal path + tree
# world-readable rather than fighting UID mapping.
if [[ -d /data/reference ]]; then
  chmod o+x /data /data/reference 2>/dev/null || true
  chmod -R o+rX /data/reference/mac-vendors 2>/dev/null || true
fi

# ---------------------------------------------------------------------
# systemd --user timer
# ---------------------------------------------------------------------
echo "-- Installing systemd --user timer --"
mkdir -p "${SYSTEMD_USER_DIR}"

sed -e "s|__REPO_ROOT__|${REPO_ROOT}|g" \
    -e "s|__VENV_PYTHON__|${VENV_PYTHON}|g" \
    "${REPO_ROOT}/systemd/mac-mirror.service" > "${SYSTEMD_USER_DIR}/mac-mirror.service"

cp "${REPO_ROOT}/systemd/mac-mirror.timer" "${SYSTEMD_USER_DIR}/mac-mirror.timer"

systemctl --user daemon-reload
systemctl --user enable --now mac-mirror.timer

# ---------------------------------------------------------------------
# Run one sync now so there's something to validate
# ---------------------------------------------------------------------
echo "-- Running initial sync --"
cd "${REPO_ROOT}/reference"
"${VENV_PYTHON}" mac_mirror.py

cat <<EOF

== MAC vendor mirror install complete ==

Timer installed: sync runs weekly (see systemd/mac-mirror.timer).
Check status:     systemctl --user status mac-mirror.timer
Run manually any time: systemctl --user start mac-mirror.service
View logs:         journalctl --user -u mac-mirror.service -f

Next steps:
  - Add the read-only /data/reference/mac-vendors:/data/mac-vendors-ref mount
    through an Open WebUI Quadlet drop-in and install
    openwebui-tools/mac_lookup_tool.py per docs/optional-tools.md.
  - Run scripts/validate-mac-mirror.sh to confirm real content
    landed in /data/reference/mac-vendors.
EOF
