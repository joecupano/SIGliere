#!/usr/bin/env bash
# scripts/install-occupancy.sh
#
# Optional occupancy service. Sets up the occupancy venv, installs a
# systemd --user unit that polls the SIGedge gateway's /status endpoint
# continuously and logs active channels into
# /data/occupancy/occupancy.db, and starts it.
#
# Depends on the gateway already being installed (scripts/install-sigedge-gateway.sh)
# — occupancy_producer.py reads its bearer token from
# ~/.config/sigliere/gateway.env, the same file that installer generates.
#
# Run as your normal user, NOT with sudo — same rootless pattern as
# other rootless user services.
#
# Usage: ./scripts/install-occupancy.sh

set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Do not run this as root/sudo — the venv and systemd --user service" >&2
  echo "need to be owned by and run as your normal user. Re-run without sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${HOME}/.local/share/sigliere/venvs/occupancy/bin/python3"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
GATEWAY_ENV="${HOME}/.config/sigliere/gateway.env"

echo "== Occupancy service =="

# ---------------------------------------------------------------------
# Gateway dependency
# ---------------------------------------------------------------------
if [[ ! -r "${GATEWAY_ENV}" ]]; then
  echo "ERROR: ${GATEWAY_ENV} not found." >&2
  echo "       Run scripts/install-sigedge-gateway.sh first — occupancy_producer.py" >&2
  echo "       authenticates to the gateway with the analyst token it generates." >&2
  exit 1
fi

# ---------------------------------------------------------------------
# occupancy venv
# ---------------------------------------------------------------------
echo "-- Installing occupancy venv --"
"${REPO_ROOT}/scripts/setup-venvs.sh" occupancy

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "ERROR: expected venv interpreter not found at ${VENV_PYTHON}" >&2
  exit 1
fi

# ---------------------------------------------------------------------
# /data/occupancy — created up front by scripts/install-corpus-dirs.sh,
# not here. Check rather than assume, same pattern as install-sigid-mirror.sh.
# ---------------------------------------------------------------------
if [[ ! -d /data/occupancy ]]; then
  echo "ERROR: /data/occupancy does not exist." >&2
  echo "       Run scripts/install-corpus-dirs.sh first." >&2
  exit 1
fi

# ---------------------------------------------------------------------
# systemd --user service — continuous poller, not a timer. Occupancy is
# about catching activity within a poll interval measured in seconds,
# not sigid-mirror's weekly-sync shape, so this runs as a persistent
# Type=simple unit that loops internally (occupancy_producer.py's own
# run_forever), the same shape as sovereign-sigint's
# vhf-uhf-occupancy@.service.
# ---------------------------------------------------------------------
echo "-- Installing systemd --user service --"
mkdir -p "${SYSTEMD_USER_DIR}"

sed -e "s|__REPO_ROOT__|${REPO_ROOT}|g" \
    -e "s|__VENV_PYTHON__|${VENV_PYTHON}|g" \
    "${REPO_ROOT}/systemd/occupancy.service" > "${SYSTEMD_USER_DIR}/occupancy.service"

systemctl --user daemon-reload
systemctl --user enable --now occupancy.service

cat <<EOF

== Occupancy install complete ==

Service installed: continuous poll of the SIGedge gateway (see systemd/occupancy.service).
Check status:      systemctl --user status occupancy.service
View logs:          journalctl --user -u occupancy.service -f
Database:            /data/occupancy/occupancy.db

Next: run scripts/validate-occupancy.sh to confirm it's polling successfully.
EOF
