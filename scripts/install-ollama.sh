#!/usr/bin/env bash
# scripts/install-ollama.sh
#
# Install — Ollama and default models. See docs/build-order.md for full
# rationale. Installed natively (not containerized) for simpler GPU
# passthrough.
#
# This script INSTALLS + pulls default models. Run
# scripts/validate-ollama.sh afterward.
#
# Usage: sudo ./scripts/install-ollama.sh

set -euo pipefail

echo "== Install: Ollama and default models =="

# ---------------------------------------------------------------------
# Default model selection — confirmed for the 16GB RTX 5060 Ti variant.
# Verified against the live Ollama library as of June 2026 — re-check
# https://ollama.com/library before relying on these tags long-term,
# the catalog moves fast and this is a snapshot, not a guarantee.
# ---------------------------------------------------------------------
INSTRUCT_MODEL="${INSTRUCT_MODEL:-qwen3:14b}"     # general chat/reasoning,
                                                    # NL query over SIGINT DB
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"    # RAG over /data/rag —
                                                    # the standard pick,
                                                    # ~274MB, 8192-token chunks
VISION_MODEL="${VISION_MODEL:-gemma3:12b}"        # image reasoning over
                                                    # /data/imagery; also
                                                    # handles OCR-adjacent
                                                    # tasks reasonably, though
                                                    # the ai-ingest pipeline's
                                                    # docling/pytesseract path
                                                    # (Phase 5) remains the
                                                    # primary OCR mechanism
TOOL_MODEL="${TOOL_MODEL:-llama3-groq-tool-use:8b}" # dedicated tool/function-
                                                    # calling model (~4.7GB),
                                                    # fine-tuned by Groq for
                                                    # reliable tool invocation.
                                                    # Pulled ALONGSIDE the
                                                    # instruct model: the SIGINT
                                                    # native tools were proven
                                                    # reliable against this in
                                                    # the working build. It's an
                                                    # older model (Llama 3, Jul
                                                    # 2024), so also try the
                                                    # newer INSTRUCT_MODEL
                                                    # (qwen3:14b) for tools and
                                                    # keep whichever invokes
                                                    # them more reliably. Set
                                                    # TOOL_MODEL=skip to omit.

echo "Models to pull: ${INSTRUCT_MODEL}, ${EMBED_MODEL}, ${VISION_MODEL}, ${TOOL_MODEL}"
echo "(override by exporting INSTRUCT_MODEL / EMBED_MODEL / VISION_MODEL / TOOL_MODEL before running)"
echo

# Ensure the default install path pulls the full recommended set for this
# SIGINT stack. If an operator wants a slimmer install, they can override
# TOOL_MODEL=skip before running the script.
if [[ "${TOOL_MODEL}" == "skip" ]]; then
  echo "  Note: TOOL_MODEL=skip set, so the dedicated tool-calling model will be omitted."
fi

# ---------------------------------------------------------------------
# Install Ollama (official installer — creates an 'ollama' system user
# and a systemd service)
# ---------------------------------------------------------------------
echo "-- Installing Ollama --"
curl -fsSL https://ollama.com/install.sh | sh

# ---------------------------------------------------------------------
# Point Ollama at /data/models BEFORE the first pull — moving weights
# after the fact works but means re-pointing manifests/symlinks rather
# than just pulling clean. See docs/data-layout.md.
# ---------------------------------------------------------------------
echo "-- Configuring loopback-only Ollama and model storage --"
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<'EOF'
[Service]
Environment="OLLAMA_MODELS=/data/models"
Environment="OLLAMA_HOST=127.0.0.1:11434"
EOF

# Open WebUI reaches Ollama through Caddy's private loopback router.
# Ollama never needs a LAN listener of its own.

# /data is owned by the human operator (see scripts/install-corpus-dirs.sh,
# which runs before this script and already created it),
# but Ollama's systemd service runs as its own 'ollama' system user —
# that account needs write access to /data/models specifically, or model
# pulls will fail with a permissions error. This is a deliberate,
# narrowly-scoped exception to the general /data ownership convention:
# /data/models is Ollama's exclusive territory, so it gets chowned to
# the ollama service account rather than the human user.
echo "-- Granting the ollama service account ownership of /data/models --"
sudo mkdir -p /data/models
sudo chown -R ollama:ollama /data/models
# Group-write + setgid on directories so that any subdirectory Ollama
# creates on future pulls inherits the group and stays writable — prevents
# a later pull failing with "permission denied" on a freshly-created
# registry subpath. Consistent with scripts/install-corpus-dirs.sh.
sudo chmod -R u+rwX,g+rwX /data/models
sudo find /data/models -type d -exec chmod g+s {} \;

# Chowning /data/models alone is NOT sufficient — confirmed via a real
# install ("mkdir /data/models: permission denied: ensure path elements
# are traversable"). /data itself is locked to o-rwx (no access outside
# the owning user/group) per scripts/install-corpus-dirs.sh, so the 'ollama'
# user — being neither the owner nor in that group — can't even
# traverse INTO /data to reach /data/models, regardless of what
# /data/models itself is owned by. Fix: add 'ollama' to whatever group
# owns /data, giving it legitimate group-level traverse access
# consistent with the existing permission model, rather than loosening
# /data's own permissions to fix one consumer.
DATA_GROUP="$(stat -c '%G' /data)"
echo "-- Adding 'ollama' to '${DATA_GROUP}' (the group owning /data) so it can traverse into it --"
sudo usermod -aG "${DATA_GROUP}" ollama

sudo systemctl daemon-reload
sudo systemctl enable --now ollama
sudo systemctl restart ollama

echo "Waiting for Ollama to come up..."
for i in $(seq 1 15); do
  if curl -fsS http://localhost:11434/ >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# ---------------------------------------------------------------------
# Pull default models
# ---------------------------------------------------------------------
echo "-- Pulling models (this can take a while on first run) --"
pull_model() {
  local model="$1"
  echo "-- Pulling ${model} --"
  ollama pull "${model}"
}

models_to_pull=("${INSTRUCT_MODEL}" "${EMBED_MODEL}" "${VISION_MODEL}")
if [[ "${TOOL_MODEL}" != "skip" ]]; then
  models_to_pull+=("${TOOL_MODEL}")
else
  echo "  (TOOL_MODEL=skip — not pulling a dedicated tool-calling model)"
fi

for model in "${models_to_pull[@]}"; do
  pull_model "${model}"
done

echo
echo "-- Installed models --"
ollama list

cat <<EOF

== Ollama install complete ==

Next: run scripts/validate-ollama.sh to confirm GPU inference actually
works and models physically live on /data/models — do not consider
the Ollama install done until that passes.
EOF
