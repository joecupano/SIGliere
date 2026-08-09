#!/usr/bin/env python3
"""
scripts/occupancy-db-manage.py — CLI to manage db/occupancy.db: wipe it
back to empty, or delete a subset of sightings by date range / SDR /
frequency.

This is the WRITE counterpart to scripts/occupancy-db-activity-test.py
(which is read-only). Everything here that actually mutates the DB is
gated behind --yes:

  - Without --yes: DRY RUN. Shows exactly what would be deleted (row
    counts, a sample of matching rows) and exits 0 without touching
    the file.
  - With --yes: takes a checkpointed backup copy of the DB first (unless
    --no-backup), then performs the change inside one transaction.

`sightings` (per-detection events) and `signals` (the aggregate rollup
keyed by frequency-bin+mode, see db/occupancy_db.py:make_signal_key) are
kept consistent: deleting sightings recomputes or removes the `signals`
rows those sightings fed, rather than leaving stale aggregates behind.

SUBCOMMANDS:
  sources   list distinct source_type/source_device pairs in the DB —
            use this to find the right --sdr / --source-type values
  delete    delete sightings matching --after/--before, --sdr,
            --source-type, and/or --freq-min/--freq-max (AND'd together;
            at least one filter is required, or pass --all explicitly)
  reset     delete ALL sightings and signals, keeping the schema

USAGE:
  scripts/occupancy-db-manage.py sources
  scripts/occupancy-db-manage.py delete --sdr rx888-hf --before 2026-08-01
  scripts/occupancy-db-manage.py delete --freq-min 144000000 --freq-max 148000000 --yes
  scripts/occupancy-db-manage.py reset --yes

EXIT STATUS:
  0  ran cleanly (a dry run with zero matches is not a failure)
  1  a structural problem (DB missing, bad arguments, no filters given
     to `delete` without --all, etc.)
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = _REPO_ROOT / "db" / "occupancy.db"
DEFAULT_BACKUP_DIR = _REPO_ROOT / "db" / "backups"


def parse_time(value: str) -> int:
    """Accept either a raw epoch-seconds integer or an ISO-8601 date/
    datetime (e.g. '2026-08-01' or '2026-08-01T12:00:00Z'). Naive
    datetimes are treated as UTC, matching how occupancy_db.py stamps
    everything (datetime.now(timezone.utc))."""
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    v = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"not an epoch integer or ISO-8601 date/time: {value!r} ({exc})"
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def fmt_ts(epoch_sec) -> str:
    if not epoch_sec:
        return "never"
    return datetime.fromtimestamp(epoch_sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def connect_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def require_db(db_path: Path) -> None:
    if not db_path.exists():
        print(f"ERROR: occupancy DB not found: {db_path}", file=sys.stderr)
        sys.exit(1)


def backup_db(conn: sqlite3.Connection, db_path: Path, backup_dir: Path) -> Path:
    """Flush WAL into the main file, then copy it — a checkpointed single
    file is enough to restore from, no need to also copy -wal/-shm."""
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{db_path.stem}.{stamp}.bak{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


# ---------------------------------------------------------------------
# Shared WHERE-clause building for `delete` (and its dry-run preview)
# ---------------------------------------------------------------------
def build_where(args) -> tuple[str, list]:
    clauses = []
    params: list = []

    if args.after is not None:
        clauses.append("last_seen_sec >= ?")
        params.append(args.after)
    if args.before is not None:
        clauses.append("last_seen_sec < ?")
        params.append(args.before)

    if args.sdr:
        placeholders = ",".join("?" for _ in args.sdr)
        clauses.append(f"source_device IN ({placeholders})")
        params.extend(args.sdr)

    if args.source_type:
        placeholders = ",".join("?" for _ in args.source_type)
        clauses.append(f"source_type IN ({placeholders})")
        params.extend(args.source_type)

    if args.freq is not None:
        lo = args.freq - args.freq_tolerance_hz
        hi = args.freq + args.freq_tolerance_hz
        clauses.append("frequency_hz BETWEEN ? AND ?")
        params.extend([lo, hi])
    else:
        if args.freq_min is not None:
            clauses.append("frequency_hz >= ?")
            params.append(args.freq_min)
        if args.freq_max is not None:
            clauses.append("frequency_hz <= ?")
            params.append(args.freq_max)

    return " AND ".join(clauses), params


def recompute_signals(conn: sqlite3.Connection, signal_keys: list[str]) -> None:
    """After deleting sightings, bring `signals` back in line: drop rows
    whose last sighting is gone, recompute the rest from what remains."""
    for key in signal_keys:
        remaining = conn.execute(
            "SELECT COUNT(*) AS n, "
            "MIN(first_seen_sec) AS min_sec, MAX(last_seen_sec) AS max_sec "
            "FROM sightings WHERE signal_key = ?",
            (key,),
        ).fetchone()
        if remaining["n"] == 0:
            conn.execute("DELETE FROM signals WHERE signal_key = ?", (key,))
            continue
        first_row = conn.execute(
            "SELECT first_seen_sec, first_seen_ms FROM sightings "
            "WHERE signal_key = ? ORDER BY first_seen_sec ASC, first_seen_ms ASC LIMIT 1",
            (key,),
        ).fetchone()
        last_row = conn.execute(
            "SELECT last_seen_sec, last_seen_ms FROM sightings "
            "WHERE signal_key = ? ORDER BY last_seen_sec DESC, last_seen_ms DESC LIMIT 1",
            (key,),
        ).fetchone()
        conn.execute(
            "UPDATE signals SET first_seen_sec=?, first_seen_ms=?, "
            "last_seen_sec=?, last_seen_ms=?, total_sightings=? WHERE signal_key=?",
            (first_row["first_seen_sec"], first_row["first_seen_ms"],
             last_row["last_seen_sec"], last_row["last_seen_ms"],
             remaining["n"], key),
        )


# ---------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------
def cmd_sources(args) -> int:
    require_db(args.db)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT source_type, source_device, COUNT(*) AS n, "
        "MIN(first_seen_sec) AS first_sec, MAX(last_seen_sec) AS last_sec "
        "FROM sightings GROUP BY source_type, source_device "
        "ORDER BY source_type, source_device"
    ).fetchall()
    if not rows:
        print("(no sightings in the DB)")
        return 0
    print(f"{'SOURCE_TYPE':16} {'SOURCE_DEVICE':14} {'COUNT':8} {'FIRST SEEN':21} {'LAST SEEN':21}")
    for r in rows:
        print(f"{r['source_type']:16} {r['source_device']:14} {r['n']:<8} "
              f"{fmt_ts(r['first_sec']):21} {fmt_ts(r['last_sec']):21}")
    return 0


def cmd_delete(args) -> int:
    require_db(args.db)

    where, params = build_where(args)
    if not where and not args.all:
        print("ERROR: `delete` needs at least one filter (--after/--before, "
              "--sdr, --source-type, --freq/--freq-min/--freq-max), or pass "
              "--all to deliberately delete every row (use `reset` instead "
              "if you actually want to wipe the DB).", file=sys.stderr)
        return 1
    where_sql = f"WHERE {where}" if where else ""

    conn = connect_rw(args.db)
    try:
        match_count = conn.execute(
            f"SELECT COUNT(*) FROM sightings {where_sql}", params
        ).fetchone()[0]

        print(f"Filter: {where or '(none — matches ALL rows, --all set)'}")
        print(f"Matching sightings: {match_count}")

        if match_count == 0:
            print("Nothing to delete.")
            return 0

        sample = conn.execute(
            f"SELECT id, source_type, source_device, frequency_hz, mode, "
            f"last_seen_sec FROM sightings {where_sql} "
            f"ORDER BY id DESC LIMIT {args.sample_limit}",
            params,
        ).fetchall()
        print(f"Sample (up to {args.sample_limit}):")
        for r in sample:
            print(f"  #{r['id']:<8} {r['source_type']:14} {r['source_device']:12} "
                  f"{r['frequency_hz']/1e6:9.4f} MHz {(r['mode'] or ''):5} "
                  f"last_seen={fmt_ts(r['last_seen_sec'])}")

        if not args.yes:
            print()
            print("DRY RUN — nothing deleted. Re-run with --yes to actually delete.")
            return 0

        affected_keys = [
            row[0] for row in conn.execute(
                f"SELECT DISTINCT signal_key FROM sightings {where_sql}", params
            ).fetchall()
        ]

        backup_path = None
        if not args.no_backup:
            backup_path = backup_db(conn, args.db, args.backup_dir)
            print(f"Backup written: {backup_path}")

        with conn:
            conn.execute(f"DELETE FROM sightings {where_sql}", params)
            recompute_signals(conn, affected_keys)

        if args.vacuum:
            conn.execute("VACUUM")

        print(f"Deleted {match_count} sighting(s); recomputed/pruned "
              f"{len(affected_keys)} affected signal(s).")
        if backup_path:
            print(f"Restore with: cp {backup_path} {args.db}")
        return 0
    finally:
        conn.close()


def cmd_reset(args) -> int:
    require_db(args.db)
    conn = connect_rw(args.db)
    try:
        n_sightings = conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
        n_signals = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        print(f"This will permanently delete ALL data from {args.db}:")
        print(f"  sightings: {n_sightings}")
        print(f"  signals:   {n_signals}")
        print("(schema_version and the schema itself are left in place.)")

        if not args.yes:
            print()
            print("DRY RUN — nothing deleted. Re-run with --yes to actually reset.")
            return 0

        backup_path = None
        if not args.no_backup:
            backup_path = backup_db(conn, args.db, args.backup_dir)
            print(f"Backup written: {backup_path}")

        with conn:
            conn.execute("DELETE FROM sightings")
            conn.execute("DELETE FROM signals")
            conn.execute("DELETE FROM sqlite_sequence WHERE name='sightings'")
        conn.execute("VACUUM")

        print(f"Reset complete: {args.db} now has 0 sightings, 0 signals.")
        if backup_path:
            print(f"Restore with: cp {backup_path} {args.db}")
        return 0
    finally:
        conn.close()


def main() -> int:
    # A shared parent parser so --db/--yes/--no-backup/--backup-dir work
    # whether given before or after the subcommand (argparse subparsers
    # don't inherit a parent's own options otherwise — `delete ... --yes`
    # would fail if --yes were only defined on the top-level parser).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=DEFAULT_DB,
                         help=f"occupancy DB path (default {DEFAULT_DB})")
    common.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR,
                         help=f"where --yes writes its pre-change backup copy "
                              f"(default {DEFAULT_BACKUP_DIR})")
    common.add_argument("--no-backup", action="store_true",
                         help="skip the automatic backup copy before a real "
                              "change (NOT recommended — this is what makes "
                              "--yes reversible)")
    common.add_argument("--yes", "-y", action="store_true",
                         help="actually perform the change; without this, "
                              "every subcommand is a dry run")

    # NOTE: --db/--yes/--no-backup/--backup-dir deliberately live ONLY on
    # the subparsers (via parents=[common] below), not on `ap` itself.
    # argparse's subparsers action re-parses with a fresh namespace and
    # then overwrites the top-level namespace wholesale, so an option
    # defined on both levels silently resets to the subparser's default
    # when given before the subcommand — i.e. `--yes delete ...` would
    # look accepted but quietly behave like a dry run. Keeping these
    # options subparser-only means they must go AFTER the subcommand
    # (`delete ... --yes`), which is unambiguous and matches every usage
    # example in this file's docstring.
    ap = argparse.ArgumentParser(
        description="Manage db/occupancy.db: reset to empty, or delete "
                     "sightings by date range / SDR / frequency.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    sub = ap.add_subparsers(dest="command", required=True)

    sp_sources = sub.add_parser("sources", parents=[common],
                                 help="list distinct source_type/"
                                 "source_device pairs (for picking --sdr values)")
    sp_sources.set_defaults(func=cmd_sources)

    sp_delete = sub.add_parser("delete", parents=[common],
                                help="delete sightings matching filters")
    sp_delete.add_argument("--after", "--since", dest="after", type=parse_time,
                            help="delete sightings last seen at/after this "
                                 "time (epoch seconds or ISO-8601 date)")
    sp_delete.add_argument("--before", "--until", dest="before", type=parse_time,
                            help="delete sightings last seen strictly before "
                                 "this time (epoch seconds or ISO-8601 date)")
    sp_delete.add_argument("--sdr", action="append", default=[],
                            metavar="SOURCE_DEVICE",
                            help="filter by source_device (e.g. rx888-hf, "
                                 "hackrf-one, rtl-sdr — see the `sources` "
                                 "subcommand for exact values). Repeatable "
                                 "(OR'd together).")
    sp_delete.add_argument("--source-type", action="append", default=[],
                            metavar="SOURCE_TYPE",
                            help="filter by source_type (e.g. radiod, "
                                 "radiod-hackrf, radiod-rtlsdr, hackrf, "
                                 "rtlsdr, gnuradio_feature_extraction). "
                                 "Repeatable (OR'd together).")
    sp_delete.add_argument("--freq", type=float, default=None,
                            help="delete sightings at this frequency in Hz "
                                 "(± --freq-tolerance-hz). Mutually exclusive "
                                 "with --freq-min/--freq-max.")
    sp_delete.add_argument("--freq-tolerance-hz", type=float, default=0.0,
                            help="tolerance band around --freq (default 0 "
                                 "= exact match)")
    sp_delete.add_argument("--freq-min", type=float, default=None,
                            help="delete sightings with frequency_hz >= this")
    sp_delete.add_argument("--freq-max", type=float, default=None,
                            help="delete sightings with frequency_hz <= this")
    sp_delete.add_argument("--all", action="store_true",
                            help="allow deleting with no filters at all "
                                 "(normally refused as a likely mistake)")
    sp_delete.add_argument("--vacuum", action="store_true",
                            help="VACUUM after deleting to reclaim disk "
                                 "space (default off — can be slow on a "
                                 "large DB)")
    sp_delete.add_argument("--sample-limit", type=int, default=10,
                            help="how many matching rows to preview "
                                 "(default 10)")
    sp_delete.set_defaults(func=cmd_delete)

    sp_reset = sub.add_parser("reset", parents=[common],
                               help="delete ALL sightings and signals")
    sp_reset.set_defaults(func=cmd_reset)

    args = ap.parse_args()

    if args.command == "delete":
        if args.freq is not None and (args.freq_min is not None or args.freq_max is not None):
            print("ERROR: --freq is mutually exclusive with --freq-min/--freq-max",
                  file=sys.stderr)
            return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
