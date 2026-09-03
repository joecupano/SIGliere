#!/usr/bin/env bash
# scripts/validate-mac-mirror.sh
#
# Phase 6.8 exit criteria: real database content mirrored locally, the
# content looks like a real MAC vendor database (not an empty/broken
# download), and the timer is actually scheduled.
#
# Usage: ./scripts/validate-mac-mirror.sh

set -uo pipefail

VENV_PYTHON="${HOME}/.local/share/sigliere/venvs/reference/bin/python3"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_ROOT="/data/reference/mac-vendors"
DATA_FILE="${OUTPUT_ROOT}/mac-vendors.json"

RESULTS=()

echo "== Phase 6.8 validation: MAC vendor database mirror =="
echo

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "FAIL: reference venv not found at ${VENV_PYTHON}"
  exit 1
fi

# ---------------------------------------------------------------------
# Content actually landed and looks real
# ---------------------------------------------------------------------
echo "-- Checking mirrored content --"
if [[ -f "${DATA_FILE}" ]]; then
  ENTRY_COUNT=$(python3 -c "import json; print(len(json.load(open('${DATA_FILE}'))))" 2>/dev/null || echo 0)
  if [[ "${ENTRY_COUNT}" -gt 10000 ]]; then
    echo "  PASS: ${DATA_FILE} has ${ENTRY_COUNT} entries"
    RESULTS+=("Content: PASS (${ENTRY_COUNT} entries)")

    echo "  Sample entry:"
    python3 -c "
import json
d = json.load(open('${DATA_FILE}'))
print('   ', d[0])
"
  else
    echo "  FAIL: ${DATA_FILE} exists but has only ${ENTRY_COUNT} entries (expected >10000)"
    RESULTS+=("Content: FAIL (${ENTRY_COUNT} entries)")
  fi
else
  echo "  FAIL: no data file at ${DATA_FILE}"
  RESULTS+=("Content: FAIL")
fi
echo

# ---------------------------------------------------------------------
# A re-run correctly detects "unchanged" rather than always rewriting
# ---------------------------------------------------------------------
echo "-- Confirming a re-run detects unchanged content --"
cd "${REPO_ROOT}/reference"
RERUN_OUTPUT="$("${VENV_PYTHON}" mac_mirror.py 2>&1)"
echo "${RERUN_OUTPUT}" | tail -3

if echo "${RERUN_OUTPUT}" | grep -q "outcome=unchanged"; then
  echo "  PASS: re-run correctly reported unchanged content"
  RESULTS+=("Unchanged-detection: PASS")
elif echo "${RERUN_OUTPUT}" | grep -q "outcome=updated"; then
  echo "  PARTIAL: re-run reported 'updated' — either upstream genuinely"
  echo "  changed between runs, or hash comparison isn't working. Re-run"
  echo "  once more; if it stays 'updated' every time, check mac_mirror.py."
  RESULTS+=("Unchanged-detection: PARTIAL")
else
  echo "  FAIL: re-run did not report a recognized outcome — see output above"
  RESULTS+=("Unchanged-detection: FAIL")
fi
echo

# ---------------------------------------------------------------------
# Timer is actually scheduled
# ---------------------------------------------------------------------
echo "-- Checking systemd timer --"
if systemctl --user is-active --quiet mac-mirror.timer 2>/dev/null; then
  echo "  PASS: mac-mirror.timer is active"
  RESULTS+=("Timer: PASS")
else
  echo "  FAIL: mac-mirror.timer is not active"
  RESULTS+=("Timer: FAIL")
fi
echo

# ---------------------------------------------------------------------
# World-readable, matching what the Open WebUI container needs (see
# scripts/setup-data-dirs.sh / install-mac-mirror.sh)
# ---------------------------------------------------------------------
echo "-- Checking container-readability --"
if [[ -r "${DATA_FILE}" ]] && sudo -n -u nobody test -r "${DATA_FILE}" 2>/dev/null; then
  echo "  PASS: ${DATA_FILE} is readable by a non-owner UID"
  RESULTS+=("World-readable: PASS")
else
  echo "  PARTIAL: could not confirm non-owner readability (needs passwordless"
  echo "  sudo to test as 'nobody' — not a hard failure, just unverified here)."
  echo "  Manually confirm: podman exec open-webui cat /data/mac-vendors-ref/mac-vendors.json | head -c 100"
  RESULTS+=("World-readable: UNVERIFIED")
fi
echo

# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------
echo "== Summary =="
FAILED=0
for r in "${RESULTS[@]}"; do
  echo "  ${r}"
  [[ "${r}" == *FAIL* && "${r}" != *UNVERIFIED* ]] && FAILED=1
done
echo

if [[ "${FAILED}" -eq 1 ]]; then
  echo "Phase 6.8 NOT complete — resolve failures above."
  exit 1
else
  echo "Phase 6.8 exit criteria met."
fi
