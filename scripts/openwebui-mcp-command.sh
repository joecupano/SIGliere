#!/usr/bin/env bash
set -euo pipefail

# Prints a command suitable for Open WebUI Tool -> MCP Settings.
# This uses streamable HTTP and the operator token stored in mcp.env.
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

cat <<EOF
Name: Sigliere MCP
Type: Streamable HTTP
URL: http://${SIGLIERE_MCP_HOST}:${SIGLIERE_MCP_PORT}
Headers:
  Authorization: Bearer ${SIGLIERE_OPERATOR_TOKEN}
EOF
