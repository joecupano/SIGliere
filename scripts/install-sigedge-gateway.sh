#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as the rootless Podman user, not with sudo." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="${HOME}/.config/sigliere"
ENV_FILE="${ENV_DIR}/gateway.env"
QUADLET_DIR="${HOME}/.config/containers/systemd"
IMAGE="localhost/sigliere-gateway:latest"

podman build -f "${REPO_ROOT}/gateway/Containerfile" -t "${IMAGE}" "${REPO_ROOT}"

mkdir -p "${ENV_DIR}" "${QUADLET_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
  ANALYST_TOKEN="$(openssl rand -hex 32)"
  OPERATOR_TOKEN="$(openssl rand -hex 32)"
  umask 077
  {
    printf 'SIGLIERE_GATEWAY_HOST=127.0.0.1\n'
    printf 'SIGLIERE_GATEWAY_PORT=8140\n'
    printf 'SIGLIERE_GATEWAY_DRY_RUN=true\n'
    printf 'SIGLIERE_GATEWAY_TOKENS_JSON={"%s":"analyst","%s":"operator"}\n'       "${ANALYST_TOKEN}" "${OPERATOR_TOKEN}"
  } > "${ENV_FILE}"
  echo "Generated gateway credentials in ${ENV_FILE}; dry-run remains enabled."
else
  echo "Preserving existing gateway credentials in ${ENV_FILE}."
fi

sed "s|__REPO_ROOT__|${REPO_ROOT}|g"   "${REPO_ROOT}/containers/sigliere-gateway.container"   > "${QUADLET_DIR}/sigliere-gateway.container"

systemctl --user daemon-reload
systemctl --user restart sigliere-gateway.service

ANALYST_TOKEN="$(sed -n 's/.*{"\([^"]*\)":"analyst".*/\1/p' "${ENV_FILE}")"
for _ in $(seq 1 30); do
  if curl -fsS -H "Authorization: Bearer ${ANALYST_TOKEN}"       http://127.0.0.1:8140/healthz >/dev/null 2>&1; then
    echo "SIGedge gateway is healthy on loopback; dry-run is enabled by default."
    exit 0
  fi
  sleep 1
done

echo "Gateway did not become healthy; inspect:" >&2
echo "  journalctl --user -u sigliere-gateway.service -n 50" >&2
exit 1

