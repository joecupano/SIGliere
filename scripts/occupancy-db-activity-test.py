#!/usr/bin/env python3
"""
scripts/occupancy-db-activity-test.py — CLI test: is db/occupancy.db
actually receiving new writes, and specifically which ka9q-radio (radiod)
services are the ones populating it?

Every ingestion source writes through OccupancyDB.record_sighting()
(db/occupancy_db.py) into one shared `sightings` table, tagged with
source_type/source_device (see db/occupancy_schema.sql). This script reads
that table read-only and answers two questions:

  1. Is the DB updating at all right now? (overall last-write age vs.
     --stale-after-sec)
  2. Per source_type/source_device: how many sightings, how recent, and —
     specifically for ka9q-radio (radiod*) sources — cross-referenced
     against the SDRs actually configured under ingest/ka9q-radio/*.conf,
     so a configured SDR that has NEVER written a sighting (not just one
     that's currently quiet) is called out distinctly.

source_type values seen in this repo (see decode/radiod_occupancy_producer.py
and decode/vhf_uhf_key_freq_producer.py):
  radiod, radiod-hackrf, radiod-rtlsdr   -> ka9q-radio (radiod) services
  hackrf, rtlsdr                          -> legacy single-tuner scan producers
  gnuradio_feature_extraction             -> GNU Radio / OpenWebRX+ flowgraphs
Only the radiod*-prefixed ones are "ka9q-radio services" for this script's
purposes; the others are reported for context, not confused with them.

This script NEVER writes to the DB — it opens it sqlite3 URI mode=ro, so
running it can't create an empty db/occupancy.db (OccupancyDB's own
constructor would) or otherwise disturb what a producer is doing.

USAGE:
  scripts/occupancy-db-activity-test.py [--db PATH]
      [--recent-minutes N] [--stale-after-sec N]
      [--require-radiod-activity] [--verbose]

EXIT STATUS:
  0  ran cleanly (a currently-quiet source is not itself a failure —
     see --require-radiod-activity if you want that enforced)
  1  a structural problem: DB file missing/unreadable, no `sightings`
     table, or (with --require-radiod-activity) no radiod* source has
     written a sighting inside --recent-minutes
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = _REPO_ROOT / "db" / "occupancy.db"
DEFAULT_CONF_DIR = _REPO_ROOT / "ingest" / "ka9q-radio"

# Reuse the producer's own device->source_type/source_device/config mapping
# rather than re-guessing it here.
sys.path.insert(0, str(_REPO_ROOT / "decode"))
from radiod_occupancy_producer import DEVICE_PROFILES  # noqa: E402

# Every source_type radiod_occupancy_producer.py writes starts with this
# prefix ('radiod', 'radiod-hackrf', 'radiod-rtlsdr'). Legacy scan-based
# producers ('hackrf', 'rtlsdr') and GNU Radio flowgraphs
# ('gnuradio_feature_extraction') deliberately do NOT match — see module
# docstring.
KA9Q_SOURCE_PREFIX = "radiod"

# Known systemd --user producer services that write each radiod*
# source_type (see systemd/radiod-occupancy*.service). None means "no
# installer/unit exists yet for this profile" — see DEVICE_PROFILES'
# calibrated=False notes in radiod_occupancy_producer.py — not "confirmed
# absent."
KA9Q_PRODUCER_UNITS = {
    "radiod": "radiod-occupancy.service",
    "radiod-hackrf": "radiod-occupancy-hackrf.service",
    "radiod-rtlsdr": None,
}


def fmt_ts(epoch_sec) -> str:
    if not epoch_sec:
        return "never"
    return datetime.fromtimestamp(epoch_sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def fmt_age(seconds) -> str:
    if seconds is None:
        return "n/a"
    seconds = max(seconds, 0)
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def open_db_readonly(db_path: Path) -> sqlite3.Connection:
    """Open strictly read-only via a file: URI — this must never be the
    call site that creates db/occupancy.db (OccupancyDB's constructor
    would, applying the schema on an empty file); a missing DB should be
    reported as an error, not silently materialized."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def user_unit_active(unit: str) -> bool | None:
    """True/False if systemctl --user answered, None if it couldn't be
    asked (no systemd, no session bus, binary missing, etc.)."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout.strip() == "active"


def discover_ka9q_configs(conf_dir: Path) -> list[str]:
    """Config stems for every radiod@*.conf in ingest/ka9q-radio/ — the
    ka9q-radio SDRs this repo has a config for, independent of whether
    they've ever written a sighting."""
    return sorted(p.stem.split("@", 1)[1] for p in conf_dir.glob("radiod@*.conf"))


def profile_by_config_name() -> dict[str, tuple[str, dict]]:
    """Map a radiod conf's filename -> (DEVICE_PROFILES key, profile)."""
    return {
        Path(profile["config"]).name: (key, profile)
        for key, profile in DEVICE_PROFILES.items()
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read-only test: is db/occupancy.db updating, and "
                     "which ka9q-radio (radiod) services are populating it?",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB,
                     help=f"occupancy DB path (default {DEFAULT_DB})")
    ap.add_argument("--conf-dir", type=Path, default=DEFAULT_CONF_DIR,
                     help=f"ka9q-radio config dir, for cross-reference "
                          f"(default {DEFAULT_CONF_DIR})")
    ap.add_argument("--recent-minutes", type=float, default=15.0,
                     help="a source counts as 'currently active' if it has "
                          "a sighting inside this window (default 15)")
    ap.add_argument("--stale-after-sec", type=float, default=300.0,
                     help="overall DB is considered STALE if its newest "
                          "sighting is older than this (default 300 = 5m)")
    ap.add_argument("--require-radiod-activity", action="store_true",
                     help="exit 1 if no ka9q-radio (radiod*) source has a "
                          "sighting inside --recent-minutes")
    ap.add_argument("--verbose", "-v", action="store_true",
                     help="also list the 5 most recent sightings per source")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"ERROR: occupancy DB not found: {args.db}", file=sys.stderr)
        print("       No producer has written to it yet, or the path is "
              "wrong. See docs/occupancy-guide.md.", file=sys.stderr)
        return 1

    try:
        conn = open_db_readonly(args.db)
        tables = {r[0] for r in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error as exc:
        print(f"ERROR: could not open {args.db}: {exc}", file=sys.stderr)
        return 1

    if "sightings" not in tables:
        print(f"ERROR: {args.db} has no 'sightings' table — wrong file, "
              "or schema not applied.", file=sys.stderr)
        return 1

    now = time.time()
    recent_cutoff = now - args.recent_minutes * 60

    total_sightings = conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
    total_signals = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] \
        if "signals" in tables else None
    overall_min, overall_max = conn.execute(
        "SELECT MIN(first_seen_sec), MAX(last_seen_sec) FROM sightings"
    ).fetchone()

    print("== occupancy DB activity test ==")
    print(f"   db:              {args.db}")
    print(f"   total sightings: {total_sightings}"
          + (f"  (total signals: {total_signals})" if total_signals is not None else ""))
    if overall_min is not None:
        print(f"   first sighting:  {fmt_ts(overall_min)}")
        age = now - overall_max
        status = "ACTIVE" if age <= args.stale_after_sec else "STALE"
        print(f"   last sighting:   {fmt_ts(overall_max)}  "
              f"({fmt_age(age)} ago)  -> {status} "
              f"(threshold {args.stale_after_sec:.0f}s)")
    else:
        print("   no sightings recorded yet.")
    print()

    rows = conn.execute(
        """
        SELECT source_type, source_device,
               COUNT(*) AS n,
               MIN(first_seen_sec) AS first_sec,
               MAX(last_seen_sec) AS last_sec,
               SUM(CASE WHEN last_seen_sec >= ? THEN 1 ELSE 0 END) AS recent_n
        FROM sightings
        GROUP BY source_type, source_device
        ORDER BY source_type, source_device
        """,
        (recent_cutoff,),
    ).fetchall()

    print(f"== All sources (recent = last {args.recent_minutes:g}m) ==")
    header = (f"{'SOURCE_TYPE':16} {'SOURCE_DEVICE':14} {'KA9Q?':6} "
              f"{'TOTAL':8} {'RECENT':7} {'LAST SEEN':21} {'STATUS':8}")
    print(header)
    row_by_key = {}
    for r in rows:
        row_by_key[(r["source_type"], r["source_device"])] = r
        is_ka9q = "yes" if r["source_type"].startswith(KA9Q_SOURCE_PREFIX) else "no"
        age = now - r["last_sec"]
        status = "ACTIVE" if r["recent_n"] > 0 else "quiet"
        print(f"{r['source_type']:16} {r['source_device']:14} {is_ka9q:6} "
              f"{r['n']:<8} {r['recent_n']:<7} "
              f"{fmt_ts(r['last_sec']):21} {status:8}")
        if args.verbose:
            recent_rows = conn.execute(
                """
                SELECT id, frequency_hz, mode, last_seen_sec, metadata_json
                FROM sightings
                WHERE source_type = ? AND source_device = ?
                ORDER BY id DESC LIMIT 5
                """,
                (r["source_type"], r["source_device"]),
            ).fetchall()
            for rr in recent_rows:
                meta = (rr["metadata_json"] or "")[:60]
                print(f"    #{rr['id']:<8} {rr['frequency_hz']/1e6:9.4f} MHz "
                      f"{(rr['mode'] or ''):5} {fmt_ts(rr['last_seen_sec']):21} {meta}")
    if not rows:
        print("  (no sightings of any kind yet)")
    print()

    # ------------------------------------------------------------------
    # ka9q-radio (radiod) cross-reference: for every SDR this repo has a
    # radiod@*.conf for, is it writing sightings, and is its --user
    # producer service even running?
    # ------------------------------------------------------------------
    print("== ka9q-radio (radiod) services specifically ==")
    if not args.conf_dir.exists():
        print(f"  WARNING: conf dir not found: {args.conf_dir} — skipping "
              "configured-SDR cross-reference.")
        configured_stems = []
    else:
        configured_stems = discover_ka9q_configs(args.conf_dir)

    profiles = profile_by_config_name()
    radiod_recent_total = 0

    for stem in configured_stems:
        conf_name = f"radiod@{stem}.conf"
        match = profiles.get(conf_name)
        if match is None:
            print(f"  {stem:16} config present, but no DEVICE_PROFILES "
                  f"entry matches {conf_name} — can't cross-reference "
                  f"against the DB automatically (see "
                  f"decode/radiod_occupancy_producer.py DEVICE_PROFILES).")
            continue

        _, profile = match
        source_type = profile["source_type"]
        source_device = profile["source_device"]
        db_row = row_by_key.get((source_type, source_device))

        unit = KA9Q_PRODUCER_UNITS.get(source_type)
        if unit is None:
            unit_state = "no producer service installer exists yet"
        else:
            active = user_unit_active(unit)
            if active is True:
                unit_state = f"{unit}: active"
            elif active is False:
                unit_state = f"{unit}: inactive"
            else:
                unit_state = f"{unit}: unknown (no --user systemd?)"

        if db_row is None:
            print(f"  {stem:16} source_type={source_type} source_device={source_device}")
            print(f"                   DB: NEVER seen a sighting for this source")
            print(f"                   producer service: {unit_state}")
        else:
            age = now - db_row["last_sec"]
            status = "ACTIVE" if db_row["recent_n"] > 0 else "quiet"
            radiod_recent_total += db_row["recent_n"]
            print(f"  {stem:16} source_type={source_type} source_device={source_device}")
            print(f"                   DB: {db_row['n']} sightings, last "
                  f"{fmt_ts(db_row['last_sec'])} ({fmt_age(age)} ago) -> {status}")
            print(f"                   producer service: {unit_state}")
            if status == "quiet" and unit_state.endswith(": active"):
                print("                   NOTE: producer service is active but "
                      "the DB hasn't seen a recent sighting from it — check "
                      "journalctl --user -u " + unit + " (radiod itself may be "
                      "silent/down, or every channel is genuinely quiet).")
        print()

    # Also total up recent activity from any OTHER radiod*-prefixed
    # source_type not tied to a discovered config (e.g. a stale/renamed
    # config, or DEVICE_PROFILES entries this cross-reference didn't
    # already count).
    accounted = {(p["source_type"], p["source_device"])
                 for _, p in profiles.values()}
    for (source_type, source_device), r in row_by_key.items():
        if source_type.startswith(KA9Q_SOURCE_PREFIX) and \
                (source_type, source_device) not in accounted:
            radiod_recent_total += r["recent_n"]
            print(f"  (uncross-referenced) source_type={source_type} "
                  f"source_device={source_device}: {r['n']} sightings, "
                  f"{r['recent_n']} recent")

    print(f"== Verdict: {radiod_recent_total} ka9q-radio (radiod*) sighting(s) "
          f"in the last {args.recent_minutes:g}m ==")

    if args.require_radiod_activity and radiod_recent_total == 0:
        print("FAIL: --require-radiod-activity set and no radiod* source "
              "wrote a sighting in the window above.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
