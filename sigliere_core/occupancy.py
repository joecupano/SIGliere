"""Queries against the local occupancy.db signals/sightings mirror."""

import time
from typing import Optional

MAX_RESULTS = 50


def query_signals(
    conn,
    near_frequency_hz: Optional[float] = None,
    tolerance_hz: Optional[float] = None,
    mode: Optional[str] = None,
    since_minutes: Optional[int] = None,
) -> list:
    """Aggregate signals matching the filters, most recently seen first."""
    clauses = []
    params: list = []
    if near_frequency_hz is not None:
        tol = 5_000.0 if tolerance_hz is None else float(tolerance_hz)
        clauses.append("frequency_hz BETWEEN ? AND ?")
        params.extend([float(near_frequency_hz) - tol, float(near_frequency_hz) + tol])
    if mode is not None:
        clauses.append("mode = ?")
        params.append(mode)
    if since_minutes is not None:
        clauses.append("last_seen_sec >= ?")
        params.append(int(time.time()) - int(since_minutes) * 60)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM signals {where} ORDER BY last_seen_sec DESC LIMIT ?",
        (*params, MAX_RESULTS),
    ).fetchall()
    return [dict(r) for r in rows]


def list_sightings(conn, signal_key: str) -> list:
    """Individual detection events for one signal_key, oldest first."""
    rows = conn.execute(
        "SELECT * FROM sightings WHERE signal_key = ? ORDER BY first_seen_sec",
        (signal_key,),
    ).fetchall()
    return [dict(r) for r in rows]


def summarize_occupancy(conn) -> dict:
    """Whole-database counts, time span, and contributing source devices."""
    signal_count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    sighting_count = conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
    span = conn.execute(
        "SELECT MIN(first_seen_sec), MAX(last_seen_sec) FROM signals"
    ).fetchone()
    devices = conn.execute(
        "SELECT DISTINCT source_device FROM sightings ORDER BY source_device"
    ).fetchall()
    return {
        "signal_count": signal_count,
        "sighting_count": sighting_count,
        "first_seen_sec": span[0],
        "last_seen_sec": span[1],
        "source_devices": [d[0] for d in devices],
    }
