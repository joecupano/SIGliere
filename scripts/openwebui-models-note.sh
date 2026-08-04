#!/usr/bin/env bash
# Small reminder for Open WebUI installs: 0.11.x shows Workspace -> Models as a
# workspace model registry, not as an auto-populated list of every Ollama model.

set -euo pipefail

echo "Open WebUI 0.11.x note"
echo "====================="
echo
if command -v ollama >/dev/null 2>&1; then
  echo "Available Ollama models:"
  ollama list || true
  echo
else
  echo "ollama is not installed or not on PATH."
  echo
fi

echo "If Workspace -> Models shows 0, that is expected until you create a"
echo "workspace model entry yourself."
echo

echo "In Open WebUI:"
echo "  1. Go to Workspace -> Models"
echo "  2. Create a new model entry"
echo "  3. Choose an Ollama base model such as qwen3:14b"
echo "  4. Save it; the model will then be available in the chat picker"
echo

echo "Recommended base models for this build:"
echo "  - qwen3:14b   (tool-capable reasoning model)"
echo "  - llama3-groq-tool-use:8b   (smaller tool-capable model)"
echo "  - gemma3:12b   (vision only; not for tools)"
