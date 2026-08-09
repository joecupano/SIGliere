#!/usr/bin/env python3
"""
scripts/ka9q-channel-activity-test.py — read-only channel-activity test
for every configured ka9q-radio (radiod) front end (SDR).

For each radiod@<instance>.conf under ingest/ka9q-radio/ this:
  1. Checks whether radiod@<instance> is running (systemctl is-active).
  2. If it is (or --force says try anyway), parses the audio channels that
     instance's config tells radiod to demodulate, and measures a short
     live window of each channel's PCM multicast stream (dBFS), calling it
     ACTIVE/quiet against a threshold.
  3. Prints a per-channel table per SDR, then an overall summary.

This is a THIN CLI WRAPPER around the exact measurement code the
continuous occupancy producer uses
(decode/radiod_occupancy_producer.py: parse_channels, measure_channel_dbfs)
— same RTP/multicast handling, same dBFS math, same DEVICE_PROFILES
thresholds where one exists for a given config — so results here should
match what that producer would see. The one deliberate difference: this
script is READ-ONLY. It never calls OccupancyDB.record_sighting, so
running it does NOT add rows to db/occupancy.db. Use the real producer
(decode/radiod_occupancy_producer.py --device X --once --verbose) for a
run that also writes sightings.

INSTANCE NAME CAVEAT (real, not hypothetical — see
ingest/ka9q-radio/radiod@rtlsdr-adhoc.conf's own "NEXT STEPS" note): this
script's default guess for a config's systemd instance name is its
filename (radiod@<NAME>.conf -> radiod@<NAME>), matching the convention
every scripts/phase6-*.sh installer already assumes. That guess can be
STALE on a given box — e.g. one deployment runs radiod@rtlsdr-adhoc.conf's
content under the unit name "radiod@rtlsdr-v4" (see
mcp-server/config/nodes.rtlsdr-v4.disabled.json), not "radiod@rtlsdr-adhoc".
If `systemctl is-active` reports a config's guessed unit as inactive but
you know it's actually running under a different name, use
--instance <config-stem>=<real-systemd-instance> to correct it, e.g.:
    --instance rtlsdr-adhoc=rtlsdr-v4

USAGE:
  scripts/ka9q-channel-activity-test.py [--sdr NAME [NAME ...]]
      [--instance CONFIG_STEM=SYSTEMD_NAME [...]] [--window SEC]
      [--threshold-dbfs DBFS] [--force] [--verbose]
      [--conf-dir PATH]

  --sdr limits the run to specific config stems (the part of
  radiod@<stem>.conf between @ and .conf — e.g. rx888-hf, hackrf-2m,
  hackrf-70cm, rtlsdr-adhoc). Repeatable. Default: every radiod@*.conf
  found in ingest/ka9q-radio/.

  RADIOD_MULTICAST_IFACE (env var, same as the producer) overrides which
  local interface joins the multicast groups, if auto-detection picks
  the wrong one.

EXIT STATUS:
  0  ran cleanly (a checked SDR reporting all-quiet channels is NOT a
     failure here — real activity is time/propagation dependent)
  1  a structural problem: no configs found, an --sdr/--instance name
     that matched nothing, or every config failed to parse
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_KA9Q_CONF_DIR = _REPO_ROOT / "ingest" / "ka9q-radio"

# Reuse the producer's own parsing/measurement code rather than
# duplicating the RTP/multicast handling and dBFS math here.
sys.path.insert(0, str(_REPO_ROOT / "decode"))
from radiod_occupancy_producer import (  # noqa: E402
    DEVICE_PROFILES,
    DEFAULT_WINDOW_SEC,
    parse_channels,
    measure_channel_dbfs,
)

DEFAULT_THRESHOLD_DBFS = -30.0  # same starting point every uncalibrated
                                # DEVICE_PROFILES entry uses; see that
                                # module for the rx888 field-calibrated
                                # value this falls back from.


def _profile_by_config_name() -> dict[str, dict]:
    """Map a radiod conf's filename -> its DEVICE_PROFILES entry, if any.

    Keyed by filename (not the DEVICE_PROFILES dict key) so this still
    works even though DEVICE_PROFILES' own key names ("rx888", "hackrf",
    "rtlsdr") don't equal the config stem for every device.
    """
    by_name: dict[str, dict] = {}
    for profile in DEVICE_PROFILES.values():
        by_name[Path(profile["config"]).name] = profile
    return by_name


def discover_configs(conf_dir: Path) -> list[tuple[str, Path]]:
    """Return [(instance_stem, conf_path), ...] for every radiod@*.conf."""
    found = []
    for conf in sorted(conf_dir.glob("radiod@*.conf")):
        stem = conf.stem.split("@", 1)[1]  # "radiod@hackrf-2m" -> "hackrf-2m"
        found.append((stem, conf))
    return found


def systemd_instance_active(unit_name: str) -> bool | None:
    """True/False if systemctl answered, None if it couldn't be asked
    (no systemd on this box, binary missing, etc.) — a genuine unknown,
    not the same as "confirmed inactive"."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", f"radiod@{unit_name}"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout.strip() == "active"


def format_dbfs(dbfs: float | None) -> str:
    if dbfs is None:
        return "  n/a"
    if dbfs == -math.inf:
        return " -inf"
    return f"{dbfs:6.1f}"


def test_instance(stem: str, conf_path: Path, unit_name: str,
                   window_sec: float, threshold_dbfs: float | None,
                   profile_by_config: dict[str, dict],
                   force: bool, verbose: bool) -> dict:
    """Run the channel-activity test for one SDR/config. Returns a summary
    dict for the final table; never raises for expected/operational
    conditions (missing config, service down, silent channel)."""
    summary = {
        "stem": stem, "unit": unit_name, "service": "unknown",
        "channels": 0, "active": 0, "quiet": 0, "no_data": 0,
        "skipped": False, "note": "",
    }

    print(f"== {stem}  (radiod@{unit_name}, config: {conf_path.name}) ==")

    if not conf_path.exists():
        print(f"  FAIL: config not found: {conf_path}")
        summary["service"] = "n/a"
        summary["note"] = "config missing"
        print()
        return summary

    active = systemd_instance_active(unit_name)
    if active is True:
        summary["service"] = "active"
        print(f"  service radiod@{unit_name}: active")
    elif active is False:
        summary["service"] = "inactive"
        print(f"  service radiod@{unit_name}: inactive")
        if not force:
            print("  SKIPPED (pass --force to measure anyway, or fix the "
                  "instance name with --instance "
                  f"{stem}=<real-systemd-name> if it's just misnamed)")
            summary["skipped"] = True
            print()
            return summary
        print("  --force set: attempting measurement despite inactive status")
    else:
        summary["service"] = "unknown"
        print(f"  service radiod@{unit_name}: could not determine "
              "(no systemctl, or it errored) — attempting measurement anyway")

    profile = profile_by_config.get(conf_path.name)
    if threshold_dbfs is not None:
        effective_threshold = threshold_dbfs
    elif profile is not None:
        effective_threshold = profile["threshold_dbfs"]
        if not profile["calibrated"]:
            print(f"  NOTE: using {stem}'s DEVICE_PROFILES threshold "
                  f"({effective_threshold} dBFS), which is itself marked "
                  "NOT field-calibrated — see radiod_occupancy_producer.py.")
    else:
        effective_threshold = DEFAULT_THRESHOLD_DBFS
        print(f"  NOTE: no DEVICE_PROFILES entry matches {conf_path.name} — "
              f"using an uncalibrated default threshold "
              f"({effective_threshold} dBFS). Pass --threshold-dbfs to set "
              "one deliberately.")

    channels = parse_channels(conf_path)
    if not channels:
        print("  No audio channels parsed (IQ-only config, or nothing "
              "matched freq=/data=).")
        summary["note"] = "no audio channels"
        print()
        return summary

    for ch in channels:
        dbfs = measure_channel_dbfs(ch["stream"], window_sec, verbose)
        summary["channels"] += 1
        if dbfs is None:
            state = "NO DATA"
            summary["no_data"] += 1
        elif dbfs >= effective_threshold:
            state = "ACTIVE"
            summary["active"] += 1
        else:
            state = "quiet"
            summary["quiet"] += 1
        print(f"    {ch['name']:20} {ch['freq_hz']/1e6:9.4f} MHz "
              f"{ch['mode']:4} {format_dbfs(dbfs)} dBFS  {state}")

    print()
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read-only ka9q-radio (radiod) channel-activity test, "
                     "per SDR.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--sdr", action="append", default=None,
                     help="limit to this config stem (radiod@STEM.conf); "
                          "repeatable. Default: all found in --conf-dir")
    ap.add_argument("--instance", action="append", default=[],
                     metavar="CONFIG_STEM=SYSTEMD_NAME",
                     help="override the systemd instance name assumed for "
                          "a config stem, e.g. rtlsdr-adhoc=rtlsdr-v4. "
                          "Repeatable.")
    ap.add_argument("--window", type=float, default=DEFAULT_WINDOW_SEC,
                     help=f"audio capture window per channel in seconds "
                          f"(default {DEFAULT_WINDOW_SEC})")
    ap.add_argument("--threshold-dbfs", type=float, default=None,
                     help="dBFS threshold applied to every channel, "
                          "overriding any DEVICE_PROFILES value")
    ap.add_argument("--force", action="store_true",
                     help="measure channels even when systemctl reports "
                          "the instance inactive (or unknown)")
    ap.add_argument("--conf-dir", type=Path, default=_KA9Q_CONF_DIR,
                     help=f"directory of radiod@*.conf files "
                          f"(default {_KA9Q_CONF_DIR})")
    ap.add_argument("--verbose", "-v", action="store_true",
                     help="show per-channel capture diagnostics (join "
                          "failures, silent streams, etc.)")
    args = ap.parse_args()

    instance_overrides = {}
    for item in args.instance:
        if "=" not in item:
            print(f"ERROR: --instance expects CONFIG_STEM=SYSTEMD_NAME, "
                  f"got: {item!r}", file=sys.stderr)
            return 1
        stem, unit = item.split("=", 1)
        instance_overrides[stem] = unit

    if not args.conf_dir.exists():
        print(f"ERROR: config directory not found: {args.conf_dir}",
              file=sys.stderr)
        return 1

    discovered = discover_configs(args.conf_dir)
    if not discovered:
        print(f"ERROR: no radiod@*.conf files found in {args.conf_dir}",
              file=sys.stderr)
        return 1

    if args.sdr:
        wanted = set(args.sdr)
        available = {stem for stem, _ in discovered}
        missing = wanted - available
        if missing:
            print(f"ERROR: --sdr name(s) not found: {', '.join(sorted(missing))}",
                  file=sys.stderr)
            print(f"       available: {', '.join(sorted(available))}",
                  file=sys.stderr)
            return 1
        discovered = [(stem, path) for stem, path in discovered if stem in wanted]

    profile_by_config = _profile_by_config_name()

    print("== ka9q-radio channel-activity test ==")
    print(f"   conf dir: {args.conf_dir}")
    print(f"   window:   {args.window}s per channel")
    print(f"   (read-only: no occupancy DB writes)")
    print()

    summaries = []
    for stem, conf_path in discovered:
        unit_name = instance_overrides.get(stem, stem)
        summaries.append(
            test_instance(
                stem, conf_path, unit_name, args.window,
                args.threshold_dbfs, profile_by_config, args.force,
                args.verbose,
            )
        )

    print("== Summary ==")
    header = f"{'SDR':20} {'SERVICE':10} {'CHANNELS':9} {'ACTIVE':7} {'QUIET':6} {'NO-DATA':8}"
    print(header)
    for s in summaries:
        if s["skipped"] or s["note"]:
            note = s["note"] or "skipped (service inactive)"
            print(f"{s['stem']:20} {s['service']:10} {note}")
        else:
            print(f"{s['stem']:20} {s['service']:10} {s['channels']:<9} "
                  f"{s['active']:<7} {s['quiet']:<6} {s['no_data']:<8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
