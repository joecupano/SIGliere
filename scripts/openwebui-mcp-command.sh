#!/usr/bin/env bash
set -euo pipefail

# Prints a command suitable for Open WebUI Tool -> MCP Settings.
# This uses streamable HTTP and the operator token stored in mcp.env.
# NOTE: only use this when Open WebUI connection Type is MCP.
# If your Open WebUI only supports OpenAPI tools, use
# scripts/openwebui-openapi-command.sh instead.
ENV_FILE="${HOME}/.config/sigliere/mcp.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${ENV_FILE}"

if [[ -z "${SIGLIERE_MCP_HOST:-}" || -z "${SIGLIERE_MCP_PORT:-}" ]]; then
  echo "SIGLIERE_MCP_HOST and SIGLIERE_MCP_PORT must be set in ${ENV_FILE}" >&2
  exit 1
fi

if [[ -z "${SIGLIERE_OPERATOR_TOKEN:-}" ]]; then
  echo "SIGLIERE_OPERATOR_TOKEN must be set in ${ENV_FILE}" >&2
  exit 1
fi

# Open WebUI runs in a container; wildcard bind addresses are not routable from
# inside that container. Emit the host-gateway name for MCP tool registration.
MCP_URL_HOST="${SIGLIERE_MCP_HOST}"
if [[ "${MCP_URL_HOST}" == "0.0.0.0" ]]; then
  MCP_URL_HOST="host.containers.internal"
fi

cat <<EOF
Name: Sigliere MCP
Type: Streamable HTTP
URL: http://${MCP_URL_HOST}:${SIGLIERE_MCP_PORT}
Headers:
  Authorization: Bearer ${SIGLIERE_OPERATOR_TOKEN}
EOF
