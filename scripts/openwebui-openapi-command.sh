#!/usr/bin/env bash
set -euo pipefail

# Prints Open WebUI OpenAPI connection settings for the SIGINT OpenAPI server.
# Use this when Open WebUI connection Type is OpenAPI.

OPENAPI_HOST="${SIGINT_OPENAPI_HOST:-}"
OPENAPI_PORT="${SIGINT_OPENAPI_PORT:-8130}"

# If host is not provided, derive a likely LAN IP for browser-side validation.
if [[ -z "${OPENAPI_HOST}" || "${OPENAPI_HOST}" == "0.0.0.0" ]]; then
  OPENAPI_HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

if [[ -z "${OPENAPI_HOST}" ]]; then
  echo "Could not determine OpenAPI host IP. Set SIGINT_OPENAPI_HOST and retry." >&2
  exit 1
fi

cat <<EOF
Type: OpenAPI
Name: SIGINT OpenAPI
URL: http://${OPENAPI_HOST}:${OPENAPI_PORT}
OpenAPI Spec URL: http://${OPENAPI_HOST}:${OPENAPI_PORT}/openapi.json
Auth: None
EOF
