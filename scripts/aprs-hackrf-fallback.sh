#!/usr/bin/env bash
set -euo pipefail

# Fallback APRS receiver for this host when the radiod multicast path is not
# producing usable demodulated audio. It uses the directly verified HackRF
# capture path instead of the radiod publish/pcmrecord chain.

FREQ=144390000
RATE=2000000
SAMPLES=$((RATE / 10))
OUTDIR="${1:-/tmp/aprs-fallback}"
mkdir -p "$OUTDIR"

RAW="$OUTDIR/hackrf-aprs.raw"
LOG="$OUTDIR/hackrf-aprs.log"

sudo hackrf_transfer -r - -f "$FREQ" -s "$RATE" -n "$SAMPLES" -l 40 -g 48 > "$RAW" 2> "$LOG"

printf 'Captured %s bytes to %s\n' "$(wc -c < "$RAW")" "$RAW"
if command -v multimon-ng >/dev/null 2>&1; then
  echo "== APRS decode via multimon-ng =="
  multimon-ng -A -q -t raw "$RAW" 2>&1 | head -40 || true
fi
