#!/usr/bin/env bash
# scripts/validate-kismet-bridge.sh
#
# Kismet bridge exit criteria: the service is active, a manual poll cycle
# completes without error against the live gateway, and the database
# file exists with the expected schema. A device count staying at zero
# is NOT treated as failure — that's the honest state whenever no
# SIGedge node has kismet_host configured, no matching API key exists in
# SIGLIERE_GATEWAY_KISMET_CREDENTIALS_JSON, or no live Kismet instance is
# reachable — same posture validate-occupancy.sh takes toward an
# unreachable gateway.
#
# Usage: ./scripts/validate-kismet-bridge.sh

set -uo pipefail

VENV_PYTHON="${HOME}/.local/share/sigliere/venvs/kismet-bridge/bin/python3"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="/data/kismet-bridge/kismet_bridge.db"

RESULTS=()

echo "== Kismet bridge validation =="
echo

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "FAIL: kismet-bridge venv not found at ${VENV_PYTHON}"
  exit 1
fi

# ---------------------------------------------------------------------
# Service is actually running
# ---------------------------------------------------------------------
echo "-- Checking systemd service --"
if systemctl --user is-active --quiet kismet-bridge.service 2>/dev/null; then
  echo "  PASS: kismet-bridge.service is active"
  RESULTS+=("Service: PASS")
else
  echo "  FAIL: kismet-bridge.service is not active"
  RESULTS+=("Service: FAIL")
fi
echo

# ---------------------------------------------------------------------
# A manual poll cycle actually runs end to end against the live gateway
# ---------------------------------------------------------------------
echo "-- Running one manual poll cycle --"
cd "${REPO_ROOT}/kismet_bridge"
POLL_OUTPUT="$("${VENV_PYTHON}" kismet_bridge_producer.py --once 2>&1)"
POLL_STATUS=$?
echo "${POLL_OUTPUT}" | tail -5

if [[ "${POLL_STATUS}" -eq 0 ]]; then
  echo "  PASS: poll cycle completed without error"
  RESULTS+=("Poll cycle: PASS")
else
  echo "  FAIL: poll cycle exited ${POLL_STATUS} — check gateway.env and gateway reachability above"
  RESULTS+=("Poll cycle: FAIL")
fi
echo

# ---------------------------------------------------------------------
# Database exists with the expected schema
# ---------------------------------------------------------------------
echo "-- Checking database --"
if [[ -f "${DB_PATH}" ]]; then
  DEVICE_COUNT=$(python3 -c "
import sqlite3
conn = sqlite3.connect('${DB_PATH}')
print(conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0])
" 2>/dev/null)
  if [[ -n "${DEVICE_COUNT}" ]]; then
    echo "  PASS: ${DB_PATH} exists with a valid devices table (${DEVICE_COUNT} device(s) so far)"
    RESULTS+=("Database: PASS (${DEVICE_COUNT} devices)")
    if [[ "${DEVICE_COUNT}" -eq 0 ]]; then
      echo "  NOTE: 0 devices is expected until at least one node has kismet_host"
      echo "  configured, a matching API key, and a reachable live Kismet instance"
      echo "  during a poll — not itself a failure."
    fi
  else
    echo "  FAIL: ${DB_PATH} exists but the devices table could not be read"
    RESULTS+=("Database: FAIL")
  fi
else
  echo "  FAIL: ${DB_PATH} does not exist — did the poll cycle above run?"
  RESULTS+=("Database: FAIL")
fi
echo

# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------
echo "== Summary =="
FAILED=0
for r in "${RESULTS[@]}"; do
  echo "  ${r}"
  [[ "${r}" == *FAIL* ]] && FAILED=1
done
echo

if [[ "${FAILED}" -eq 1 ]]; then
  echo "Kismet bridge validation failed — resolve failures above."
  exit 1
else
  echo "Kismet bridge exit criteria met."
fi
