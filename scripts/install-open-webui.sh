#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as the rootless Podman user, not with sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUADLET_DIR="${HOME}/.config/containers/systemd"
HOSTNAME_TLS="${SIGLIERE_HOSTNAME:-$(hostname -s).local}"
CERT="${SIGLIERE_CERT:-}"
KEY="${SIGLIERE_KEY:-}"

if [[ -n "${CERT}" || -n "${KEY}" ]]; then
  [[ -n "${CERT}" && -n "${KEY}" ]] || {
    echo "SIGLIERE_CERT and SIGLIERE_KEY must be supplied together." >&2
    exit 1
  }
  [[ -r "${CERT}" && -r "${KEY}" ]] || {
    echo "Certificate or key is not readable." >&2
    exit 1
  }
fi

mkdir -p "${QUADLET_DIR}" "${QUADLET_DIR}/caddy-certs"
install -m 0644 "${REPO_ROOT}/containers/open-webui.container"   "${QUADLET_DIR}/open-webui.container"
install -m 0644 "${REPO_ROOT}/containers/caddy.container"   "${QUADLET_DIR}/caddy.container"

TLS_LINE="tls internal"
if [[ -n "${CERT}" ]]; then
  install -m 0644 "${CERT}" "${QUADLET_DIR}/caddy-certs/cert.pem"
  install -m 0600 "${KEY}" "${QUADLET_DIR}/caddy-certs/key.pem"
  TLS_LINE="tls /etc/caddy/certs/cert.pem /etc/caddy/certs/key.pem"
fi

umask 077
{
  printf '%s\n' '{'
  printf '\tauto_https disable_redirects\n'
  printf '%s\n\n' '}'
  printf '%s:8443 {\n' "${HOSTNAME_TLS}"
  printf '\t%s\n' "${TLS_LINE}"
  printf '\treverse_proxy 127.0.0.1:8080\n'
  printf '%s\n\n' '}'
  printf '%s\n' 'http://127.0.0.1:8180 {'
  printf '\tbind 127.0.0.1\n'
  printf '\thandle_path /ollama/* {\n'
  printf '\t\treverse_proxy 127.0.0.1:11434\n'
  printf '\t}\n'
  printf '\thandle_path /gateway/* {\n'
  printf '\t\treverse_proxy 127.0.0.1:8140\n'
  printf '\t}\n'
  # MCP server (scripts/install-sigliere-mcp.sh). Matches /mcp and
  # /mcp/..., strips the prefix, and streams responses. Returns 502 on this
  # loopback-only router until the service is installed.
  printf '\t@mcp path /mcp /mcp/*\n'
  printf '\thandle @mcp {\n'
  printf '\t\turi strip_prefix /mcp\n'
  printf '\t\treverse_proxy 127.0.0.1:8150 {\n'
  printf '\t\t\tflush_interval -1\n'
  printf '\t\t}\n'
  printf '\t}\n'
  printf '\thandle {\n'
  printf '\t\trespond 404\n'
  printf '\t}\n'
  printf '%s\n' '}'
} > "${QUADLET_DIR}/Caddyfile"
chmod 0644 "${QUADLET_DIR}/Caddyfile"

systemctl --user daemon-reload
systemctl --user restart open-webui.service
systemctl --user restart caddy.service

# Wait for Open WebUI itself first. Caddy answers 502 while the backend is
# still starting, and a plain `curl` treats a 502 as success, so probing only
# through Caddy reported "ready" too early (and a validator run straight after
# the install then failed). Open WebUI can take a minute or more to come up,
# especially right after an upgrade.
backend_ready=0
for _ in $(seq 1 180); do
  if curl -fsS http://127.0.0.1:8080/api/version >/dev/null 2>&1; then
    backend_ready=1
    break
  fi
  sleep 1
done
if [[ "${backend_ready}" != "1" ]]; then
  echo "Open WebUI did not answer on 127.0.0.1:8080 within 180 s; inspect:" >&2
  echo "  journalctl --user -u open-webui.service -n 50" >&2
  exit 1
fi

ready=0
for _ in $(seq 1 60); do
  if [[ "${HOSTNAME_TLS}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    # An IP-literal host gets no SNI from real clients (RFC 6066); Caddy
    # then matches by actual destination address, so probe that address
    # directly rather than faking DNS to loopback.
    PROBE=(curl -fksS "https://${HOSTNAME_TLS}:8443/")
  else
    PROBE=(curl -fksS --resolve "${HOSTNAME_TLS}:8443:127.0.0.1" "https://${HOSTNAME_TLS}:8443/")
  fi
  if "${PROBE[@]}" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "${ready}" != "1" ]]; then
  echo "Caddy/Open WebUI did not become ready; inspect user-service logs." >&2
  exit 1
fi

echo "Open WebUI: https://${HOSTNAME_TLS}:8443/"
if [[ -z "${CERT}" ]]; then
  echo "Caddy internal CA is active. Export and trust it on each client:"
  echo "  podman cp caddy:/data/caddy/pki/authorities/local/root.crt ./sigliere-root-ca.crt"
else
  echo "Operator-provided certificate installed."
fi

