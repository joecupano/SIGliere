#!/usr/bin/env bash
# scripts/install-sigid-mirror.sh
#
# Optional — SigID mirror. See INSTALL.md Phase 6. Sets up
# the /data/reference/sigid layout, ensures the reference venv
# has `requests` (reference/sigid_mirror.py's only new dependency), and
# installs a systemd --user timer for weekly incremental sync.
#
# Run as your normal user, NOT with sudo — same rootless pattern as
# Phases 2/4/5.
#
# This script sets up the SCHEDULE. It also runs one sync immediately
# so there's real data to validate against — run
# scripts/validate-sigid-mirror.sh afterward.
#
# Usage: ./scripts/install-sigid-mirror.sh

set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Do not run this as root/sudo — the venv and systemd --user timer" >&2
  echo "need to be owned by and run as your normal user. Re-run without sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${HOME}/.local/share/sigliere/venvs/reference/bin/python3"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

echo "== Phase 6.3: SigID mirror =="

# ---------------------------------------------------------------------
# The optional reference venv is kept separate from the gateway image.
# ensures it's current with reference/requirements.txt (which now
# includes `requests` again, for this specifically — see that file's
# comment for why that's not a walk-back of the earlier removal).
# ---------------------------------------------------------------------
echo "-- Updating reference venv --"
"${REPO_ROOT}/scripts/setup-venvs.sh" reference

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "ERROR: expected venv interpreter not found at ${VENV_PYTHON}" >&2
  exit 1
fi

# ---------------------------------------------------------------------
# /data/reference/sigid layout — created up front by
# scripts/install-corpus-dirs.sh (run during host prerequisites, before
# any of this), not here. Check rather than assume, so a skipped step
# fails with a clear message instead of a confusing one later.
# ---------------------------------------------------------------------
for d in /data/reference/sigid/images /data/reference/sigid/audio /data/reference/sigid/metadata; do
  if [[ ! -d "${d}" ]]; then
    echo "ERROR: ${d} does not exist." >&2
    echo "       Run scripts/install-corpus-dirs.sh first." >&2
    exit 1
  fi
done

# ---------------------------------------------------------------------
# systemd --user timer
# ---------------------------------------------------------------------
echo "-- Installing systemd --user timer --"
mkdir -p "${SYSTEMD_USER_DIR}"

sed -e "s|__REPO_ROOT__|${REPO_ROOT}|g" \
    -e "s|__VENV_PYTHON__|${VENV_PYTHON}|g" \
    "${REPO_ROOT}/systemd/sigid-mirror.service" > "${SYSTEMD_USER_DIR}/sigid-mirror.service"

cp "${REPO_ROOT}/systemd/sigid-mirror.timer" "${SYSTEMD_USER_DIR}/sigid-mirror.timer"

systemctl --user daemon-reload
systemctl --user enable --now sigid-mirror.timer

# ---------------------------------------------------------------------
# Run one sync now (bootstrap) so there's something to validate
# ---------------------------------------------------------------------
echo "-- Running initial bootstrap sync (this enumerates the whole wiki" 
echo "   on first run — may take a while) --"
cd "${REPO_ROOT}/reference"
"${VENV_PYTHON}" sigid_mirror.py

cat <<EOF

== Phase 6.3 install complete ==

Timer installed: incremental sync runs weekly (see systemd/sigid-mirror.timer).
Check status:     systemctl --user status sigid-mirror.timer
Run manually any time: systemctl --user start sigid-mirror.service
View logs:         journalctl --user -u sigid-mirror.service -f

Next: run scripts/validate-sigid-mirror.sh to confirm real
content landed in /data/reference/sigid.
EOF
