#!/usr/bin/env python3
"""
radiod_occupancy_producer.py — radiod occupancy producer (multi-device).

Originally built for the RX-888 (HF); generalized to support any radiod
front end via --device, since HackRF/RTL-SDR are migrating from the old
single-tuner scan approach (vhf_uhf_key_freq_producer.py) to their own
per-device radiod instances — the same simultaneous-multichannel-demod
win the RX-888 already has. See DEVICE_PROFILES below for the per-device
config path, source identity, and calibration state.

radiod continuously demodulates a fixed set of channels defined in its
config (e.g. WWV time standard, ham bands in several modes, FT8, APRS,
or — for a VHF/UHF front end — 2m/70cm key frequencies) and publishes
each as a PCM audio multicast stream. This producer measures how much
signal is present on each channel and records an occupancy sighting when
a channel is active. (The exact channel list is site-configurable; pick
beacons/bands receivable at YOUR location. Note: Canada's CHU shortwave
time station shut down 22 Jun 2026 — don't configure it as a channel
expecting signal.)

WHY THIS DESIGN (honest):
  radiod does NOT (in this build's config) publish a resolvable wideband IQ
  stream, and its status-metadata tools (powers/metadump) did not yield
  parseable per-channel levels in testing. The interface that IS proven to
  work is `pcmrecord`, which streams a channel's demodulated audio as WAV.
  So this producer measures per-channel audio power via pcmrecord rather
  than reading a wideband spectrum. That means it reports occupancy for the
  ~18 KNOWN channels radiod demodulates, each with a correct frequency and
  mode — not a full-HF spectral sweep. That is still far more than the
  single-frequency manual RTL-SDR/HackRF monitors, and it is real, running,
  continuous occupancy feeding the AI's database.

  If a wideband spectral producer is wanted later, radiod must first be
  reconfigured to publish its IQ stream (uncomment the [rx888] data= line),
  and a `powers`-based producer built against that SSRC. That is a separate
  effort; this producer uses only interfaces confirmed working.

HOW IT WORKS:
  For each channel parsed from radiod's config:
    1. Run `pcmrecord --catmode <data-stream>` for a short window, capturing
       WAV audio to memory.
    2. Compute RMS power of the samples, expressed in dBFS.
    3. If power >= threshold, the channel is "occupied" -> record a sighting
       at that channel's known frequency/mode via OccupancyDB.record_sighting.
  Repeat every --interval seconds.

USAGE:
  python3 radiod_occupancy_producer.py [--once] [--interval SEC]
      [--window SEC] [--threshold-dbfs DBFS] [--config PATH] [--verbose]

SINGLE-OWNER NOTE:
  The RX-888 must be owned by radiod (AI mode) for this to work. If
  OpenWebRX+ holds the RX-888, radiod is not running and this producer has
  nothing to read. See scripts/sdr-mode.sh / scripts/rx888-mode.sh.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import re
import select
import socket
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path


RTP_HEADER_SIZE = 12
RADIOD_MULTICAST_PORT = 5004

# Import the shared occupancy DB layer (same one every producer uses).
# This file lives at decode/radiod_occupancy_producer.py, so the repo root
# is parents[1] (decode/ -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "db"))
from occupancy_db import OccupancyDB  # noqa: E402

DEFAULT_DB = _REPO_ROOT / "db" / "occupancy.db"
_KA9Q_CONF_DIR = _REPO_ROOT / "ingest" / "ka9q-radio"

DEFAULT_INTERVAL_SEC = 60.0
DEFAULT_WINDOW_SEC = 2.0

# Per-device profile: radiod config path, source identity recorded with
# each sighting, and calibration state. --device selects one of these;
# --config/--threshold-dbfs/--db still override individual fields.
#
# source_type distinguishes DETECTION METHOD, not just device, per the
# reverse-compat decision made when migrating HackRF/RTL-SDR off the old
# scan-based vhf_uhf_key_freq_producer.py: 'radiod-rtlsdr' (this file,
# continuous simultaneous demod) stays queryable separately from the
# legacy 'rtlsdr' source_type (old single-tuner retune-and-scan sightings
# already sitting in occupancy.db) rather than collapsing both into one
# value. See docs/occupancy-guide.md.
DEVICE_PROFILES = {
    "rx888": {
        "config": _KA9Q_CONF_DIR / "radiod@rx888-hf.conf",
        "source_type": "radiod",
        "source_device": "rx888-hf",
        # Calibrated 2026-07 against a live sweep: the RX-888/radiod
        # demodulators sit at a ~-33 dBFS residual floor when a channel
        # carries no strong signal (a cluster of unrelated bands all read
        # -32..-36 simultaneously = the floor, not real occupancy).
        # Genuinely active channels stood clearly above it: WWV carriers
        # -18..-24, FT8 slots ~-21, an active CW channel -27. -30 dBFS
        # sits in the gap, marking real signals ACTIVE while treating the
        # demod floor as quiet. Recalibrate if front-end gain or antenna
        # changes; HF activity is also time/propagation dependent, but the
        # demod floor is the stable anchor.
        "threshold_dbfs": -30.0,
        "calibrated": True,
    },
    "rtlsdr": {
        "config": _KA9Q_CONF_DIR / "radiod@rtlsdr-vhf.conf",
        "source_type": "radiod-rtlsdr",
        "source_device": "rtl-sdr",
        # NOT yet field-calibrated. The old scan-based producer's -18 dBFS
        # threshold does NOT carry over: that number was RMS on raw IQ at
        # RF (vhf_uhf_key_freq_producer.py), whereas this producer measures
        # RMS on radiod's demodulated PCM audio output, like the RX-888
        # profile above — a different signal chain with its own floor.
        # Needs a --verbose calibration sweep (dead channel vs. a known-
        # active one, e.g. 146.520 during a local net) before this number
        # is trustworthy. Placeholder mirrors the RX-888 starting point
        # only because both share the "demod audio floor" measurement
        # method — not because the actual floor is expected to match.
        "threshold_dbfs": -30.0,
        "calibrated": False,
    },
    "hackrf": {
        "config": _KA9Q_CONF_DIR / "radiod@hackrf-2m.conf",
        "source_type": "radiod-hackrf",
        "source_device": "hackrf-one",
        # NOT yet field-calibrated, same reasoning as the rtlsdr profile
        # above: the existing scan-based producer's -14 dBFS threshold
        # (LNA 40 / VGA 48, hackrf_transfer raw-IQ RMS at a single retuned
        # frequency) does not transfer to this radiod/demodulated-FM-audio
        # signal chain. This profile is ALSO the least field-verified of
        # the three — HackRF's radiod driver itself is unconfirmed on this
        # build (see radiod@hackrf-2m.conf header: the project's own docs
        # disagree on whether HackRF support is delivered or still
        # forthcoming). Don't trust this profile's threshold, or that the
        # config even loads, without a field check first.
        "threshold_dbfs": -30.0,
        "calibrated": False,
    },
}


def parse_channels(config_path: Path) -> list[dict]:
    """Parse radiod's config into a list of channels the producer can read.

    Each channel needs a freq, a data (multicast) name, and a mode. IQ-mode
    channels are skipped — RMS-on-audio is meaningless for raw IQ.
    """
    text = config_path.read_text()
    channels: list[dict] = []
    # Split on section headers; first element is pre-first-section preamble.
    for block in re.split(r"\n\[", text):
        name = block.split("]", 1)[0].strip()
        if name in ("global", "rx888") or name.startswith("#"):
            continue
        freq_m = re.search(r"^\s*freq\s*=\s*(\d+)", block, re.M)
        data_m = re.search(r"^\s*data\s*=\s*(\S+)", block, re.M)
        mode_m = re.search(r"^\s*mode\s*=\s*(\S+)", block, re.M)
        if not (freq_m and data_m):
            continue
        mode = (mode_m.group(1) if mode_m else "usb").lower()
        if mode == "iq":
            # Raw IQ channel — not an audio stream; skip for power measurement.
            continue
        channels.append(
            {
                "name": name,
                "freq_hz": float(freq_m.group(1)),
                "mode": mode,
                "stream": data_m.group(1),
            }
        )
    return channels


def measure_channel_dbfs(stream: str, window_sec: float, verbose: bool) -> float | None:
    """Capture a short PCM window from a radiod multicast channel and return
    its RMS power in dBFS, or None if capture failed / no audio.

    This uses the same multicast address that radiod publishes for each
    channel, but it reads it directly with Python instead of relying on the
    pcmrecord wrapper, which was not yielding data in this environment even
    though the multicast packets were visible on the host.
    """
    if not stream:
        return None

    try:
        addr = socket.gethostbyname(stream)
    except socket.gaierror:
        if verbose:
            print(f"    {stream:14} (host lookup failed)")
        return None

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        sock.bind(('', RADIOD_MULTICAST_PORT))
        mreq = struct.pack('4s4s', socket.inet_aton(addr), socket.inet_aton('0.0.0.0'))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(window_sec)
    except OSError:
        return None

    raw = b""
    deadline = time.time() + window_sec
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                chunk = sock.recv(65535)
            except socket.timeout:
                break
            if not chunk:
                break
            raw += chunk
            if len(raw) >= 4096:
                break
    finally:
        sock.close()

    if len(raw) < 64:
        if verbose:
            print(f"    {stream:14} (no data — stream silent/absent)")
        return None

    samples = _extract_pcm_s16(raw)
    if not samples:
        return None

    sumsq = 0.0
    for s in samples:
        sumsq += float(s) * float(s)
    rms = math.sqrt(sumsq / len(samples))
    if rms <= 0:
        return -math.inf
    dbfs = 20.0 * math.log10(rms / 32768.0)
    return dbfs


def _extract_pcm_s16(raw: bytes) -> list[int]:
    """Extract 16-bit signed mono PCM samples from one or more RTP packets.

    The radiod multicast stream is RTP. Each packet contains a 12-byte RTP
    header followed by the audio payload. The payload bytes are 16-bit signed
    little-endian mono PCM samples, which we decode directly.
    """
    samples: list[int] = []
    offset = 0
    while offset + RTP_HEADER_SIZE <= len(raw):
        payload_len = len(raw) - offset - RTP_HEADER_SIZE
        if payload_len <= 0:
            break
        payload = raw[offset + RTP_HEADER_SIZE:offset + RTP_HEADER_SIZE + payload_len]
        offset += RTP_HEADER_SIZE + payload_len
        n = (len(payload) // 2) * 2
        if n == 0:
            continue
        samples.extend(struct.unpack("<%dh" % (n // 2), payload[:n]))
    return samples


def run_once(db: OccupancyDB, channels: list[dict], window_sec: float,
             threshold_dbfs: float, source_type: str, source_device: str,
             verbose: bool) -> int:
    """One sweep across all channels. Returns count of channels recorded active."""
    active = 0
    for ch in channels:
        dbfs = measure_channel_dbfs(ch["stream"], window_sec, verbose)
        if dbfs is None:
            continue
        state = "ACTIVE" if dbfs >= threshold_dbfs else "quiet"
        if verbose:
            fs = f"{dbfs:6.1f}" if dbfs != -math.inf else "  -inf"
            print(f"    {ch['name']:14} {ch['freq_hz']/1e6:8.4f} MHz "
                  f"{ch['mode']:4} {fs} dBFS  {state}")
        if dbfs >= threshold_dbfs:
            active += 1
            db.record_sighting(
                frequency_hz=ch["freq_hz"],
                source_type=source_type,
                source_device=source_device,
                mode=ch["mode"],
                metadata_json=(
                    '{"channel":"%s","power_dbfs":%.1f,"threshold_dbfs":%.1f}'
                    % (ch["name"], dbfs, threshold_dbfs)
                ),
            )
    return active


def main() -> int:
    ap = argparse.ArgumentParser(description="radiod occupancy producer")
    ap.add_argument("--device", choices=sorted(DEVICE_PROFILES), default="rx888",
                    help="radiod front end profile: selects config path, "
                         "source_type/source_device, and calibrated threshold "
                         "(default rx888, preserving pre-multi-device behavior)")
    ap.add_argument("--once", action="store_true",
                    help="run a single sweep and exit (default: loop)")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SEC,
                    help=f"seconds between sweeps (default {DEFAULT_INTERVAL_SEC})")
    ap.add_argument("--window", type=float, default=DEFAULT_WINDOW_SEC,
                    help=f"audio window per channel (default {DEFAULT_WINDOW_SEC}s)")
    ap.add_argument("--threshold-dbfs", type=float, default=None,
                    help="override the device profile's calibrated threshold dBFS")
    ap.add_argument("--config", type=Path, default=None,
                    help="override the device profile's radiod config path")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB,
                    help="occupancy DB path")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    profile = DEVICE_PROFILES[args.device]
    config_path = args.config if args.config is not None else profile["config"]
    threshold = args.threshold_dbfs if args.threshold_dbfs is not None else profile["threshold_dbfs"]
    source_type = profile["source_type"]
    source_device = profile["source_device"]

    if not profile["calibrated"]:
        print(f"WARNING: device '{args.device}' is NOT field-calibrated under "
              f"radiod — its threshold ({threshold} dBFS) is a placeholder "
              f"carried over from a different device profile's starting point, "
              f"not a measured floor for this device. Do a --verbose run "
              f"against a known-quiet vs. known-active channel and set "
              f"--threshold-dbfs explicitly before trusting ACTIVE/quiet calls.")

    if not config_path.exists():
        print(f"ERROR: radiod config not found: {config_path}", file=sys.stderr)
        return 1

    channels = parse_channels(config_path)
    if not channels:
        print("ERROR: no audio channels parsed from config.", file=sys.stderr)
        return 1

    db = OccupancyDB(args.db)
    print(f"radiod occupancy producer [{args.device}]: {len(channels)} channels, "
          f"source_type={source_type}, threshold {threshold} dBFS, "
          f"window {args.window}s"
          + ("" if args.once else f", every {args.interval}s"))

    try:
        while True:
            t0 = time.time()
            if args.verbose:
                print(f"-- sweep @ {time.strftime('%H:%M:%S')} --")
            active = run_once(db, channels, args.window, threshold,
                              source_type, source_device, args.verbose)
            print(f"sweep complete: {active}/{len(channels)} channels active")
            if args.once:
                break
            # Sleep the remainder of the interval (sweeps take real time).
            elapsed = time.time() - t0
            sleep_for = max(0.0, args.interval - elapsed)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
