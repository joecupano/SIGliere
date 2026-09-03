#!/usr/bin/env bash
# scripts/validate-os-packages.sh
#
# Host prerequisite exit criteria: real smoke tests, not
# just "apt install succeeded." Run as your normal user — NOT with sudo
# — since rootless Podman and venv creation both need to run as the
# actual user services will run as.
#
# Usage: ./scripts/validate-os-packages.sh

set -uo pipefail  # NOT -e — run both tests and report both results.

RESULTS=()

if [[ "$(id -u)" -eq 0 ]]; then
  echo "WARNING: running as root. Podman and venv checks below need to"
  echo "run as the real (non-root) user — results may not reflect what"
  echo "user services will actually see. Re-run without sudo."
  echo
fi

echo "== Host prerequisite validation =="
echo

# ---------------------------------------------------------------------
# Podman — rootless hello-world
# ---------------------------------------------------------------------
echo "-- Podman --"
if ! command -v podman >/dev/null 2>&1; then
  echo "  FAIL: podman not found — run scripts/install-os-packages.sh first"
  RESULTS+=("Podman: FAIL (not installed)")
else
  echo "  Running: podman run --rm hello-world"
  if timeout 60 podman run --rm hello-world 2>&1 | tee /tmp/sigliere-podman-validation.log; then
    echo "  PASS"
    RESULTS+=("Podman: PASS")
  else
    echo "  FAIL: see /tmp/sigliere-podman-validation.log"
    echo "  Common causes: missing subuid/subgid range, lingering not"
    echo "  enabled, cgroups v2 not active — see install-os-packages.sh"
    echo "  output for warnings from earlier."
    RESULTS+=("Podman: FAIL (see /tmp/sigliere-podman-validation.log)")
  fi
fi
echo

# ---------------------------------------------------------------------
# Python — venv creation + a real PyPI resolve
# ---------------------------------------------------------------------
echo "-- Python venv --"
VENV_TEST_DIR="$(mktemp -d /tmp/sigliere-venv-validation.XXXXXX)"
if python3 -m venv "${VENV_TEST_DIR}/venv" 2>&1 | tee /tmp/sigliere-venv-validation.log; then
  if "${VENV_TEST_DIR}/venv/bin/pip" install --quiet --upgrade pip 2>&1 | tee -a /tmp/sigliere-venv-validation.log \
     && "${VENV_TEST_DIR}/venv/bin/pip" install --quiet wheel 2>&1 | tee -a /tmp/sigliere-venv-validation.log; then
    echo "  PASS: venv created, pip resolved and installed from PyPI"
    RESULTS+=("Python venv: PASS")
  else
    echo "  FAIL: venv created but pip install failed — check network/PyPI access, see /tmp/sigliere-venv-validation.log"
    RESULTS+=("Python venv: FAIL (pip install failed)")
  fi
else
  echo "  FAIL: venv creation failed — likely missing python3-venv package"
  RESULTS+=("Python venv: FAIL (venv creation failed)")
fi
rm -rf "${VENV_TEST_DIR}"
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
  echo "Host prerequisite validation failed — resolve the failures above."
  exit 1
else
  echo "Host prerequisite exit criteria met."
fi
