#!/usr/bin/env bash
# scripts/validate-occupancy.sh
#
# Occupancy exit criteria: the service is active, a manual poll cycle
# completes without error against the live gateway, and the database
# file exists with the expected schema. Sighting counts staying at
# zero is NOT treated as failure — that's the honest state whenever no
# SIGedge node is actually reachable (dry-run gateway, no live SIGedge,
# or an all-quiet band), same posture as validate-tiered.sh toward an
# unreachable gateway.
#
# Usage: ./scripts/validate-occupancy.sh

set -uo pipefail

VENV_PYTHON="${HOME}/.local/share/sigliere/venvs/occupancy/bin/python3"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="/data/occupancy/occupancy.db"

RESULTS=()

echo "== Occupancy validation =="
echo

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "FAIL: occupancy venv not found at ${VENV_PYTHON}"
  exit 1
fi

# ---------------------------------------------------------------------
# Service is actually running
# ---------------------------------------------------------------------
echo "-- Checking systemd service --"
if systemctl --user is-active --quiet occupancy.service 2>/dev/null; then
  echo "  PASS: occupancy.service is active"
  RESULTS+=("Service: PASS")
else
  echo "  FAIL: occupancy.service is not active"
  RESULTS+=("Service: FAIL")
fi
echo

# ---------------------------------------------------------------------
# A manual poll cycle actually runs end to end against the live gateway
# ---------------------------------------------------------------------
echo "-- Running one manual poll cycle --"
cd "${REPO_ROOT}/occupancy"
POLL_OUTPUT="$("${VENV_PYTHON}" occupancy_producer.py --once 2>&1)"
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
  SIGNAL_COUNT=$(python3 -c "
import sqlite3
conn = sqlite3.connect('${DB_PATH}')
print(conn.execute('SELECT COUNT(*) FROM signals').fetchone()[0])
" 2>/dev/null)
  if [[ -n "${SIGNAL_COUNT}" ]]; then
    echo "  PASS: ${DB_PATH} exists with a valid signals table (${SIGNAL_COUNT} signal(s) so far)"
    RESULTS+=("Database: PASS (${SIGNAL_COUNT} signals)")
    if [[ "${SIGNAL_COUNT}" -eq 0 ]]; then
      echo "  NOTE: 0 signals is expected until a live, reachable SIGedge node has an"
      echo "  active channel during a poll — not itself a failure."
    fi
  else
    echo "  FAIL: ${DB_PATH} exists but the signals table could not be read"
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
  echo "Occupancy validation failed — resolve failures above."
  exit 1
else
  echo "Occupancy exit criteria met."
fi
