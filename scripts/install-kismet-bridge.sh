#!/usr/bin/env bash
# scripts/install-kismet-bridge.sh
#
# Optional Kismet bridge service. Sets up the kismet-bridge venv, installs
# a systemd --user unit that polls the SIGedge gateway's curated
# /kismet/summary/{node} and /kismet/devices/{node} endpoints continuously
# and mirrors devices into /data/kismet-bridge/kismet_bridge.db, and
# starts it.
#
# Depends on the gateway already being installed (scripts/install-sigedge-gateway.sh)
# — kismet_bridge_producer.py reads its bearer token from
# ~/.config/sigliere/gateway.env, the same file that installer generates.
# It also depends on at least one node in gateway/config/nodes.json having
# kismet_host set and a matching entry in
# SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON — see gateway/README.md's
# "Kismet bridge" section and KISMET-BRIDGE.md. Neither is required for
# this script to install successfully; without them the service simply
# has nothing to poll (0 devices, same "honest empty state" posture
# validate-occupancy.sh takes toward an unreachable gateway).
#
# Run as your normal user, NOT with sudo — same rootless pattern as
# other rootless user services.
#
# Usage: ./scripts/install-kismet-bridge.sh

set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Do not run this as root/sudo — the venv and systemd --user service" >&2
  echo "need to be owned by and run as your normal user. Re-run without sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${HOME}/.local/share/sigliere/venvs/kismet-bridge/bin/python3"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
GATEWAY_ENV="${HOME}/.config/sigliere/gateway.env"

echo "== Kismet bridge service =="

# ---------------------------------------------------------------------
# Gateway dependency
# ---------------------------------------------------------------------
if [[ ! -r "${GATEWAY_ENV}" ]]; then
  echo "ERROR: ${GATEWAY_ENV} not found." >&2
  echo "       Run scripts/install-sigedge-gateway.sh first — kismet_bridge_producer.py" >&2
  echo "       authenticates to the gateway with the analyst token it generates." >&2
  exit 1
fi

if ! grep -q "SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON" "${GATEWAY_ENV}"; then
  echo "NOTE: ${GATEWAY_ENV} has no SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON line."
  echo "      The service will install and run, but every node will 409 until"
  echo "      you add kismet_host/kismet_port to gateway/config/nodes.json and"
  echo "      a matching API key here — see gateway/README.md's 'Kismet bridge'"
  echo "      section."
fi

# ---------------------------------------------------------------------
# kismet-bridge venv
# ---------------------------------------------------------------------
echo "-- Installing kismet-bridge venv --"
"${REPO_ROOT}/scripts/setup-venvs.sh" kismet-bridge

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "ERROR: expected venv interpreter not found at ${VENV_PYTHON}" >&2
  exit 1
fi

# ---------------------------------------------------------------------
# /data/kismet-bridge — created up front by scripts/install-corpus-dirs.sh,
# not here. Check rather than assume, same pattern as install-occupancy.sh.
# ---------------------------------------------------------------------
if [[ ! -d /data/kismet-bridge ]]; then
  echo "ERROR: /data/kismet-bridge does not exist." >&2
  echo "       Run scripts/install-corpus-dirs.sh first." >&2
  exit 1
fi

# ---------------------------------------------------------------------
# systemd --user service — continuous poller, same shape as occupancy.service.
# ---------------------------------------------------------------------
echo "-- Installing systemd --user service --"
mkdir -p "${SYSTEMD_USER_DIR}"

sed -e "s|__REPO_ROOT__|${REPO_ROOT}|g" \
    -e "s|__VENV_PYTHON__|${VENV_PYTHON}|g" \
    "${REPO_ROOT}/systemd/kismet-bridge.service" > "${SYSTEMD_USER_DIR}/kismet-bridge.service"

systemctl --user daemon-reload
systemctl --user enable --now kismet-bridge.service

cat <<EOF

== Kismet bridge install complete ==

Service installed: continuous poll of the SIGedge gateway's Kismet endpoints
                    (see systemd/kismet-bridge.service).
Check status:       systemctl --user status kismet-bridge.service
View logs:          journalctl --user -u kismet-bridge.service -f
Database:           /data/kismet-bridge/kismet_bridge.db

Next: run scripts/validate-kismet-bridge.sh to confirm it's polling successfully.
EOF
