#!/usr/bin/env bash
# scripts/phase6-hackrf-occupancy-producer.sh
#
# Install the HackRF (2m, via radiod) occupancy producer as a continuous
# systemd --user service, and its supporting system-level radiod@hackrf-2m
# instance. Mirrors scripts/phase6-occupancy-producer.sh's RX-888 install
# pattern, with one addition: a compatibility gate. Whether a given
# installed radiod build exposes HackRF support depends on how it was built,
# so this script performs a dry-run config load first and stops with a
# specific fix command if the runtime cannot load the HackRF config.
#
# Two-layer install, in order:
#   1. System-level radiod@hackrf-2m.service (owns the USB device, needs
#      root — installs the config to /etc/radio/ and enables the instance)
#   2. --user radiod-occupancy-hackrf.service (the producer that reads
#      radiod's demodulated 2m channels and writes occupancy sightings)
#
# Usage: sudo ./scripts/phase6-hackrf-occupancy-producer.sh
#   Needs root for step 1 (system service + /etc/radio/ install), but must
#   also know which normal user owns the --user producer service — pass it
#   via TARGET_USER=you if sudo doesn't already know (SUDO_USER is used by
#   default when run as 'sudo ./script...').
#   Override the interpreter with VENV_PYTHON=... if needed (the producer
#   only needs the stdlib + db/occupancy_db.py, so system python3 is fine).

set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: this script installs a system-level radiod@hackrf-2m service" >&2
  echo "       and needs root for that half. Re-run with sudo." >&2
  exit 1
fi

TARGET_USER="${TARGET_USER:-${SUDO_USER:-}}"
if [[ -z "${TARGET_USER}" ]]; then
  echo "ERROR: could not determine which normal user should own the --user" >&2
  echo "       producer service. Re-run as 'sudo ./script...' (so SUDO_USER" >&2
  echo "       is set), or pass TARGET_USER=youruser explicitly." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${VENV_PYTHON:-$(command -v python3)}"
TARGET_UID="$(id -u "${TARGET_USER}")"
SYSTEMD_USER_DIR="$(getent passwd "${TARGET_USER}" | cut -d: -f6)/.config/systemd/user"
RADIOD_CONF_SRC="${REPO_ROOT}/ingest/ka9q-radio/radiod@hackrf-2m.conf"
RADIOD_CONF_DST="/etc/radio/radiod@hackrf-2m.conf"

echo "== HackRF (2m) radiod occupancy producer — two-layer install =="
echo "   Target user for --user service: ${TARGET_USER}"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "ERROR: python3 interpreter not found at ${VENV_PYTHON}" >&2
  exit 1
fi

# ---------------------------------------------------------------------
# GATE: verify that this host's installed radiod build can actually load
# the HackRF config before doing anything else. This avoids silently
# enabling the service when the runtime lacks HackRF support.
# ---------------------------------------------------------------------
echo "-- Field-verify: does this box's radiod support HackRF? --"
if ! command -v radiod >/dev/null 2>&1; then
  echo "ERROR: 'radiod' not found on PATH. Is ka9q-radio installed?" >&2
  echo "       Fix: install/build ka9q-radio first (see docs/ka9q-radio.md)." >&2
  exit 1
fi

if [[ ! -f "${RADIOD_CONF_SRC}" ]]; then
  echo "ERROR: config not found: ${RADIOD_CONF_SRC}" >&2
  exit 1
fi

mkdir -p /etc/radio
cp "${RADIOD_CONF_SRC}" "${RADIOD_CONF_DST}"

# Validate the config when the service is not already running. If
# radiod@hackrf-2m is already active, the device is already owned by the
# running instance and a direct load test would fail with "Resource busy";
# that is an expected condition here, not a deployment failure.
if systemctl is-active --quiet radiod@hackrf-2m; then
  echo "   OK: radiod@hackrf-2m is already active; skipping standalone load test."
else
  if ! radiod "${RADIOD_CONF_DST}" 2>/tmp/hackrf-radiod-verify.log; then
    echo "ERROR: radiod rejected radiod@hackrf-2m.conf on a config parse/load." >&2
    echo "       This usually means HackRF front-end support isn't available" >&2
    echo "       in your installed radiod build (see the notes.md caveat in" >&2
    echo "       ingest/ka9q-radio/radiod@hackrf-2m.conf's header)." >&2
    echo "       Details: /tmp/hackrf-radiod-verify.log" >&2
    echo "       Fix: rebuild ka9q-radio with HackRF support enabled (check" >&2
    echo "       for /usr/local/lib/ka9q-radio/hackrf* or a static hackrf" >&2
    echo "       symbol), then re-run this script." >&2
    exit 1
  fi
  echo "   OK: radiod accepted the HackRF config on load."
fi

# ---------------------------------------------------------------------
# Layer 1: system-level radiod@hackrf-2m instance.
# ---------------------------------------------------------------------
echo "-- Installing system service radiod@hackrf-2m --"
systemctl daemon-reload
systemctl enable --now radiod@hackrf-2m

sleep 2
if ! systemctl is-active --quiet radiod@hackrf-2m; then
  echo "ERROR: radiod@hackrf-2m did not stay active after enable." >&2
  echo "       Check: journalctl -u radiod@hackrf-2m --no-pager -n 40" >&2
  echo "       Common cause: HackRF held by OpenWebRX+, or a USB permissions" >&2
  echo "       issue (see scripts/sdr-mode.sh hackrf status)." >&2
  exit 1
fi
echo "   OK: radiod@hackrf-2m active."

# ---------------------------------------------------------------------
# Layer 2: --user producer service, installed for TARGET_USER.
# ---------------------------------------------------------------------
echo "-- Installing --user service radiod-occupancy-hackrf.service --"
sudo -u "${TARGET_USER}" mkdir -p "${SYSTEMD_USER_DIR}"

sed -e "s|__REPO_ROOT__|${REPO_ROOT}|g" \
    -e "s|__VENV_PYTHON__|${VENV_PYTHON}|g" \
    "${REPO_ROOT}/systemd/radiod-occupancy-hackrf.service" \
    > "${SYSTEMD_USER_DIR}/radiod-occupancy-hackrf.service"
chown "${TARGET_USER}" "${SYSTEMD_USER_DIR}/radiod-occupancy-hackrf.service"

sudo -u "${TARGET_USER}" \
    XDG_RUNTIME_DIR="/run/user/${TARGET_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${TARGET_UID}/bus" \
    systemctl --user daemon-reload

sudo -u "${TARGET_USER}" \
    XDG_RUNTIME_DIR="/run/user/${TARGET_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${TARGET_UID}/bus" \
    systemctl --user enable --now radiod-occupancy-hackrf.service

sleep 2
PROD_STATE=$(sudo -u "${TARGET_USER}" \
    XDG_RUNTIME_DIR="/run/user/${TARGET_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${TARGET_UID}/bus" \
    systemctl --user is-active radiod-occupancy-hackrf.service 2>/dev/null || echo "inactive")

if [[ "${PROD_STATE}" != "active" ]]; then
  echo "ERROR: radiod-occupancy-hackrf.service did not stay active." >&2
  echo "       Check: journalctl --user -u radiod-occupancy-hackrf.service --no-pager -n 40" >&2
  exit 1
fi
echo "   OK: radiod-occupancy-hackrf.service active."

# ---------------------------------------------------------------------
# Lingering, same rationale as phase6-occupancy-producer.sh: a
# continuous --user service needs this or it stops at logout.
# ---------------------------------------------------------------------
if ! loginctl show-user "${TARGET_USER}" -p Linger --value 2>/dev/null | grep -q yes; then
  echo "-- Enabling lingering for ${TARGET_USER} so the service survives logout --"
  loginctl enable-linger "${TARGET_USER}" || \
    echo "   NOTE: could not enable lingering; the service will stop at logout."
fi

OCC_DB="${REPO_ROOT}/db/occupancy.db"
echo
echo "== HackRF (2m) radiod occupancy producer installed =="
echo "radiod status:    systemctl status radiod@hackrf-2m"
echo "Producer status:  systemctl --user status radiod-occupancy-hackrf.service"
echo "Producer logs:    journalctl --user -u radiod-occupancy-hackrf.service -f"
echo "Free HackRF for OpenWebRX+:  sudo ./scripts/sdr-mode.sh hackrf interactive"
echo
echo "The threshold (-30 dBFS) is still a placeholder for field calibration:"
echo "  ${VENV_PYTHON} ${REPO_ROOT}/decode/radiod_occupancy_producer.py \\"
echo "      --device hackrf --once --verbose"
echo "against a known-quiet vs. known-active channel (e.g. key up 146.520"
echo "during a local net), then set --threshold-dbfs in the service file if"
echo "you want the producer to be stricter about what counts as active."
echo
echo "Confirm sightings are accumulating:"
echo "  sqlite3 ${OCC_DB} \"SELECT COUNT(*) FROM sightings WHERE source_type='radiod-hackrf';\""
