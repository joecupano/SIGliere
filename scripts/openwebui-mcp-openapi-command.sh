#!/usr/bin/env bash
set -euo pipefail

# Prints Open WebUI OpenAPI-type connection settings for the Sigliere MCP
# server (:8140), for Open WebUI builds whose Admin Panel only offers
# Type=OpenAPI (no MCP/Streamable HTTP option) — see
# docs/openapi-to-mcp-migration.md. The MCP server is a FastAPI app and
# already serves its own /openapi.json covering the same
# healthz/nodes/route_frequency/radiod_status/set_frequency endpoints, so
# this is the same server and same role-scoped tokens as
# scripts/openwebui-mcp-command.sh, just registered under a different
# Open WebUI connection type.
#
# Usage: ./scripts/openwebui-mcp-openapi-command.sh [analyst|operator]
#   No argument: prints both blocks.
ENV_FILE="${HOME}/.config/sigliere/mcp.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${ENV_FILE}"

MCP_PORT="${SIGLIERE_MCP_PORT:-8140}"

# Re-read the token map directly from the file rather than trusting what
# `source` just set: bash's word-splitting/quote-removal on an unquoted
# `VAR={"a":"b"}` line strips every double quote, leaving invalid JSON.
SIGLIERE_MCP_TOKENS_JSON="$(grep -m1 '^SIGLIERE_MCP_TOKENS_JSON=' "${ENV_FILE}" | cut -d= -f2-)"
if [[ -z "${SIGLIERE_MCP_TOKENS_JSON:-}" ]]; then
  echo "SIGLIERE_MCP_TOKENS_JSON must be set in ${ENV_FILE}" >&2
  exit 1
fi

# Open WebUI's OpenAPI connection (both the connection URL and the spec URL)
# needs a LAN-reachable address, the same pattern already validated for the
# :8130 OpenAPI server in docs/openwebui-setup-guide.md — not
# host.containers.internal, which is container-to-host only.
MCP_HOST="${SIGINT_OPENAPI_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
if [[ -z "${MCP_HOST}" ]]; then
  echo "Could not determine a LAN IP. Set SIGINT_OPENAPI_HOST and retry." >&2
  exit 1
fi

print_block() {
  local role="$1"
  local token
  token="$(SIGLIERE_MCP_TOKENS_JSON="${SIGLIERE_MCP_TOKENS_JSON}" ROLE="${role}" python3 -c '
import json, os, sys
tokens = json.loads(os.environ["SIGLIERE_MCP_TOKENS_JSON"])
role = os.environ["ROLE"]
matches = [tok for tok, r in tokens.items() if r == role]
if not matches:
    sys.exit(1)
print(matches[0])
')" || {
    echo "No token mapped to role '${role}' in SIGLIERE_MCP_TOKENS_JSON (${ENV_FILE})" >&2
    return 1
  }

  cat <<EOF
Type: OpenAPI
Name: Sigliere MCP (${role})
URL: http://${MCP_HOST}:${MCP_PORT}
OpenAPI Spec URL: http://${MCP_HOST}:${MCP_PORT}/openapi.json
Auth: Bearer
Bearer Token: ${token}

EOF
}

case "${1:-}" in
  "")
    print_block "analyst"
    print_block "operator"
    ;;
  analyst|operator)
    print_block "$1"
    ;;
  *)
    echo "Usage: $0 [analyst|operator]" >&2
    exit 1
    ;;
esac
