#!/usr/bin/env bash
set -euo pipefail

# Validates the Sigliere MCP server container in dry-run mode.
# This script is read-only against radio state when SIGLIERE_MCP_DRY_RUN=true.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="localhost/sigliere-mcp:latest"
NAME="sigliere-mcp-validate"
HOST="127.0.0.1"
PORT="8140"

ANALYST_TOKEN="analyst-token"
OPERATOR_TOKEN="operator-token"
TOKENS_JSON='{"analyst-token":"analyst","operator-token":"operator"}'

echo "[mcp-validate] ensuring image exists: ${IMAGE}"
if ! podman image exists "${IMAGE}"; then
  echo "[mcp-validate] image missing, building..."
  podman build -f "${REPO_ROOT}/mcp-server/Containerfile" -t "${IMAGE}" "${REPO_ROOT}"
fi

echo "[mcp-validate] starting container ${NAME}"
podman rm -f "${NAME}" >/dev/null 2>&1 || true
podman run -d \
  --name "${NAME}" \
  --network host \
  -e SIGLIERE_MCP_HOST="${HOST}" \
  -e SIGLIERE_MCP_PORT="${PORT}" \
  -e SIGLIERE_MCP_DRY_RUN=true \
  -e "SIGLIERE_MCP_TOKENS_JSON=${TOKENS_JSON}" \
  "${IMAGE}" >/dev/null

cleanup() {
  podman rm -f "${NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[mcp-validate] waiting for health endpoint"
ready=0
for _ in $(seq 1 30); do
  if curl -fsS -H "Authorization: Bearer ${ANALYST_TOKEN}" "http://${HOST}:${PORT}/healthz" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done

if [[ "${ready}" != "1" ]]; then
  echo "[mcp-validate] service did not become healthy on http://${HOST}:${PORT}"
  podman logs --tail 50 "${NAME}" || true
  exit 1
fi

health_json="$(curl -fsS -H "Authorization: Bearer ${ANALYST_TOKEN}" "http://${HOST}:${PORT}/healthz")"
nodes_json="$(curl -fsS -H "Authorization: Bearer ${ANALYST_TOKEN}" "http://${HOST}:${PORT}/nodes")"
route_json="$(curl -fsS -X POST -H 'Content-Type: application/json' -H "Authorization: Bearer ${ANALYST_TOKEN}" -d '{"frequency_hz":146520000}' "http://${HOST}:${PORT}/route_frequency")"
set_code="$(curl -sS -o /tmp/mcp_set_resp.json -w '%{http_code}' -X POST -H 'Content-Type: application/json' -H "Authorization: Bearer ${OPERATOR_TOKEN}" -d '{"node_id":"hackrf-vhf-uhf","frequency_hz":146520000,"mode":"nfm"}' "http://${HOST}:${PORT}/set_frequency")"
set_json="$(cat /tmp/mcp_set_resp.json)"

if [[ "${set_code}" != "200" ]]; then
  echo "[mcp-validate] set_frequency failed with HTTP ${set_code}"
  echo "${set_json}"
  exit 1
fi

echo "[mcp-validate] health: ${health_json}"
echo "[mcp-validate] nodes: ${nodes_json}"
echo "[mcp-validate] route: ${route_json}"
echo "[mcp-validate] set_frequency: ${set_json}"

echo "[mcp-validate] PASS"
