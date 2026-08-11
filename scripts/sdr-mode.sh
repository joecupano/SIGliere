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
#   - HackRF migrated to its own radiod instance(s). Unlike RX-888
#     (always radiod@rx888-hf), HackRF can run any ONE of several band
#     PROFILES at a time — radiod@hackrf-<name>.conf under
#     ingest/ka9q-radio/ (2m and 70cm ship in this repo; an operator can
#     scaffold more via 'hackrf new <name>') — since it's still a single
#     USB device, only one profile owns it at once. HackRF's AI mode has
#     the SAME two-layer shape as RX-888: a system-level
#     radiod@hackrf-<name> instance (owns the USB device) plus a --user
#     radiod-occupancy-hackrf.service (the producer, which auto-detects
#     WHICHEVER profile is currently active — see
#     decode/radiod_occupancy_producer.py's resolve_hackrf_profile() —
#     so it follows a profile switch without needing its own
#     reconfiguration). 'hackrf ai [profile]'/'hackrf interactive' toggle
#     BOTH layers together; see hackrf_ai()/hackrf_interactive() below.
#     'hackrf list' shows available profiles and which (if any) is
#     active; 'hackrf new <name>' scaffolds a new one. This REPLACES the
#     old vhf-uhf-occupancy@hackrf scan-based service — that unit is
#     retired for HackRF (still installed as a template file for
#     rtlsdr's use below, but no longer the HackRF path).
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
#   sudo ./scripts/sdr-mode.sh hackrf ai [profile]  # HackRF -> radiod@hackrf-<profile> + producer
#   sudo ./scripts/sdr-mode.sh hackrf interactive   # HackRF -> free/OWRX+
#   ./scripts/sdr-mode.sh hackrf list               # available HackRF band profiles + which is active
#   ./scripts/sdr-mode.sh hackrf new <name>         # scaffold a new radiod@hackrf-<name>.conf
#   ./scripts/sdr-mode.sh rtlsdr ai                 # DEPRECATED -- see note above, RTL-SDR is OpenWebRX+-only now
#   ./scripts/sdr-mode.sh rtlsdr interactive        # RTL-SDR -> free/OWRX+ (the only supported mode now)
#   ./scripts/sdr-mode.sh rtlsdr status             # per-device detail
#   ./scripts/sdr-mode.sh hackrf status
# ---------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OWRX_UNIT="openwebrx"
RADIOD_UNIT="radiod@rx888-hf"
KA9Q_CONF_DIR="${SCRIPT_DIR}/../ingest/ka9q-radio"
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

# --- HackRF band-profile discovery ---------------------------------------
# HackRF can run any ONE of several radiod@hackrf-<name>.conf profiles
# (single-owner USB device — only one at a time). These two helpers are
# the single source of truth other hackrf_* functions build on, rather
# than any of them re-globbing ingest/ka9q-radio/ themselves.

# One profile name per line (the <name> in radiod@hackrf-<name>.conf),
# sorted. Empty output (no lines) if none exist.
hackrf_profiles() {
  local f base
  for f in "${KA9Q_CONF_DIR}"/radiod@hackrf-*.conf; do
    [[ -e "${f}" ]] || continue
    base="$(basename "${f}" .conf)"   # radiod@hackrf-2m
    echo "${base#radiod@hackrf-}"     # 2m
  done | sort
}

# Prints the profile name of whichever radiod@hackrf-<name> systemd unit
# is currently active, and returns 0 — or prints nothing and returns 1 if
# none is (normal/expected, e.g. HackRF in OpenWebRX+/interactive mode).
hackrf_active_profile() {
  local name
  for name in $(hackrf_profiles); do
    if is_active "radiod@hackrf-${name}"; then
      echo "${name}"
      return 0
    fi
  done
  return 1
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

  # HackRF — now has a real AI (radiod@hackrf-<profile> + producer) owner,
  # same treatment as RX-888, except which band PROFILE is active varies
  # (see hackrf_active_profile()). RTL-SDR below is unchanged (no
  # dedicated radiod owner in this script yet).
  printf '  %-10s ' "HackRF:"
  local hackrf_prod_state hackrf_active
  if usb_present "${HACKRF_IDS}"; then
    hackrf_active="$(hackrf_active_profile || true)"
    if [[ -n "${hackrf_active}" ]]; then
      hackrf_prod_state=$(user_svc is-active "${HACKRF_PRODUCER_UNIT}" 2>/dev/null || echo "inactive")
      if [[ "${hackrf_prod_state}" == "active" ]]; then
        echo "AI/occupancy (profile '${hackrf_active}', radiod + producer both running)"
      else
        echo "radiod@hackrf-${hackrf_active} running, but producer (${HACKRF_PRODUCER_UNIT}) is not"
      fi
    elif is_active "${OWRX_UNIT}"; then
      echo "likely OpenWebRX+ (no radiod@hackrf-* instance active, OWRX running)"
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
  echo "== HackRF (via radiod) =="
  if ! usb_present "${HACKRF_IDS}"; then
    echo "  Not detected on USB."
    return
  fi
  echo "  Present on USB."
  echo "  OpenWebRX+ (system-wide): $(owrx_state)"
  local active; active="$(hackrf_active_profile || true)"
  if [[ -n "${active}" ]]; then
    echo "  Active profile: ${active}  (radiod@hackrf-${active})"
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
    echo "  No radiod@hackrf-* instance active."
    echo "  Mode: interactive/free (available to OpenWebRX+), or no owner at all."
  fi
  echo
  echo "  Available profiles: ./scripts/sdr-mode.sh hackrf list"
  echo "  To flip: sudo ./scripts/sdr-mode.sh hackrf {ai [profile] | interactive}"
}

# List every radiod@hackrf-*.conf profile this repo has, whether it's
# deployed to /etc/radio/ (and whether that deployed copy matches the
# repo — a real drift mode, see PROJECT_STATE files' "re-diff before
# trusting" notes elsewhere), and which one (if any) is currently active.
hackrf_list() {
  echo "== HackRF radiod profiles (${KA9Q_CONF_DIR}/radiod@hackrf-*.conf) =="
  local active; active="$(hackrf_active_profile || true)"
  local name found=0
  for name in $(hackrf_profiles); do
    found=1
    local dst="/etc/radio/radiod@hackrf-${name}.conf"
    local deployed="not deployed"
    if [[ -f "${dst}" ]]; then
      if diff -q "${KA9Q_CONF_DIR}/radiod@hackrf-${name}.conf" "${dst}" >/dev/null 2>&1; then
        deployed="deployed, matches repo"
      else
        deployed="deployed, DIFFERS from repo — redeploy before trusting"
      fi
    fi
    local mark=" "
    [[ "${name}" == "${active}" ]] && mark="*"
    printf "  %s %-16s %s\n" "${mark}" "${name}" "${deployed}"
  done
  if [[ "${found}" -eq 0 ]]; then
    echo "  (none found)"
  fi
  echo
  echo "  * = currently active."
  echo "  Select one:   sudo ./scripts/sdr-mode.sh hackrf ai <name>"
  echo "  Create a new: ./scripts/sdr-mode.sh hackrf new <name>"
}

# Scaffold a new radiod@hackrf-<name>.conf. Structure only (global +
# hardware section with the source-verified gain keys, one placeholder
# channel block) — deliberately does NOT invent real frequencies for
# whatever band/purpose this profile is for; the operator fills those in.
hackrf_new() {
  local name="${1:-}"
  if [[ -z "${name}" ]]; then
    echo "Usage: $0 hackrf new <name>" >&2
    echo "  <name> becomes radiod@hackrf-<name>.conf and the systemd instance" >&2
    echo "  radiod@hackrf-<name> — e.g. '70cm', '915ism'. Lowercase" >&2
    echo "  alphanumeric/hyphens only (it's a systemd instance name)." >&2
    exit 2
  fi
  if [[ ! "${name}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    echo "ERROR: name must be lowercase alphanumeric/hyphens, got: '${name}'" >&2
    exit 1
  fi

  local out="${KA9Q_CONF_DIR}/radiod@hackrf-${name}.conf"
  if [[ -e "${out}" ]]; then
    echo "ERROR: ${out} already exists — not overwriting." >&2
    echo "       ./scripts/sdr-mode.sh hackrf list  to see existing profiles." >&2
    exit 1
  fi

  cat > "${out}" <<CONF
# ============================================================================
# sovereign-sigint : radiod@hackrf-${name}.conf
#
# Scaffolded $(date -u +%Y-%m-%d) by 'scripts/sdr-mode.sh hackrf new ${name}'.
# NOT a working config yet — fill in the CHANNEL DEFINITIONS section below
# with real frequencies for whatever band/purpose this profile is for.
# Nothing here invents them for you; verify your own frequencies rather
# than trust a generated placeholder. See radiod@hackrf-2m.conf or
# radiod@hackrf-70cm.conf alongside this file for real, working examples
# of the channel-section shape.
#
# Once real channels are filled in:
#   ./scripts/sdr-mode.sh hackrf list              # confirm it's picked up
#   sudo ./scripts/sdr-mode.sh hackrf ai ${name}   # deploy + activate
#
# Gain block below matches the source-verified key mapping for this
# ka9q-radio build (hackrf.c, traced 2026-08-11 — see
# docs/mcp-validation-evidence.md and radiod@hackrf-2m.conf's header for
# the full finding):
#   lna-gain    -> hackrf_set_antenna_enable() — boolean, NOT a dB value.
#                  Any nonzero value just enables the antenna port/bias.
#   mixer-gain  -> hackrf_set_lna_gain() — HackRF's REAL onboard LNA
#                  gain, 0-40dB in 8dB steps (0/8/16/24/32/40). Note the
#                  name swap from HackRF's own vocabulary — that's this
#                  ka9q-radio build's naming, not a typo.
#   if-gain     -> hackrf_set_vga_gain() — HackRF's real baseband VGA
#                  gain, 0-62dB. Works despite not being in this build's
#                  own "recognized keys" advisory list (which names
#                  "vga-gain" instead — a key the code never actually
#                  reads). The advisory warning it prints is non-fatal.
# Do NOT use "mix-gain" — it is not a recognized key on this build and
# will be silently ignored (falls back to a hardcoded default instead of
# erroring), which is exactly the bug radiod@hackrf-2m.conf had until
# 2026-08-11.
# ============================================================================

[global]
hardware = hackrf
status = hackrf-${name}-status.local
mode = fm
samprate = 12000
ttl = 0
fft-threads = 2
overlap = 5

# ----------------------------------------------------------------------
# Front-end hardware section
# ----------------------------------------------------------------------
[hackrf]
device = "hackrf"
description = "sovereign-sigint HackRF One — ${name} profile"

# Sample rate (Hz): cover whatever span this profile's channels need,
# comfortably inside HackRF's 20 Msps ceiling. NOT filled in here — it
# depends on the real band plan you're targeting. radiod@hackrf-2m.conf
# uses 8000000 for a 2.13 MHz span; scale from that, don't copy it blind.
samprate = REPLACE_ME_SAMPRATE_HZ

lna-gain = 1
mixer-gain = 24

# ============================================================================
# CHANNEL DEFINITIONS — REPLACE THIS PLACEHOLDER SECTION.
# One [section] per demodulated channel. freq is in Hz, mode is radiod's
# mode name (fm/nfm/wfm/am/usb/lsb/cw), data is the multicast hostname
# sightings get recorded under (scripts/ka9q-channel-activity-test.py and
# decode/radiod_occupancy_producer.py both parse this shape directly).
# ============================================================================

[REPLACE_ME_CHANNEL_NAME]
freq = 0
mode = fm
data = hackrf-${name}-REPLACE_ME-pcm.local
CONF

  echo "Scaffolded: ${out}"
  echo "Edit it with real channel frequencies, then:"
  echo "  ./scripts/sdr-mode.sh hackrf list"
  echo "  sudo ./scripts/sdr-mode.sh hackrf ai ${name}"
}

hackrf_ai() {
  local profile="${1:-}"
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: 'hackrf ai' toggles a system-level radiod@hackrf-<profile>" >&2
    echo "       service and needs root. Re-run with sudo." >&2
    exit 1
  fi

  local available; available="$(hackrf_profiles)"
  if [[ -z "${available}" ]]; then
    echo "ERROR: no radiod@hackrf-*.conf profiles found in ${KA9Q_CONF_DIR}." >&2
    echo "       Create one first: ./scripts/sdr-mode.sh hackrf new <name>" >&2
    exit 1
  fi

  if [[ -z "${profile}" ]]; then
    local current; current="$(hackrf_active_profile || true)"
    if [[ -n "${current}" ]]; then
      profile="${current}"
      echo "-- No profile given; re-affirming the currently active one: ${profile} --"
    elif [[ "$(wc -l <<<"${available}")" -eq 1 ]]; then
      profile="${available}"
      echo "-- No profile given, only one exists: ${profile} --"
    else
      echo "ERROR: multiple HackRF profiles exist and none is currently active —" >&2
      echo "       specify which one:" >&2
      echo "${available}" | sed 's/^/         /' >&2
      echo "       sudo ./scripts/sdr-mode.sh hackrf ai <name>" >&2
      echo "       (./scripts/sdr-mode.sh hackrf list for detail)" >&2
      exit 2
    fi
  elif ! grep -qxF "${profile}" <<<"${available}"; then
    echo "ERROR: no such profile '${profile}'. Available:" >&2
    echo "${available}" | sed 's/^/  /' >&2
    exit 1
  fi

  local instance="radiod@hackrf-${profile}"
  local src="${KA9Q_CONF_DIR}/radiod@hackrf-${profile}.conf"
  local dst="/etc/radio/radiod@hackrf-${profile}.conf"

  echo "-- Switching HackRF to AI mode: ${instance} + ${HACKRF_PRODUCER_UNIT} --"
  if is_active "${OWRX_UNIT}"; then
    echo "  NOTE: OpenWebRX+ is running. If its HackRF profile is enabled,"
    echo "        ${instance} may fail to open the device. Disable the"
    echo "        HackRF profile in OpenWebRX+ Settings -> SDR devices first,"
    echo "        then re-run this command."
  fi

  # Single-owner USB device: stop any OTHER currently active HackRF
  # profile first, so radiod@hackrf-${profile} isn't fighting it for
  # the same hardware.
  local other
  for other in $(hackrf_profiles); do
    [[ "${other}" == "${profile}" ]] && continue
    if is_active "radiod@hackrf-${other}"; then
      echo "  Stopping currently active profile radiod@hackrf-${other} first"
      echo "  (single-owner USB device — only one profile can run at a time)..."
      systemctl disable --now "radiod@hackrf-${other}" 2>/dev/null || true
    fi
  done

  echo "  Deploying ${src} -> ${dst}..."
  if [[ ! -f "${dst}" ]] || ! diff -q "${src}" "${dst}" >/dev/null 2>&1; then
    rm -f "${dst}"
    if ! cp "${src}" "${dst}"; then
      echo "  ERROR: could not deploy ${dst} — check /etc/radio is writable" >&2
      echo "  (group 'radio' should own it and be group-writable)." >&2
      exit 1
    fi
  else
    echo "  (already deployed and matches the repo copy, skipping)"
  fi

  echo "  Enabling and starting ${instance}..."
  if ! systemctl enable --now "${instance}"; then
    echo "  ERROR: failed to enable/start ${instance}." >&2
    echo "  Check: journalctl -u ${instance} --no-pager -n 40" >&2
    echo "  Common cause: HackRF front-end support not confirmed in your" >&2
    echo "  installed radiod build — see ingest/ka9q-radio/radiod@hackrf-2m.conf" >&2
    echo "  header before troubleshooting further." >&2
    exit 1
  fi
  sleep 2
  if ! is_active "${instance}"; then
    echo "  WARNING: ${instance} did not stay active." >&2
    echo "  Diagnose: journalctl -u ${instance} --no-pager -n 40" >&2
    exit 1
  fi

  echo "  Enabling and (re)starting ${HACKRF_PRODUCER_UNIT} so it picks up"
  echo "  '${profile}' immediately (it auto-detects the active profile on"
  echo "  every sweep regardless, but restarting gives instant feedback)..."
  if ! user_svc enable --now "${HACKRF_PRODUCER_UNIT}"; then
    echo "  ERROR: failed to enable/start ${HACKRF_PRODUCER_UNIT}." >&2
    echo "  Check: journalctl --user -u ${HACKRF_PRODUCER_UNIT} --no-pager -n 30" >&2
    echo "  (radiod@hackrf-${profile} is up, but the producer isn't — DB won't fill.)" >&2
    exit 1
  fi
  user_svc restart "${HACKRF_PRODUCER_UNIT}" 2>/dev/null || true
  sleep 2
  local prod_state
  prod_state=$(user_svc is-active "${HACKRF_PRODUCER_UNIT}" 2>/dev/null || echo "inactive")
  if [[ "${prod_state}" == "active" ]]; then
    echo "  OK: both layers active on profile '${profile}'. Sightings will"
    echo "      accumulate with source_type=radiod-hackrf, tagged"
    echo "      radiod_instance=hackrf-${profile} in metadata_json."
    echo "  Watch: journalctl --user -u ${HACKRF_PRODUCER_UNIT} -f"
  else
    echo "  WARNING: ${HACKRF_PRODUCER_UNIT} did not stay active (state: ${prod_state})." >&2
    echo "  Diagnose: journalctl --user -u ${HACKRF_PRODUCER_UNIT} --no-pager -n 40" >&2
    exit 1
  fi
}

hackrf_interactive() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: 'hackrf interactive' toggles a system-level" >&2
    echo "       radiod@hackrf-<profile> service and needs root. Re-run with sudo." >&2
    exit 1
  fi
  echo "-- Switching HackRF to interactive mode --"
  echo "  Disabling and stopping ${HACKRF_PRODUCER_UNIT}..."
  user_svc disable --now "${HACKRF_PRODUCER_UNIT}" 2>/dev/null || true

  local name any_active=0
  for name in $(hackrf_profiles); do
    if is_active "radiod@hackrf-${name}"; then
      echo "  Disabling and stopping radiod@hackrf-${name}..."
      systemctl disable --now "radiod@hackrf-${name}" 2>/dev/null || true
      any_active=1
    fi
  done
  [[ "${any_active}" -eq 0 ]] && echo "  (no radiod@hackrf-* instance was active)"

  echo "  OK: HackRF is now free."
  echo "  For OpenWebRX+ interactive use: enable its HackRF profile in"
  echo "  Settings -> SDR devices (if not already), then select it on the"
  echo "  main receiver page."
}

hackrf_cmd() {
  local sub="${1:-status}"
  case "${sub}" in
    ai)          hackrf_ai "${2:-}" ;;
    interactive) hackrf_interactive ;;
    status)      hackrf_status ;;
    list)        hackrf_list ;;
    new)         hackrf_new "${2:-}" ;;
    *)
      echo "hackrf sub-command must be: ai [profile] | interactive | status | list | new <name>" >&2
      exit 2 ;;
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
  hackrf)  hackrf_cmd "${2:-status}" "${3:-}" ;;
  *)
    echo "Usage: $0 {status | rx888 <ai|interactive|status> | hackrf <ai [profile]|interactive|status|list|new NAME> | rtlsdr <ai|interactive|status>}"
    echo
    echo "  status                     true ownership of all SDRs"
    echo "  rx888 ai                   RX-888 -> radiod (AI/occupancy)"
    echo "  rx888 interactive          RX-888 -> OpenWebRX+ (waterfall)"
    echo "  rx888 status               RX-888 detail (via rx888-mode.sh)"
    echo "  hackrf ai [profile]        HackRF -> radiod@hackrf-<profile> + producer (needs sudo)"
    echo "                             profile omitted: reaffirm active one, or the only one if just one exists"
    echo "  hackrf interactive         HackRF -> free/OWRX+ (needs sudo)"
    echo "  hackrf status              HackRF detail (active profile + producer state + USB)"
    echo "  hackrf list                available HackRF band profiles + which is active"
    echo "  hackrf new NAME            scaffold ingest/ka9q-radio/radiod@hackrf-NAME.conf"
    echo "  rtlsdr ai                  DEPRECATED -- RTL-SDR is OpenWebRX+-only now, see script header"
    echo "  rtlsdr interactive         RTL-SDR -> free/OWRX+ (the only supported mode now)"
    echo "  rtlsdr status              RTL-SDR detail (producer state + USB)"
    exit 2 ;;
esac
