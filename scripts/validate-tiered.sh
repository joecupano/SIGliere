#!/usr/bin/env bash
set -euo pipefail

HOSTNAME_TLS="${SIGLIERE_HOSTNAME:-$(hostname -s).local}"
ENV_FILE="${HOME}/.config/sigliere/gateway.env"
failures=0

check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "PASS  ${label}"
  else
    echo "FAIL  ${label}"
    failures=$((failures + 1))
  fi
}

check "Open WebUI loopback" curl -fsS http://127.0.0.1:8080/

if [[ "${HOSTNAME_TLS}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  # An IP-literal host gets no SNI from real clients (RFC 6066); Caddy then
  # matches by actual destination address, so probe that address directly
  # rather than faking DNS to loopback.
  check "Caddy TLS ingress" curl -ksS "https://${HOSTNAME_TLS}:8443/"
else
  check "Caddy TLS ingress" curl -ksS --resolve "${HOSTNAME_TLS}:8443:127.0.0.1"     "https://${HOSTNAME_TLS}:8443/"
fi

check "Ollama through private Caddy route" curl -fsS   http://127.0.0.1:8180/ollama/api/tags

if [[ -r "${ENV_FILE}" ]]; then
  ANALYST_TOKEN="$(sed -n 's/.*{"\([^"]*\)":"analyst".*/\1/p' "${ENV_FILE}")"
  check "SIGedge gateway through private Caddy route" curl -fsS     -H "Authorization: Bearer ${ANALYST_TOKEN}"     http://127.0.0.1:8180/gateway/healthz
  check "SIGedge node contract" curl -fsS     -H "Authorization: Bearer ${ANALYST_TOKEN}"     http://127.0.0.1:8180/gateway/nodes
else
  echo "FAIL  gateway environment missing: ${ENV_FILE}"
  failures=$((failures + 1))
fi

# MCP server (standard component): reachable through the private router, and
# it must reject requests that carry no token.
MCP_ENV="${HOME}/.config/sigliere/mcp.env"
MCP_URL="http://127.0.0.1:8180/mcp/"
MCP_INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"validate-tiered","version":"0"}}}'
if [[ -r "${MCP_ENV}" ]]; then
  MCP_TOKEN="$(sed -n 's/^SIGLIERE_MCP_TOKEN=//p' "${MCP_ENV}")"
  check "MCP server through private Caddy route" curl -fsS -X POST "${MCP_URL}" \
    -H "Authorization: Bearer ${MCP_TOKEN}" -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' --data "${MCP_INIT}"
  mcp_rejects_anonymous() {
    [[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "${MCP_URL}" \
      -H 'Content-Type: application/json' \
      -H 'Accept: application/json, text/event-stream' --data "${MCP_INIT}")" == "401" ]]
  }
  check "MCP server rejects requests without a token" mcp_rejects_anonymous
else
  echo "FAIL  MCP environment missing: ${MCP_ENV} (run scripts/install-sigliere-mcp.sh)"
  failures=$((failures + 1))
fi

check "Caddy configuration" podman exec caddy caddy validate   --config /etc/caddy/Caddyfile
check "Open WebUI to Ollama" podman exec open-webui curl -fsS   http://127.0.0.1:8180/ollama/api/tags

if (( failures )); then
  echo "${failures} validation check(s) failed." >&2
  exit 1
fi
echo "Tiered core validation passed."

