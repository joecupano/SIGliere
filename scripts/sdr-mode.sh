#!/usr/bin/env bash
# =====================================================================
# sdr-mode.sh — unified view + control of which owner holds each SDR.
# =====================================================================
# THE RULE THIS ENFORCES/EXPLAINS:
#   Every SDR is a single-owner USB device. An SDR held by OpenWebRX+ is
#   NOT available for AI/occupancy capture, and vice versa. They cannot
#   do both at once. DIFFERENT SDRs can do different jobs simultaneously
#   (e.g. RX-888->radiod for HF occupancy WHILE HackRF->OpenWebRX+ for a
#   VHF waterfall) — but no single SDR serves two masters.
#
# HONEST SCOPE (read this before expecting more than it does):
#   - RX-888 has a real, working AI<->OpenWebRX+ switch (radiod is its
#     occupancy/AI owner). This script delegates that to rx888-mode.sh.
#   - HackRF migrated to its own radiod instance (radiod@hackrf-2m,
#     2m band only — see ingest/ka9q-radio/radiod@hackrf-2m.conf for why
#     70cm isn't covered by this device; tracked as a TODO, not silently
#     dropped). HackRF's AI mode now has the SAME two-layer shape as
#     RX-888: a system-level radiod@hackrf-2m instance (owns the USB
#     device) plus a --user radiod-occupancy-hackrf.service (the producer
#     that reads radiod's demodulated channels and writes sightings).
#     'hackrf ai'/'hackrf interactive' toggle BOTH layers together; see
#     hackrf_ai()/hackrf_interactive() below. This REPLACES the old
#     vhf-uhf-occupancy@hackrf scan-based service — that unit is retired
#     for HackRF (still installed as a template file for rtlsdr's use
#     below, but no longer the HackRF path).
#   - RTL-SDR's role is DECIDED as of 2026-08-06: OpenWebRX+-only,
#     permanently, no AI mode. An ad hoc live-tasking path via
#     radiod@rtlsdr-v4 was built and fixed at the client/MCP level, but
#     a ka9q-radio bug limits a live-tasked channel to one control
#     command per radiod restart -- unfixable from this repo, filed
#     upstream (see docs/ka9q-radio-upstream-issue-command-queue.md and
#     docs/mcp-validation-evidence.md). 'rtlsdr ai' below still targets
#     the OLDER, already-retired vhf-uhf-occupancy@rtlsdr scan service
#     (installed by scripts/phase6-vhf-uhf-producer.sh) -- a different,
#     earlier mechanism than the radiod@rtlsdr-v4 path just described.
#     Neither should be used now; treat 'rtlsdr ai' as deprecated. Left
#     in place rather than removed, matching this repo's policy of
#     preserving rather than deleting decommissioned work.
#
# HackRF two-layer note: because radiod@hackrf-2m is a SYSTEM service
# (like radiod@rx888-hf), toggling HackRF's AI/interactive mode now needs
# sudo, same as rx888 — unlike the old --user-only vhf-uhf-occupancy path.
#
# Usage:
#   ./scripts/sdr-mode.sh status                    # true ownership of all SDRs
#   sudo ./scripts/sdr-mode.sh rx888 ai             # RX-888 -> radiod (AI/occupancy)
#   sudo ./scripts/sdr-mode.sh rx888 interactive    # RX-888 -> OpenWebRX+
#   sudo ./scripts/sdr-mode.sh hackrf ai            # HackRF -> radiod@hackrf-2m + producer
#   sudo ./scripts/sdr-mode.sh hackrf interactive   # HackRF -> free/OWRX+
#   ./scripts/sdr-mode.sh rtlsdr ai                 # DEPRECATED -- see note above, RTL-SDR is OpenWebRX+-only now
#   ./scripts/sdr-mode.sh rtlsdr interactive        # RTL-SDR -> free/OWRX+ (the only supported mode now)
#   ./scripts/sdr-mode.sh rtlsdr status             # per-device detail
#   ./scripts/sdr-mode.sh hackrf status
# ---------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OWRX_UNIT="openwebrx"
RADIOD_UNIT="radiod@rx888-hf"
HACKRF_RADIOD_INSTANCE="radiod@hackrf-2m"
HACKRF_PRODUCER_UNIT="radiod-occupancy-hackrf.service"

# USB identifiers for ownership detection.
RTLSDR_IDS="0bda:2838|0bda:2832"
HACKRF_IDS="1d50:6089|1d50:6084"
RX888_DFU="04b4:00f3"
RX888_LOADED="04b4:00f1"

is_active() { systemctl is-active --quiet "$1"; }

# Does OpenWebRX+ have a given driver ENABLED in its config? We can't
# easily introspect which device OWRX currently holds without parsing its
# runtime state, so we report OWRX's overall running state and let the
# operator combine it with the device-present check. This is honest about
# the limitation rather than guessing.
owrx_state() { is_active "${OWRX_UNIT}" && echo "RUNNING" || echo "stopped"; }

usb_present() {  # $1 = pattern
  lsusb 2>/dev/null | grep -qiE "$1"
}

# --- status --------------------------------------------------------------
status_all() {
  echo "== SDR ownership status =="
  echo
  echo "Rule: an SDR in OpenWebRX+ is NOT available for AI/occupancy, and"
  echo "vice versa. OpenWebRX+ is currently: $(owrx_state)."
  echo

  # RX-888 — has a real AI (radiod) owner, so we can state ownership.
  printf '  %-10s ' "RX-888:"
  if usb_present "${RX888_LOADED}|RX888"; then
    if is_active "${RADIOD_UNIT}"; then
      echo "AI/occupancy (radiod owns it)"
    elif is_active "${OWRX_UNIT}"; then
      echo "likely OpenWebRX+ (firmware loaded, radiod inactive, OWRX running)"
    else
      echo "firmware loaded but no active owner (free-ish; a process opened it)"
    fi
  elif usb_present "${RX888_DFU}"; then
    echo "present, DFU/bootloader — NO owner has loaded firmware (free)"
  else
    echo "not detected on USB"
  fi

  # RTL-SDR — no occupancy producer yet; report presence + OWRX state.
  printf '  %-10s ' "RTL-SDR:"
  if usb_present "${RTLSDR_IDS}"; then
    if is_active "${OWRX_UNIT}"; then
      echo "present; OpenWebRX+ is running (may hold it if its RTL-SDR"
      echo "             profile is enabled). No occupancy producer exists yet."
    else
      echo "present; OpenWebRX+ stopped -> free. No occupancy producer exists yet."
    fi
  else
    echo "not detected on USB"
  fi

  # HackRF — now has a real AI (radiod@hackrf-2m + producer) owner, same
  # treatment as RX-888. RTL-SDR below is unchanged (no dedicated radiod
  # owner in this script yet).
  printf '  %-10s ' "HackRF:"
  local hackrf_prod_state
  if usb_present "${HACKRF_IDS}"; then
    if is_active "${HACKRF_RADIOD_INSTANCE}"; then
      hackrf_prod_state=$(user_svc is-active "${HACKRF_PRODUCER_UNIT}" 2>/dev/null || echo "inactive")
      if [[ "${hackrf_prod_state}" == "active" ]]; then
        echo "AI/occupancy (radiod@hackrf-2m + producer both running)"
      else
        echo "radiod@hackrf-2m running, but producer (${HACKRF_PRODUCER_UNIT}) is not"
      fi
    elif is_active "${OWRX_UNIT}"; then
      echo "likely OpenWebRX+ (radiod@hackrf-2m inactive, OWRX running)"
    else
      echo "present; no active owner (free-ish; a process may have opened it)"
    fi
  else
    echo "not detected on USB"
  fi

  echo
  echo "Note: for RTL-SDR, 'which device OpenWebRX+ actually holds' depends"
  echo "on which profiles are enabled in its settings — this script reports"
  echo "OpenWebRX+'s running state, not per-device claim, for that path."
}

# --- rx888 delegation ----------------------------------------------------
rx888_cmd() {
  local sub="${1:-status}"
  if [[ ! -x "${SCRIPT_DIR}/rx888-mode.sh" ]]; then
    echo "rx888-mode.sh not found next to this script." >&2
    exit 1
  fi
  case "${sub}" in
    ai|interactive|status) exec "${SCRIPT_DIR}/rx888-mode.sh" "${sub}" ;;
    *) echo "rx888 sub-command must be: ai | interactive | status" >&2; exit 2 ;;
  esac
}

# --- hackrf: dedicated two-layer control (radiod@hackrf-2m + producer) ---
# Unlike rtlsdr (still a single --user service toggle), HackRF now has the
# same two-layer shape as RX-888: a system-level radiod instance owning
# the USB device, plus a --user producer service reading its channels.
# Both must be toggled together. Not delegated to a separate *-mode.sh
# file like RX-888 is, since this is new/less mature — kept inline here
# so the two-layer logic is visible in one place while it's still fresh.

hackrf_status() {
  echo "== HackRF (2m, via radiod) =="
  if ! usb_present "${HACKRF_IDS}"; then
    echo "  Not detected on USB."
    return
  fi
  echo "  Present on USB."
  echo "  OpenWebRX+ (system-wide): $(owrx_state)"
  if is_active "${HACKRF_RADIOD_INSTANCE}"; then
    echo "  radiod@hackrf-2m: RUNNING"
    local prod_state
    prod_state=$(user_svc is-active "${HACKRF_PRODUCER_UNIT}" 2>/dev/null || echo "inactive")
    echo "  Producer (${HACKRF_PRODUCER_UNIT}): ${prod_state}"
    if [[ "${prod_state}" == "active" ]]; then
      echo "  Mode: AI (radiod + producer both own the device)."
    else
      echo "  Mode: PARTIAL — radiod owns the device but the producer isn't"
      echo "        running, so no sightings are being recorded. Run:"
      echo "        sudo ./scripts/sdr-mode.sh hackrf ai"
    fi
  else
    echo "  radiod@hackrf-2m: stopped"
    echo "  Mode: interactive/free (available to OpenWebRX+), or no owner at all."
  fi
  echo
  echo "  To flip: sudo ./scripts/sdr-mode.sh hackrf {ai | interactive}"
}

hackrf_ai() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: 'hackrf ai' toggles a system-level service (${HACKRF_RADIOD_INSTANCE})" >&2
    echo "       and needs root. Re-run with sudo." >&2
    exit 1
  fi
  echo "-- Switching HackRF to AI mode (${HACKRF_RADIOD_INSTANCE} + ${HACKRF_PRODUCER_UNIT}) --"
  if is_active "${OWRX_UNIT}"; then
    echo "  NOTE: OpenWebRX+ is running. If its HackRF profile is enabled,"
    echo "        radiod@hackrf-2m may fail to open the device. Disable the"
    echo "        HackRF profile in OpenWebRX+ Settings -> SDR devices first,"
    echo "        then re-run this command."
  fi

  echo "  Enabling and starting ${HACKRF_RADIOD_INSTANCE}..."
  if ! systemctl enable --now "${HACKRF_RADIOD_INSTANCE}"; then
    echo "  ERROR: failed to enable/start ${HACKRF_RADIOD_INSTANCE}." >&2
    echo "  Check: journalctl -u ${HACKRF_RADIOD_INSTANCE} --no-pager -n 40" >&2
    echo "  Common cause: HackRF front-end support not confirmed in your" >&2
    echo "  installed radiod build — see ingest/ka9q-radio/radiod@hackrf-2m.conf" >&2
    echo "  header before troubleshooting further." >&2
    exit 1
  fi
  sleep 2
  if ! is_active "${HACKRF_RADIOD_INSTANCE}"; then
    echo "  WARNING: ${HACKRF_RADIOD_INSTANCE} did not stay active." >&2
    echo "  Diagnose: journalctl -u ${HACKRF_RADIOD_INSTANCE} --no-pager -n 40" >&2
    exit 1
  fi

  echo "  Enabling and starting ${HACKRF_PRODUCER_UNIT}..."
  if ! user_svc enable --now "${HACKRF_PRODUCER_UNIT}"; then
    echo "  ERROR: failed to enable/start ${HACKRF_PRODUCER_UNIT}." >&2
    echo "  Check: journalctl --user -u ${HACKRF_PRODUCER_UNIT} --no-pager -n 30" >&2
    echo "  (radiod@hackrf-2m is up, but the producer isn't — DB won't fill.)" >&2
    exit 1
  fi
  sleep 2
  local prod_state
  prod_state=$(user_svc is-active "${HACKRF_PRODUCER_UNIT}" 2>/dev/null || echo "inactive")
  if [[ "${prod_state}" == "active" ]]; then
    echo "  OK: both layers active. Sightings will accumulate in the occupancy DB"
    echo "      with source_type=radiod-hackrf."
    echo "  Watch: journalctl --user -u ${HACKRF_PRODUCER_UNIT} -f"
  else
    echo "  WARNING: ${HACKRF_PRODUCER_UNIT} did not stay active (state: ${prod_state})." >&2
    echo "  Diagnose: journalctl --user -u ${HACKRF_PRODUCER_UNIT} --no-pager -n 40" >&2
    exit 1
  fi
}

hackrf_interactive() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: 'hackrf interactive' toggles a system-level service" >&2
    echo "       (${HACKRF_RADIOD_INSTANCE}) and needs root. Re-run with sudo." >&2
    exit 1
  fi
  echo "-- Switching HackRF to interactive mode --"
  echo "  Disabling and stopping ${HACKRF_PRODUCER_UNIT}..."
  user_svc disable --now "${HACKRF_PRODUCER_UNIT}" 2>/dev/null || true
  echo "  Disabling and stopping ${HACKRF_RADIOD_INSTANCE}..."
  systemctl disable --now "${HACKRF_RADIOD_INSTANCE}" 2>/dev/null || true
  echo "  OK: HackRF is now free."
  echo "  For OpenWebRX+ interactive use: enable its HackRF profile in"
  echo "  Settings -> SDR devices (if not already), then select it on the"
  echo "  main receiver page."
}

hackrf_cmd() {
  local sub="${1:-status}"
  case "${sub}" in
    ai)          hackrf_ai ;;
    interactive) hackrf_interactive ;;
    status)      hackrf_status ;;
    *) echo "hackrf sub-command must be: ai | interactive | status" >&2; exit 2 ;;
  esac
}

# --- helper: reach the operator's --user services from either bare or
# sudo invocation. Same helper as rx888-mode.sh; when SUDO_USER is set,
# we run systemctl --user as that user with the right session env.
user_svc() {
  # $@ passed through to 'systemctl --user'
  if [[ -n "${SUDO_USER:-}" ]]; then
    local uid; uid=$(id -u "${SUDO_USER}")
    sudo -u "${SUDO_USER}" \
        XDG_RUNTIME_DIR="/run/user/${uid}" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
        systemctl --user "$@"
  else
    systemctl --user "$@"
  fi
}

# --- rtlsdr / hackrf: per-device status ---------------------------------
device_status() {  # $1 = label, $2 = id pattern, $3 = instance name
  local label="$1" ids="$2" instance="$3"
  local unit="vhf-uhf-occupancy@${instance}.service"
  local prod_state
  prod_state=$(user_svc is-active "${unit}" 2>/dev/null || echo "inactive")
  echo "== ${label} =="
  if usb_present "${ids}"; then
    echo "  Present on USB."
    echo "  OpenWebRX+ (system-wide): $(owrx_state)"
    if [[ "${prod_state}" == "active" ]]; then
      echo "  Occupancy producer (${unit}): RUNNING"
      echo "  Mode: AI (occupancy producer holds the device)."
    else
      echo "  Occupancy producer (${unit}): stopped"
      echo "  Mode: interactive/free (available to OpenWebRX+)."
    fi
  else
    echo "  Not detected on USB."
  fi
  echo
  echo "  To flip: ./scripts/sdr-mode.sh ${instance} {ai | interactive}"
}

# --- rtlsdr / hackrf: mode switches -------------------------------------
mode_device_ai() {  # $1 = label, $2 = instance
  local label="$1" instance="$2"
  local unit="vhf-uhf-occupancy@${instance}.service"
  echo "-- Switching ${label} to AI mode (vhf-uhf-occupancy@${instance}) --"
  # If OpenWebRX+ is running with the device's profile enabled, it may be
  # holding the device -- warn (we can't safely toggle OWRX+ profiles from
  # a script, and stopping OWRX+ entirely is too heavy since it may be
  # serving other SDRs).
  if is_active "${OWRX_UNIT}"; then
    echo "  NOTE: OpenWebRX+ is running. If its ${label} profile is enabled,"
    echo "        the producer may hit LIBUSB_ERROR_BUSY. Disable the"
    echo "        ${label} profile in OpenWebRX+ Settings -> SDR devices"
    echo "        first, then re-run this command."
  fi
  echo "  Enabling and starting ${unit}..."
  if ! user_svc enable --now "${unit}"; then
    echo "  ERROR: failed to enable/start ${unit}." >&2
    echo "  Check: journalctl --user -u ${unit} --no-pager -n 30" >&2
    exit 1
  fi
  sleep 2
  local state
  state=$(user_svc is-active "${unit}" 2>/dev/null || echo "inactive")
  if [[ "${state}" == "active" ]]; then
    echo "  OK: ${unit} active. Sightings will accumulate in the occupancy DB."
    echo "  Watch: journalctl --user -u ${unit} -f"
  else
    echo "  WARNING: ${unit} did not stay active (state: ${state})." >&2
    echo "  Common causes: device held by OpenWebRX+ (see NOTE above), or" >&2
    echo "  the subprocess CLI (hackrf_transfer / rtl_sdr) not installed." >&2
    echo "  Diagnose: journalctl --user -u ${unit} --no-pager -n 40" >&2
    exit 1
  fi
}

mode_device_interactive() {  # $1 = label, $2 = instance
  local label="$1" instance="$2"
  local unit="vhf-uhf-occupancy@${instance}.service"
  echo "-- Switching ${label} to interactive mode --"
  echo "  Disabling and stopping ${unit}..."
  user_svc disable --now "${unit}" 2>/dev/null || true
  echo "  OK: ${label} is now free."
  echo "  For OpenWebRX+ interactive use: enable its ${label} profile in"
  echo "  Settings -> SDR devices (if not already), then select it on the"
  echo "  main receiver page."
}

# --- dispatch ------------------------------------------------------------
# Per-device dispatch helper: interprets the second arg (ai|interactive|
# status) for the vhf-uhf-occupancy templated service.
device_cmd() {  # $1 = label, $2 = ids pattern, $3 = instance name, $4 = verb
  local label="$1" ids="$2" instance="$3" verb="${4:-status}"
  case "${verb}" in
    ai)          mode_device_ai          "${label}" "${instance}" ;;
    interactive) mode_device_interactive "${label}" "${instance}" ;;
    status)      device_status           "${label}" "${ids}" "${instance}" ;;
    *)
      echo "Usage: $0 ${instance} {ai | interactive | status}" >&2
      exit 2 ;;
  esac
}

case "${1:-status}" in
  status)  status_all ;;
  rx888)   rx888_cmd "${2:-status}" ;;
  rtlsdr)  device_cmd "RTL-SDR" "${RTLSDR_IDS}" "rtlsdr" "${2:-status}" ;;
  hackrf)  hackrf_cmd "${2:-status}" ;;
  *)
    echo "Usage: $0 {status | rx888 <ai|interactive|status> | hackrf <ai|interactive|status> | rtlsdr <ai|interactive|status>}"
    echo
    echo "  status                     true ownership of all SDRs"
    echo "  rx888 ai                   RX-888 -> radiod (AI/occupancy)"
    echo "  rx888 interactive          RX-888 -> OpenWebRX+ (waterfall)"
    echo "  rx888 status               RX-888 detail (via rx888-mode.sh)"
    echo "  hackrf ai                  HackRF -> radiod@hackrf-2m + producer (needs sudo)"
    echo "  hackrf interactive         HackRF -> free/OWRX+ (needs sudo)"
    echo "  hackrf status              HackRF detail (radiod + producer state + USB)"
    echo "  rtlsdr ai                  DEPRECATED -- RTL-SDR is OpenWebRX+-only now, see script header"
    echo "  rtlsdr interactive         RTL-SDR -> free/OWRX+ (the only supported mode now)"
    echo "  rtlsdr status              RTL-SDR detail (producer state + USB)"
    exit 2 ;;
esac
