#!/usr/bin/env bash
# scripts/phase6-mcp-server-install.sh
#
# Phase 6.9 — Sigliere MCP server (role-aware radiod control plane). See
# docs/build-order.md Phase 6 and mcp-server/README.md.
#
# Builds the container image, installs the host env file and Podman
# Quadlet unit, and starts sigliere-mcp.service as a systemd --user
# service. Safe to re-run: rebuilds the image and restarts the service to
# pick up code/config changes, but never overwrites an existing
# ~/.config/sigliere/mcp.env (it holds live bearer tokens).
#
# Run as your normal user, NOT with sudo — same rootless --user pattern as
# the other Podman Quadlet services (Caddy, Open WebUI).
#
# Usage: ./scripts/phase6-mcp-server-install.sh
#   Run scripts/phase6-mcp-server-validate.sh afterward for an end-to-end
#   dry-run smoke test in a separate throwaway container.

set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Do not run this as root/sudo — the systemd --user service must be" >&2
  echo "owned by and run as your normal user. Re-run without sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="localhost/sigliere-mcp:latest"
ENV_DIR="${HOME}/.config/sigliere"
ENV_FILE="${ENV_DIR}/mcp.env"
QUADLET_DIR="${HOME}/.config/containers/systemd"
HOST="127.0.0.1"
PORT="8140"

echo "== Phase 6.9: Sigliere MCP server (radiod control plane) =="

# ---------------------------------------------------------------------
# Image — always rebuild so a re-run picks up source/config changes, same
# as re-running any other phase install script.
# ---------------------------------------------------------------------
echo "-- Building image: ${IMAGE} --"
podman build -f "${REPO_ROOT}/mcp-server/Containerfile" -t "${IMAGE}" "${REPO_ROOT}"

# ---------------------------------------------------------------------
# Host env file — created from the template only if missing. Never
# overwritten on re-run: it holds the live bearer-token map, and an
# operator may have already flipped SIGLIERE_MCP_DRY_RUN to false here
# after validating live control (see docs/mcp-validation-evidence.md).
# ---------------------------------------------------------------------
mkdir -p "${ENV_DIR}"
if [[ -f "${ENV_FILE}" ]]; then
  echo "-- Env file already exists, leaving it as-is: ${ENV_FILE} --"
else
  echo "-- Creating env file from template: ${ENV_FILE} --"
  cp "${REPO_ROOT}/mcp-server/mcp.env.example" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  echo "   NOTE: installed with SIGLIERE_MCP_DRY_RUN=true and the example"
  echo "   analyst-token/operator-token pair. Replace those tokens before"
  echo "   exposing this beyond loopback, and only flip DRY_RUN to false"
  echo "   after validating live control on your own nodes — see"
  echo "   mcp-server/README.md and docs/mcp-validation-evidence.md."
fi

# ---------------------------------------------------------------------
# Preflight warning (don't fail) — same check phase6-openapi-tools.sh does
# for :8130. Open WebUI validates a Tool Server connection from your
# BROWSER, not from the container, so it must reach the host's LAN IP on
# this port even though localhost/in-container curls to it already work.
# ---------------------------------------------------------------------
if ! sudo -n ufw status 2>/dev/null | grep -q "${PORT}/tcp"; then
  echo "NOTE: ufw may have no ${PORT}/tcp allow rule (could not confirm"
  echo "      without a cached sudo credential — check yourself with:"
  echo "      sudo ufw status | grep ${PORT}). Open WebUI validates a Tool"
  echo "      Server connection from your BROWSER, which must reach the"
  echo "      LAN IP:${PORT} — this succeeds from localhost/in-container"
  echo "      even when ufw blocks it from elsewhere on the LAN. If the"
  echo "      Admin Panel connection test fails, run:"
  echo "      sudo ufw allow ${PORT}/tcp"
fi

# ---------------------------------------------------------------------
# Quadlet unit
# ---------------------------------------------------------------------
echo "-- Installing Quadlet unit --"
mkdir -p "${QUADLET_DIR}"
cp "${REPO_ROOT}/containers/sigliere-mcp.container" "${QUADLET_DIR}/sigliere-mcp.container"

systemctl --user daemon-reload
# Quadlet-generated units are transient/generated — `systemctl --user
# enable` refuses them ("Unit is transient or generated"). Start-on-boot
# instead comes from the [Install] WantedBy=default.target already baked
# into containers/sigliere-mcp.container; the generator wires that up on
# every daemon-reload. `restart` (not `start`) so a re-run also picks up
# a rebuilt image or an edited quadlet/env file.
systemctl --user restart sigliere-mcp.service

# ---------------------------------------------------------------------
# Lingering so the --user service survives logout / starts at boot,
# same as the other continuous --user services in this build.
# ---------------------------------------------------------------------
if command -v loginctl >/dev/null 2>&1; then
  if ! loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null | grep -q yes; then
    echo "-- Enabling lingering (requires sudo once) --"
    sudo loginctl enable-linger "$(id -un)" || \
      echo "   NOTE: could not enable lingering; service will stop at logout."
  fi
fi

# ---------------------------------------------------------------------
# Wait for health, using whichever tokens are actually in the env file
# (falls back to the template's example tokens if not found there).
# ---------------------------------------------------------------------
ANALYST_TOKEN="$(grep -oP '"\K[^"]+(?="\s*:\s*"analyst")' "${ENV_FILE}" 2>/dev/null | head -1)"
ANALYST_TOKEN="${ANALYST_TOKEN:-analyst-token}"

echo "-- Waiting for health endpoint --"
ready=0
for _ in $(seq 1 30); do
  if curl -fsS -H "Authorization: Bearer ${ANALYST_TOKEN}" "http://${HOST}:${PORT}/healthz" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done

if [[ "${ready}" != "1" ]]; then
  echo "ERROR: service did not become healthy on http://${HOST}:${PORT}" >&2
  echo "       journalctl --user -u sigliere-mcp.service -n 50" >&2
  exit 1
fi

cat <<EOF

== Phase 6.9 install complete ==

Status:  systemctl --user status sigliere-mcp.service
Logs:    journalctl --user -u sigliere-mcp.service -f
Env:     ${ENV_FILE}
Quadlet: ${QUADLET_DIR}/sigliere-mcp.container

Next steps:
  - Run scripts/phase6-mcp-server-validate.sh for a throwaway-container
    dry-run smoke test independent of this live service.
  - Register the Open WebUI connection: see mcp-server/README.md and
    mcp-server/openwebui-role-prompts.md.
EOF
