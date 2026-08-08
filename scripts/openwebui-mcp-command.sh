#!/usr/bin/env bash
set -euo pipefail

# Prints a command suitable for Open WebUI Tool -> MCP Settings.
# This uses streamable HTTP and a role-scoped bearer token, looked up from
# mcp.env's SIGLIERE_MCP_TOKENS_JSON (the single source of truth for
# token-to-role mapping — nothing here hardcodes or duplicates a token).
# NOTE: only use this when Open WebUI connection Type is MCP.
# If your Open WebUI only supports OpenAPI tools, use
# scripts/openwebui-openapi-command.sh instead.
#
# Usage: ./scripts/openwebui-mcp-command.sh [analyst|operator]
#   No argument: prints both blocks (analyst first, then operator) — you
#   need both to set up the two roles described in
#   mcp-server/openwebui-role-prompts.md. Pass a role name to print just
#   that one block.
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

# Re-read SIGLIERE_MCP_TOKENS_JSON directly from the file rather than trusting
# the value `source` just set: bash's word-splitting/quote-removal on an
# unquoted `VAR={"a":"b"}` line strips every double quote, leaving invalid
# JSON. grep+cut preserve the line byte-for-byte instead.
SIGLIERE_MCP_TOKENS_JSON="$(grep -m1 '^SIGLIERE_MCP_TOKENS_JSON=' "${ENV_FILE}" | cut -d= -f2-)"

if [[ -z "${SIGLIERE_MCP_TOKENS_JSON:-}" ]]; then
  echo "SIGLIERE_MCP_TOKENS_JSON must be set in ${ENV_FILE}" >&2
  exit 1
fi

# Open WebUI runs in a container; wildcard bind addresses are not routable from
# inside that container. Emit the host-gateway name for MCP tool registration.
MCP_URL_HOST="${SIGLIERE_MCP_HOST}"
if [[ "${MCP_URL_HOST}" == "0.0.0.0" ]]; then
  MCP_URL_HOST="host.containers.internal"
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
Name: Sigliere MCP (${role})
Type: Streamable HTTP
URL: http://${MCP_URL_HOST}:${SIGLIERE_MCP_PORT}
Headers:
  Authorization: Bearer ${token}

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
