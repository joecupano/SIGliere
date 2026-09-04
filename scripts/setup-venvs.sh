#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_ROOT="${HOME}/.local/share/sigliere/venvs"
declare -A DOMAINS=(
  [ai-ingest]="ai-ingest/requirements.txt"
  [reference]="reference/requirements.txt"
  [occupancy]="occupancy/requirements.txt"
)

TARGETS=("$@")
if (( ${#TARGETS[@]} == 0 )); then
  TARGETS=("${!DOMAINS[@]}")
fi

install -d -m 0755 "${VENV_ROOT}"
for domain in "${TARGETS[@]}"; do
  requirements="${DOMAINS[${domain}]:-}"
  [[ -n "${requirements}" ]] || {
    echo "Unknown domain: ${domain}" >&2
    exit 1
  }
  python3 -m venv "${VENV_ROOT}/${domain}"
  "${VENV_ROOT}/${domain}/bin/pip" install --upgrade pip
  "${VENV_ROOT}/${domain}/bin/pip" install -r "${REPO_ROOT}/${requirements}"
done

