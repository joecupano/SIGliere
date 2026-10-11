#!/usr/bin/env bash
# scripts/validate-sigliere-mcp.sh
#
# MCP server exit criteria (docs/mcp-server-design.md, section 11):
#   - the service is active and listens on loopback only
#   - requests without, or with a wrong, token are rejected (directly and
#     through Caddy)
#   - initialize works and tools/list is exactly the expected read-only set
#   - one successful call per tool, via the Caddy route Open WebUI uses
#   - the container has no writable mounts and no gateway credentials
#
# Usage: ./scripts/validate-sigliere-mcp.sh

set -uo pipefail

ENV_FILE="${HOME}/.config/sigliere/mcp.env"
DIRECT="http://127.0.0.1:8150/"
VIA_CADDY="http://127.0.0.1:8180/mcp/"
EXPECTED="kismet_summary lookup_mac_vendor lookup_signal occupancy_sightings occupancy_summary query_occupancy query_wifi_devices search_mac_vendors search_signals"
failures=0

pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1"; failures=$((failures + 1)); }

echo "== MCP server validation =="

[[ -r "${ENV_FILE}" ]] || { echo "FAIL: ${ENV_FILE} not found; run scripts/install-sigliere-mcp.sh"; exit 1; }
TOKEN="$(sed -n 's/^SIGLIERE_MCP_TOKEN=//p' "${ENV_FILE}")"

rpc() {  # rpc URL TOKEN-OR-EMPTY JSON  -> prints "<http_status> <body>"
  local url="$1" token="$2" body="$3" auth=()
  [[ -n "${token}" ]] && auth=(-H "Authorization: Bearer ${token}")
  curl -s -w ' %{http_code}' -X POST "${url}" "${auth[@]}" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' --data "${body}"
}
status_of() { echo "${1##* }"; }
body_of() { echo "${1% *}"; }

INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"validate","version":"0"}}}'

echo "-- Service and network exposure --"
if systemctl --user is-active --quiet sigliere-mcp.service 2>/dev/null; then
  pass "sigliere-mcp.service is active"
else
  fail "sigliere-mcp.service is not active"
fi
listeners="$(ss -ltnH 'sport = :8150' 2>/dev/null | awk '{print $4}')"
if [[ -n "${listeners}" ]] && ! echo "${listeners}" | grep -vE '^(127\.0\.0\.1|\[::1\]):8150$' | grep -q .; then
  pass "port 8150 listens on loopback only (${listeners//$'\n'/, })"
else
  fail "port 8150 listener is missing or not loopback-only: ${listeners:-none}"
fi

echo "-- Authentication --"
for target in "${DIRECT}" "${VIA_CADDY}"; do
  r="$(rpc "${target}" "" "${INIT}")"
  [[ "$(status_of "${r}")" == "401" ]] && pass "no token rejected (${target})" || fail "no token not rejected (${target}): $(status_of "${r}")"
  r="$(rpc "${target}" "wrong-token-value" "${INIT}")"
  [[ "$(status_of "${r}")" == "401" ]] && pass "wrong token rejected (${target})" || fail "wrong token not rejected (${target}): $(status_of "${r}")"
done

echo "-- Protocol and tools (through Caddy, as Open WebUI calls it) --"
r="$(rpc "${VIA_CADDY}" "${TOKEN}" "${INIT}")"
if [[ "$(status_of "${r}")" == "200" ]] && body_of "${r}" | grep -q '"serverInfo"'; then
  pass "initialize"
else
  fail "initialize failed: $(status_of "${r}") $(body_of "${r}" | cut -c1-120)"
fi

r="$(rpc "${VIA_CADDY}" "${TOKEN}" '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')"
listing="$(python3 - "$(body_of "${r}")" <<'PY'
import json, sys
try:
    tools = json.loads(sys.argv[1])["result"]["tools"]
except Exception as e:
    print(f"unparseable:{e}"); sys.exit()
ro = all((t.get("annotations") or {}).get("readOnlyHint") is True for t in tools)
print(" ".join(sorted(t["name"] for t in tools)) + ("" if ro else " NOT-ALL-READONLY"))
PY
)"
if [[ "${listing}" == "${EXPECTED}" ]]; then
  pass "tools/list is exactly the expected nine read-only tools"
else
  fail "unexpected tool list: ${listing}"
fi

call() {  # call NAME ARGS-JSON : succeeds if the call returned without isError
  local r
  r="$(rpc "${VIA_CADDY}" "${TOKEN}" "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}")"
  if [[ "$(status_of "${r}")" == "200" ]] && body_of "${r}" | grep -q '"isError":false'; then
    pass "call $1"
  else
    fail "call $1: $(status_of "${r}") $(body_of "${r}" | cut -c1-160)"
  fi
}
call kismet_summary '{}'
call query_wifi_devices '{"device_type":"AP","since_minutes":600}'
call occupancy_summary '{}'
call query_occupancy '{}'
call occupancy_sightings '{"signal_key":"validate:none"}'
call lookup_signal '{"name":"OTH Radar"}'
call search_signals '{"keyword":"8psk"}'
call lookup_mac_vendor '{"mac_address":"00:1A:2B:3C:4D:5E"}'
call search_mac_vendors '{"vendor_name":"cisco"}'

echo "-- Container privileges --"
rw="$(podman inspect sigliere-mcp --format '{{range .Mounts}}{{if .RW}}{{.Destination}} {{end}}{{end}}' 2>/dev/null)"
[[ -z "${rw}" ]] && pass "no writable mounts" || fail "writable mounts: ${rw}"
ro_root="$(podman inspect sigliere-mcp --format '{{.HostConfig.ReadonlyRootfs}}' 2>/dev/null)"
[[ "${ro_root}" == "true" ]] && pass "read-only root filesystem" || fail "root filesystem is writable"
tok_vars="$(podman inspect sigliere-mcp --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | sed -n 's/^\([A-Z_]*TOKEN[A-Z_]*\)=.*/\1/p' | sort -u | tr '\n' ' ')"
if [[ "${tok_vars}" == "SIGLIERE_MCP_TOKEN " ]]; then
  pass "only credential in the container is SIGLIERE_MCP_TOKEN"
else
  fail "unexpected credential variables: ${tok_vars:-none}"
fi

echo
if (( failures )); then
  echo "${failures} check(s) failed." >&2
  exit 1
fi
echo "MCP server validation passed."
