#!/usr/bin/env bash
# scripts/phase4-open-webui.sh
#
# Phase 4 — Open WebUI (Podman container), fronted by Caddy. See
# docs/build-order.md for full rationale.
#
# Deploys rootless — Quadlet units go under
# ~/.config/containers/systemd/, managed by `systemctl --user`. Run this
# as your normal user, NOT with sudo (Phase 2 already set up the
# subuid/subgid range and lingering this needs).
#
# This script INSTALLS. Run scripts/phase4-validate.sh afterward.
#
# Usage: ./scripts/phase4-open-webui.sh

set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Do not run this as root/sudo — rootless Quadlet units need to be" >&2
  echo "owned by and run as your normal user. Re-run without sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUADLET_DIR="${HOME}/.config/containers/systemd"

echo "== Phase 4: Open WebUI + Caddy =="

mkdir -p "${QUADLET_DIR}"

# Ensure the Kismet and occupancy data sources exist and are wired to run
# before Open WebUI starts. This prevents the chat tool from seeing an empty
# or stale mount when the container is restarted or the machine boots.
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
mkdir -p "${SYSTEMD_USER_DIR}"
mkdir -p "${HOME}/.config/systemd/user/open-webui.service.d"

# The Quadlet mounts a HOME-relative, REPO_ROOT-independent path
# (~/sovereign-sigint/{db,kismet-data}) into the container, so the
# container-side tool config never has to know where the repo happens to
# be cloned. Point those paths at the repo's LIVE data via symlinks, not
# a one-time copy — a real bug, found and fixed 2026-08-11: this used to
# `cp db/occupancy.db` once here and never again, which silently froze
# the occupancy native tool's view from that instant forward while the
# real radiod-occupancy producer kept growing db/occupancy.db underneath
# it (confirmed live: the two diverged by 1000+ rows within the same
# session). kismet-data had no seeding at all, so a truly fresh install
# hit the "don't exist yet" hard-fail below every time — nothing in this
# repo has ever written to ~/sovereign-sigint/kismet-data;
# scripts/kismet-refresh.sh always writes to ${REPO_ROOT}/kismet-data.
mkdir -p "${REPO_ROOT}/db" "${REPO_ROOT}/kismet-data"
for name in db kismet-data; do
  link="${HOME}/sovereign-sigint/${name}"
  target="${REPO_ROOT}/${name}"
  mkdir -p "$(dirname "${link}")"
  if [[ -L "${link}" ]]; then
    # Already a symlink — repoint only if it's wrong; don't touch a
    # correct one just to avoid spurious churn on repeat runs.
    [[ "$(readlink -f "${link}")" == "$(readlink -f "${target}")" ]] || \
      ln -sfn "${target}" "${link}"
  elif [[ -e "${link}" ]]; then
    echo "NOTE: ${link} exists as a real directory, not a symlink — leaving" >&2
    echo "it alone (may be pre-existing data worth checking by hand). If" >&2
    echo "it's just a stale derivative copy, replace it with:" >&2
    echo "  rm -rf ${link} && ln -s ${target} ${link}" >&2
  else
    ln -s "${target}" "${link}"
  fi
done

# Install the Kismet staging unit if it isn't present yet (phase 7 normally
# owns this, but phase 4 now seeds it so the startup path is robust even if
# the timer step hasn't run yet).
sed -e "s|__REPO_ROOT__|${REPO_ROOT}|g" \
    "${REPO_ROOT}/systemd/kismet-refresh.service" \
    > "${SYSTEMD_USER_DIR}/kismet-refresh.service"
cp "${REPO_ROOT}/systemd/kismet-refresh.timer" \
   "${SYSTEMD_USER_DIR}/kismet-refresh.timer"

cat > "${HOME}/.config/systemd/user/open-webui.service.d/10-kismet-refresh.conf" <<'EOF'
[Unit]
Wants=kismet-refresh.service
After=kismet-refresh.service
EOF

# ---------------------------------------------------------------------
# Verify the host-side mount sources the Open WebUI Quadlet expects
# actually exist. Silent-failure symptom (verified on rubberduck this
# session): if a bind-mount source doesn't exist on the host, Podman
# either mounts nothing or the container sees an empty directory --
# tools then honestly report "no data" and the operator has no clear
# error to chase back. Fail loud here instead, before daemon-reload.
# ---------------------------------------------------------------------
REQUIRED_MOUNT_SOURCES=(
  "/data/audio"                        # whisper tool
  "/data/rag"                          # RAG uploads
  "/data/reference/sigid"              # SigID native tool
  "${HOME}/sovereign-sigint/db"        # occupancy native tool
  "${HOME}/sovereign-sigint/kismet-data"  # Kismet native tool
)
missing_mounts=()
for d in "${REQUIRED_MOUNT_SOURCES[@]}"; do
  [[ -d "$d" ]] || missing_mounts+=("$d")
done
if (( ${#missing_mounts[@]} > 0 )); then
  echo "ERROR: the Open WebUI Quadlet template mounts these host paths, but they" >&2
  echo "don't exist yet:" >&2
  for d in "${missing_mounts[@]}"; do echo "    ${d}" >&2; done
  echo >&2
  echo "Create them first. For the /data/* set, run the shipped setup script:" >&2
  echo "    sudo ./scripts/setup-data-dirs.sh" >&2
  echo "which creates the whole /data/{audio,rag,corpus,imagery,models,reference," >&2
  echo "signals} tree with correct ownership. For the ~/sovereign-sigint/ set," >&2
  echo "run the phases that own them (phase 6 occupancy, phase 7 kismet-refresh) --" >&2
  echo "or 'mkdir -p' them manually if you're intentionally staging early." >&2
  exit 1
fi

# ---------------------------------------------------------------------
# Install one Quadlet unit or Caddyfile from a repo template. Safe to
# re-run: never blindly overwrites, always shows what changed.
#
# The problem this solves (verified twice tonight): repo template
# containers/open-webui.container was updated to add new mount lines,
# but 'git pull' does NOT push those changes to the operator's INSTALLED
# copy at ~/.config/containers/systemd/open-webui.container. The
# installed file was a plain copy from the last run of this script, not
# a symlink. Result: operators saw phase 4 as "done" and didn't know
# their installed Quadlet was drifting from the shipped template.
#
# This helper closes the gap without being destructive:
#   - Fresh install: copy without prompting (the original behavior).
#   - Installed == template: skip and say so (no-op is visible).
#   - Installed != template: backup the current file with a timestamp
#     suffix, then copy the new template in, and print a short diff so
#     the operator can review. If they had local hand-edits, the backup
#     is right next to the installed file and their custom mounts /
#     env vars are easy to re-apply.
# ---------------------------------------------------------------------
install_quadlet_file() {
  local template="$1" installed="$2"
  local name; name=$(basename "$template")
  if [[ ! -f "$installed" ]]; then
    echo "  ${name}: fresh install"
    cp "$template" "$installed"
    return 0
  fi
  if cmp -s "$template" "$installed"; then
    echo "  ${name}: already matches template, no change"
    return 0
  fi
  local backup="${installed}.bak.$(date +%Y%m%d-%H%M%S)"
  echo "  ${name}: differs from template — updating"
  echo "    backup:    ${backup}"
  cp "$installed" "$backup"
  cp "$template" "$installed"
  echo "    diff (backup -> new):"
  diff -u "$backup" "$installed" 2>/dev/null | sed 's/^/      /' | head -40 || true
  echo "    (If you had local customizations in the backup — extra Volume=,"
  echo "     Environment= etc. — re-apply them to the installed file and re-run"
  echo "     'systemctl --user daemon-reload && systemctl --user restart <unit>'.)"
}

echo "-- Installing Quadlet units and Caddyfile to ${QUADLET_DIR} --"
install_quadlet_file "${REPO_ROOT}/containers/open-webui.container" \
                     "${QUADLET_DIR}/open-webui.container"
install_quadlet_file "${REPO_ROOT}/containers/caddy.container" \
                     "${QUADLET_DIR}/caddy.container"

# Caddyfile: plain HTTP by default, local-CA HTTPS opt-in via CADDY_TLS=1.
#   CADDY_TLS=1 ./scripts/phase4-open-webui.sh    → local-CA HTTPS on :8443
#   CADDY_TLS=cert CADDY_CERT=/path/fullchain.pem CADDY_KEY=/path/key.pem \
#     CADDY_HOSTNAME=host.example.com ./scripts/phase4-open-webui.sh
#                                                 → HTTPS on :8443 with YOUR cert
#   ./scripts/phase4-open-webui.sh                → HTTP on :8000 (default)
#
# HTTP is the default deliberately: for a single-operator box on a
# trusted LAN with no DNS, plain HTTP is a legitimate, simpler choice,
# and the TLS path carries real caveats (client-side CA trust, hostname
# resolution without DNS) documented in docs/security-hardening.md.
#
# CADDY_TLS=cert is for operators who ALREADY have a certificate — from
# an internal/corporate CA, an existing wildcard, or their own PKI — and
# want to use it instead of Caddy's self-signed local CA. The advantage:
# if that cert chains to a CA the clients ALREADY trust (e.g. a corporate
# root pushed to every machine), there's no per-client trust step at all.
if [[ "${CADDY_TLS:-0}" == "cert" ]]; then
  # Bring-your-own-certificate mode.
  : "${CADDY_CERT:?CADDY_TLS=cert requires CADDY_CERT=/path/to/fullchain.pem}"
  : "${CADDY_KEY:?CADDY_TLS=cert requires CADDY_KEY=/path/to/privkey.pem}"
  CADDY_HOST="${CADDY_HOSTNAME:-$(hostname).local}"

  if [[ ! -r "${CADDY_CERT}" ]]; then
    echo "ERROR: cert file not readable: ${CADDY_CERT}" >&2; exit 1
  fi
  if [[ ! -r "${CADDY_KEY}" ]]; then
    echo "ERROR: key file not readable: ${CADDY_KEY}" >&2; exit 1
  fi

  echo "   CADDY_TLS=cert — using your certificate for ${CADDY_HOST}:8443"
  # Copy the cert/key into a stable location the container mounts, rather
  # than mounting the user's arbitrary source paths directly (which may
  # live somewhere the rootless container can't traverse). 0600 key.
  CERT_DIR="${HOME}/.config/containers/systemd/caddy-certs"
  mkdir -p "${CERT_DIR}"
  cp "${CADDY_CERT}" "${CERT_DIR}/cert.pem"
  cp "${CADDY_KEY}"  "${CERT_DIR}/key.pem"
  chmod 0600 "${CERT_DIR}/key.pem"
  chmod 0644 "${CERT_DIR}/cert.pem"

  # Ensure the container mounts the cert dir. Add the Volume line to the
  # unit if not already present (idempotent).
  if ! grep -q "caddy-certs:/etc/caddy/certs" "${QUADLET_DIR}/caddy.container"; then
    # Insert the mount right after the Caddyfile volume line.
    sed -i '/Volume=%h\/.config\/containers\/systemd\/Caddyfile/a Volume=%h/.config/containers/systemd/caddy-certs:/etc/caddy/certs:ro' \
      "${QUADLET_DIR}/caddy.container"
  fi

  # auto_https disable_redirects still required (same :80-bind reason as
  # the local-CA path — Caddy auto-opens :80 for the redirect otherwise).
  cat > "${QUADLET_DIR}/Caddyfile" <<EOF
# Caddyfile — sovereign-sigint (operator-provided cert, generated by phase4)
{
	auto_https disable_redirects
}

${CADDY_HOST}:8443 {
	tls /etc/caddy/certs/cert.pem /etc/caddy/certs/key.pem
	reverse_proxy 127.0.0.1:8080
}
EOF
  echo "   NOTE: clients reach this at https://${CADDY_HOST}:8443"
  echo "   If ${CADDY_HOST} isn't in DNS, ensure clients can resolve it"
  echo "   (hosts file or DNS). No per-client CA trust step is needed IF"
  echo "   your cert chains to a CA the clients already trust."
elif [[ "${CADDY_TLS:-0}" == "1" ]]; then
  CADDY_HOST="$(hostname).local"
  echo "   CADDY_TLS=1 set — generating local-CA HTTPS config for ${CADDY_HOST}:8443"
  # The global 'auto_https disable_redirects' block is REQUIRED, not
  # optional: 'tls internal' otherwise makes Caddy auto-open privileged
  # :80 for the HTTP->HTTPS redirect, which rootless Podman cannot bind
  # ("listening on :80: bind: permission denied"), crashing Caddy on
  # startup despite the site block being :8443. This was a real,
  # diagnosed bug — do not remove this block.
  cat > "${QUADLET_DIR}/Caddyfile" <<EOF
# Caddyfile — sovereign-sigint (local-CA HTTPS, generated by phase4)
{
	auto_https disable_redirects
}

${CADDY_HOST}:8443 {
	tls internal
	reverse_proxy 127.0.0.1:8080
}
EOF
  echo "   NOTE: clients reach this at https://${CADDY_HOST}:8443"
  echo "   Without DNS, add '<this-box-ip> ${CADDY_HOST}' to each client's"
  echo "   hosts file, and trust Caddy's local CA to avoid browser warnings"
  echo "   (extraction steps in docs/security-hardening.md)."
else
  echo "   Plain HTTP on :8000 (default; set CADDY_TLS=1 for local-CA HTTPS)"
  install_quadlet_file "${REPO_ROOT}/containers/Caddyfile" \
                       "${QUADLET_DIR}/Caddyfile"
fi

# Sanity check: /data/rag must exist and be writable before Open WebUI
# starts, or the bind mount in open-webui.container fails outright.
if [[ ! -d /data/rag ]]; then
  echo "ERROR: /data/rag does not exist. Run scripts/setup-data-dirs.sh first." >&2
  exit 1
fi

echo "-- Reloading systemd user units --"
systemctl --user daemon-reload
# Run the Kismet staging step once now so the mounted file is populated
# before Open WebUI starts.
"${REPO_ROOT}/scripts/kismet-refresh.sh" || true
echo "-- Starting Open WebUI and Caddy --"
# Quadlet-generated units are transient/generator-produced — systemctl
# enable fails on them ("is transient or generated"), confirmed via a
# real install. Enablement already happened automatically at generation
# time via each .container file's own [Install] section
# (WantedBy=default.target) — just start them.
systemctl --user start open-webui.service
systemctl --user start caddy.service

echo "Waiting for Open WebUI to come up..."
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/ >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo
echo "== Phase 4 install complete =="
echo
echo "Next: run scripts/phase4-validate.sh to confirm Open WebUI is actually"
echo "reachable (direct and via Caddy) and can talk to Ollama."
echo

# Reflect the DEPLOYED Caddyfile's actual state (in QUADLET_DIR), not the
# repo copy — the TLS paths generate their config directly to the deployed
# location, so checking the repo file would misreport when TLS is on.
# NOTE: strip comment lines before matching — the plain-HTTP Caddyfile ships a
# commented example containing "tls internal", and matching that would wrongly
# print the HTTPS message even though the active config is plain :8000.
DEPLOYED_ACTIVE="$(grep -v '^[[:space:]]*#' "${QUADLET_DIR}/Caddyfile" 2>/dev/null)"
if echo "${DEPLOYED_ACTIVE}" | grep -q "tls /etc/caddy/certs"; then
  echo "Caddy is configured for HTTPS on :8443 using your provided certificate."
  echo "No per-client CA trust step is needed if that cert chains to a CA"
  echo "your clients already trust; otherwise trust its issuing CA per client."
elif echo "${DEPLOYED_ACTIVE}" | grep -q "tls internal"; then
  echo "Caddy is configured for HTTPS via local CA on :8443."
  echo "Browsers will warn until the local root CA is trusted on each client —"
  echo "see docs/security-hardening.md for the extraction and trust steps."
else
  echo "Reminder: Caddy is on plain HTTP (:8000) by default — not :80, since"
  echo "rootless Podman can't bind privileged ports without a system-wide"
  echo "policy change (confirmed via a real install) — see"
  echo "containers/Caddyfile for how to add HTTPS if/when this needs it."
fi
