#!/usr/bin/env bash
# scripts/install-sigliere-mcp.sh
#
# Optional MCP server: read-only tools over the local Kismet, occupancy,
# SigID, and MAC-vendor mirrors, served on 127.0.0.1:8150 and reached only
# through Caddy's loopback router at http://127.0.0.1:8180/mcp.
# See docs/mcp-server-design.md.
#
# Builds the image, creates ~/.config/sigliere/mcp.env (a new token on first
# run; preserved afterwards), installs the Quadlet, and starts the service.
# The environment file holds only the MCP token: no gateway credentials.
#
# Run as your normal user, NOT with sudo. Re-run scripts/install-open-webui.sh
# afterwards if the Caddy /mcp route is not present yet.
#
# Usage: ./scripts/install-sigliere-mcp.sh

set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as the rootless Podman user, not with sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="${HOME}/.config/sigliere"
ENV_FILE="${ENV_DIR}/mcp.env"
QUADLET_DIR="${HOME}/.config/containers/systemd"
IMAGE="localhost/sigliere-mcp:latest"
PORT=8150

echo "== SIGliere MCP server =="

# Podman refuses to start a container whose bind-mount source is missing.
for dir in /data/kismet-bridge /data/occupancy /data/reference/sigid /data/reference/mac-vendors; do
  if [[ ! -d "${dir}" ]]; then
    echo "ERROR: ${dir} does not exist. Run scripts/install-corpus-dirs.sh first." >&2
    exit 1
  fi
done

echo "-- Building ${IMAGE} --"
podman build -f "${REPO_ROOT}/mcp_server/Containerfile" -t "${IMAGE}" "${REPO_ROOT}"

mkdir -p "${ENV_DIR}" "${QUADLET_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
  umask 077
  {
    printf 'SIGLIERE_MCP_HOST=127.0.0.1\n'
    printf 'SIGLIERE_MCP_PORT=%s\n' "${PORT}"
    printf 'SIGLIERE_MCP_TOKEN=%s\n' "$(openssl rand -hex 32)"
  } > "${ENV_FILE}"
  echo "Generated an MCP token in ${ENV_FILE}."
else
  echo "Preserving existing MCP token in ${ENV_FILE}."
fi
chmod 0600 "${ENV_FILE}"

install -m 0644 "${REPO_ROOT}/containers/sigliere-mcp.container" \
  "${QUADLET_DIR}/sigliere-mcp.container"

systemctl --user daemon-reload
systemctl --user restart sigliere-mcp.service

TOKEN="$(sed -n 's/^SIGLIERE_MCP_TOKEN=//p' "${ENV_FILE}")"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"install","version":"0"}}}'
probe() {
  curl -fsS -o /dev/null -X POST "$1" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    --data "${INIT}"
}

healthy=0
for _ in $(seq 1 30); do
  if probe "http://127.0.0.1:${PORT}/" 2>/dev/null; then healthy=1; break; fi
  sleep 1
done
if [[ "${healthy}" != "1" ]]; then
  echo "MCP server did not become healthy; inspect:" >&2
  echo "  journalctl --user -u sigliere-mcp.service -n 50" >&2
  exit 1
fi
echo "MCP server is healthy on 127.0.0.1:${PORT}."

if probe "http://127.0.0.1:8180/mcp/" 2>/dev/null; then
  echo "Caddy route OK: http://127.0.0.1:8180/mcp/"
else
  echo "NOTE: the Caddy /mcp route is not answering. Re-run (with your original"
  echo "      SIGLIERE_HOSTNAME / certificate settings):"
  echo "        ./scripts/install-open-webui.sh"
fi

cat <<EOF2

== MCP server install complete ==

Status:     systemctl --user status sigliere-mcp.service
Logs:       journalctl --user -u sigliere-mcp.service -f
Validate:   ./scripts/validate-sigliere-mcp.sh

To connect Open WebUI (admin): Tools -> Integrations -> add a connection of
type MCP (Streamable HTTP)
  URL:   http://127.0.0.1:8180/mcp/
  Auth:  Bearer, with the SIGLIERE_MCP_TOKEN value from ${ENV_FILE}
EOF2
