#!/usr/bin/env bash
# scripts/phase6-ka9q-radio.sh
#
# Phase 6, part 1 of 6 — ka9q-radio (radiod), the HF ingest daemon for
# the RX-888 MkII. See docs/build-order.md Phase 6. This is the
# foundation the rest of Phase 6 (occupancy DB, callsign tracking)
# depends on — nothing downstream is meaningful without a working HF
# stream first.
#
# Built from source (no apt package) per ka9q-radio's own docs:
# https://github.com/ka9q/ka9q-radio/blob/main/docs/INSTALL.md
#
# This script INSTALLS. Run scripts/phase6-ka9q-radio-validate.sh
# afterward.
#
# Usage: sudo ./scripts/phase6-ka9q-radio.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${SUDO_USER:-$(id -un)}"
SRC_ROOT="/opt/sovereign-sigint/src"
INSTANCE_NAME="rx888-hf"  # matches ingest/ka9q-radio/radiod@rx888-hf.conf

echo "== Phase 6.1: ka9q-radio (radiod) =="

sudo apt update

# ---------------------------------------------------------------------
# Build dependencies — per ka9q-radio's own INSTALL.md. libfftw3-dev
# is NOT here — moved to Phase 2 (scripts/phase2-os-packages.sh), since
# FFTW is general infrastructure multiple Phase 6 tools need (radiod
# AND GNU Radio), not something specific to ka9q-radio.
# ---------------------------------------------------------------------
echo "-- Installing build dependencies --"
sudo apt install -y \
  git avahi-utils build-essential make gcc \
  libairspy-dev libairspyhf-dev libavahi-client-dev libbsd-dev \
  libhackrf-dev libiniparser-dev libncurses5-dev \
  libopus-dev librtlsdr-dev libusb-1.0-0-dev libusb-dev \
  portaudio19-dev libasound2-dev uuid-dev rsync libogg-dev \
  libsamplerate-dev libliquid-dev libncursesw5-dev libbladerf-dev

# ---------------------------------------------------------------------
# Build and install
# ---------------------------------------------------------------------
echo "-- Cloning and building ka9q-radio --"
sudo mkdir -p "${SRC_ROOT}"
sudo chown "${TARGET_USER}:${TARGET_USER}" "${SRC_ROOT}"

# Pin to a known-working commit rather than tracking bare main.
# ka9q-radio's main branch moves fast and periodically breaks external
# builds — the projecthorus/auto_rx project pins for exactly this reason.
# Override with KA9Q_COMMIT=<sha> (or KA9Q_COMMIT=main to track tip) if
# you deliberately want a different revision.
#
# RE-PINNED 2026-08-11 (was e1224dcd1991637ba8e1caa68cd802e1b22933de,
# 2025-11-08 -- 9 months stale at the time of this update; see
# docs/mcp-validation-evidence.md for the full check). Verified against
# GitHub's live API before re-pinning, not assumed:
#   - Confirmed via `git log -1` on this host's actual installed source
#     that the old pin really was what got built, not just what this
#     script claimed.
#   - The ORIGINAL reason this script pins at all (a bare `make` on main
#     trying to compile fobos.c against headers we don't have) is still
#     real on current main -- upstream's build system changed shape
#     since the old pin (see the ENABLE_* note below) but the underlying
#     risk didn't go away.
#   - Checked ka9q/ka9q-radio#239 (this project's own filed bug, the
#     reason RTL-SDR is currently OpenWebRX+-only, see
#     docs/mcp-validation-evidence.md and README.md): closed 2026-08-10,
#     but NOT because the fix is confirmed merged/working -- Karn pointed
#     at his separate, not-yet-merged `setup-restructure` branch, and the
#     issue was closed pending someone actually testing that branch, which
#     had not happened as of this pin update. Re-pinning to main does
#     NOT include that fix. Don't assume the RTL-SDR descope can be
#     revisited just because this pin moved forward -- that needs its own
#     deliberate test against `setup-restructure` specifically.
KA9Q_COMMIT="${KA9Q_COMMIT:-1c0a4231d20f4257569715325242d6f2432dd939}"  # main HEAD as of 2026-08-10

if [[ ! -d "${SRC_ROOT}/ka9q-radio" ]]; then
  git clone --quiet https://github.com/ka9q/ka9q-radio.git "${SRC_ROOT}/ka9q-radio"
fi
cd "${SRC_ROOT}/ka9q-radio"
git fetch --quiet origin
if [[ "${KA9Q_COMMIT}" == "main" ]]; then
  git checkout --quiet main && git pull --quiet
  echo "  WARNING: tracking ka9q-radio main (unpinned) — may break; see notes above."
else
  git checkout --quiet "${KA9Q_COMMIT}"
  echo "  Pinned to ka9q-radio ${KA9Q_COMMIT}"
fi

# Per-driver ENABLE_* build flags (top-level Makefile, confirmed live
# via GitHub 2026-08-11 -- this is a NEWER build system than the old
# Nov 2025 pin had; the old "don't pass FOBOS=1" comment described the
# OPPOSITE convention (opt-in flags) and no longer applies). Current
# upstream Makefile defaults nearly everything to 1 (on), including
# ENABLE_FOBOS and ENABLE_HYDRASDR -- both need third-party vendor
# headers (libfobos, libhydrasdr) that are NOT apt-installable and NOT
# installed on this host (confirmed: no such packages found via
# apt-cache, no headers found anywhere on disk), so leaving either at
# its default 1 reproduces the exact `fatal error: ...h: No such file
# or directory` build failure this script has always pinned to avoid.
# Neither device is present on this build anyway. Every other ENABLE_*
# flag's dev headers ARE already installed above (airspy/airspyhf/
# bladerf/hackrf/rtlsdr) or need no vendor SDK (rx888, funcube,
# sig_gen), so they're left at their upstream defaults.
make clean >/dev/null 2>&1 || true   # clear any stale/partial prior build
make ENABLE_FOBOS=0 ENABLE_HYDRASDR=0 -j"$(nproc)"

# `make install` creates the 'radio' system user/group, installs
# /usr/local/sbin/radiod, and the systemd template unit
# /etc/systemd/system/radiod@.service. Per ka9q-radio's own docs, add
# your own user to the 'radio' group afterward so you can inspect/edit
# the installed files without becoming root each time.
#
# ENABLE_FOBOS=0 ENABLE_HYDRASDR=0 MUST be repeated here -- confirmed via
# a real failure 2026-08-11: `make install` is a SEPARATE invocation from
# the build above and does not inherit its command-line variables. Without
# repeating them, `install`'s own dependency chain rebuilds fobos.o fresh
# with ENABLE_FOBOS back at its unset `?= 1` default, hitting the exact
# `fatal error: fobos.h: No such file or directory` this script pins to
# avoid -- the line above alone does not prevent it.
sudo make ENABLE_FOBOS=0 ENABLE_HYDRASDR=0 install

echo "-- Adding ${TARGET_USER} to the 'radio' group --"
sudo usermod -aG radio "${TARGET_USER}"
echo "  NOTE: group membership won't take effect in your current shell"
echo "  session until you log out and back in (or run 'newgrp radio')."

# ---------------------------------------------------------------------
# Cross-phase permission check: radiod runs as the 'radio' system user
# just created above, NOT as the interactive user Phase 1's udev rule
# (scripts/phase1-hardware-drivers.sh) was installed and validated
# against. If that rule grants USB access by group membership rather
# than world-readable mode, 'radio' needs to be in that group too, or
# radiod hits a permissions error Phase 1's validation never would have
# caught (it never ran as 'radio'). Check the actual rule rather than
# assume either way.
# ---------------------------------------------------------------------
echo "-- Checking RX-888 udev rule for group-based access the 'radio' user needs too --"
RX888_UDEV_RULE="/etc/udev/rules.d/99-rx888.rules"
if [[ -f "${RX888_UDEV_RULE}" ]]; then
  RULE_GROUP="$(grep -oP 'GROUP="\K[^"]+' "${RX888_UDEV_RULE}" | head -1 || true)"
  if [[ -n "${RULE_GROUP}" ]]; then
    echo "  Rule grants access via group '${RULE_GROUP}' — adding 'radio' to it"
    sudo usermod -aG "${RULE_GROUP}" radio
    echo "  NOTE: this happens before radiod's first start below, so no"
    echo "  restart should be needed for this specific group grant to take"
    echo "  effect — but if you re-run this script after radiod is already"
    echo "  running, a restart would be needed then."
  else
    echo "  No GROUP= found in the rule — likely MODE-based (e.g. 0666,"
    echo "  world-accessible), in which case 'radio' needs no extra group."
    echo "  If radiod still hits a USB permissions error, inspect"
    echo "  ${RX888_UDEV_RULE} directly rather than assume this check covered it."
  fi
else
  echo "  WARNING: ${RX888_UDEV_RULE} not found — was Phase 1's RX-888"
  echo "  install run? If radiod hits a USB permissions error, that's why."
fi

# ---------------------------------------------------------------------
# Firmware placement — CONFIRMED via a real radiod startup log: this step
# is UNNECESSARY. radiod's rx888 support is a dynamically loaded driver
# (/usr/local/lib/ka9q-radio/rx888.so) that handles firmware upload to the
# FX3 internally — its startup log goes straight from "Dynamically loading
# rx888 hardware driver" to "found rx888 vendor 04b4, device 00f1 ...
# selected" with no standalone SDDC_FX3.img search step at all. The
# Phase-1-built rx888-firmware tree (and any "could not find SDDC_FX3.img"
# warning from an earlier version of this script) can be ignored — radiod
# does not use it. Kept here as a no-op/informational check in case a
# future ka9q-radio version changes this.
# ---------------------------------------------------------------------
echo "-- Firmware: handled internally by rx888.so, no placement needed --"
echo "  radiod's rx888 driver loads firmware into the FX3 itself at startup"
echo "  (confirmed via startup log: 'found rx888 vendor 04b4, device 00f1"
echo "  ... selected' with no separate firmware-file search). Nothing to do."

# ---------------------------------------------------------------------
# Deploy our radiod config and enable the service
# ---------------------------------------------------------------------
echo "-- Deploying radiod@${INSTANCE_NAME}.conf --"
sudo mkdir -p /etc/radio
sudo cp "${REPO_ROOT}/ingest/ka9q-radio/radiod@${INSTANCE_NAME}.conf" \
  "/etc/radio/radiod@${INSTANCE_NAME}.conf"

sudo systemctl daemon-reload
sudo systemctl enable --now "radiod@${INSTANCE_NAME}"

sleep 3
echo
echo "-- radiod status --"
sudo systemctl status "radiod@${INSTANCE_NAME}" --no-pager -l | head -20

# ---------------------------------------------------------------------
# FFTW wisdom — baseline generation was kicked off in the background
# back in Phase 2 (scripts/phase2-os-packages.sh), specifically so it
# would run across Phases 3-5 instead of being pure tacked-on wait time
# here. Check whether it's done, and whether radiod wants anything
# beyond what that baseline covers for THIS specific config.
# ---------------------------------------------------------------------
echo
echo "-- Checking Phase 2's background FFTW wisdom job --"
sudo mkdir -p /var/lib/ka9q-radio
sudo chown "${TARGET_USER}:radio" /var/lib/ka9q-radio

if [[ -f /tmp/fftw-wisdom-phase2.log ]]; then
  if pgrep -f fftwf-wisdom >/dev/null 2>&1; then
    echo "  Still running (started in Phase 2) — check progress:"
    echo "    tail -f /tmp/fftw-wisdom-phase2.log"
  else
    echo "  Finished. Log: /tmp/fftw-wisdom-phase2.log"
  fi
else
  echo "  No record of the Phase 2 background job (log file not found)."
  echo "  If Phase 2 predates this step, or ran on a different session,"
  echo "  system-wide wisdom may not exist yet — see below."
fi

echo
echo "-- Checking for additional wisdom radiod wants beyond the baseline --"
WISDOM_SUGGESTIONS="$(journalctl -u "radiod@${INSTANCE_NAME}" -n 500 --no-pager 2>/dev/null | grep -i "suggest running" || true)"

if [[ -n "${WISDOM_SUGGESTIONS}" ]]; then
  echo "  radiod suggested additional wisdom-generation command(s) — the"
  echo "  Phase 2 baseline didn't cover every transform this specific"
  echo "  config uses:"
  echo "${WISDOM_SUGGESTIONS}"
  echo
  echo "  Same caveat as Phase 2 — can take a while, fine to background:"
  echo "    nohup sudo <suggested command> > /tmp/fftw-wisdom-phase6.log 2>&1 &"
  echo "  radiod runs fine without this (just less CPU-efficient) in the"
  echo "  meantime — this is optimization, not a correctness requirement."
else
  echo "  No 'suggest running' wisdom messages seen yet in the last 500"
  echo "  log lines — the Phase 2 baseline likely already covers this"
  echo "  config's transforms. Recheck after the channels have run a"
  echo "  while if that changes:"
  echo "    journalctl -u radiod@${INSTANCE_NAME} | grep -i 'suggest running'"
fi

cat <<EOF

== Phase 6.1 install complete (pending validation) ==

Firmware is loaded internally by radiod's rx888.so driver — confirmed via a
real startup log ('found rx888 vendor 04b4, device 00f1 ... selected' with
no separate firmware-file search), so no firmware placement/path issue is
expected. If a FUTURE ka9q-radio version changes this and radiod logs a
firmware-file error, it'll name the exact path it searched:
  journalctl -u radiod@${INSTANCE_NAME} -n 50 --no-pager

Next: run scripts/phase6-ka9q-radio-validate.sh to confirm actual
demodulated output, not just "service active."

If radiod suggested any supplemental wisdom above (beyond the Phase 2
baseline), it's worth kicking off once you're not about to actively
debug the rest of Phase 6 on this same CPU.
EOF
