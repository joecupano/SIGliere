"""Queries against the local kismet_bridge.db device mirror."""

import time
from typing import Optional

MAX_RESULTS = 50

# ADS-B aircraft dominate a typical mirror (~88%) and update constantly, so
# they would crowd Wi-Fi/Bluetooth devices out of the MAX_RESULTS window.
# Excluded by default; ask for them explicitly with phy="ADSB" or
# include_adsb=True. Naming a device_type (e.g. "Airplane") also opts in.
ADSB_PHY = "ADSB"


def iso(sec) -> Optional[str]:
    """Epoch seconds -> UTC ISO-8601; small models can't read raw epochs."""
    if sec is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(sec)))


def slim_device(row: dict) -> dict:
    """Trim a devices row to what an LLM needs: drop row ids and the raw
    metadata blob (large, mostly redundant), render times readably, and omit
    empty fields so results stay small enough for the model's context."""
    out = {
        "node_id": row["node_id"],
        "mac": row["mac"],
        "device_type": row["device_type"],
        "phy": row["phy"],
        "ssid": row["ssid"],
        "manufacturer": row["manufacturer"],
        "signal_dbm": row["signal_dbm"],
        "first_seen": iso(row["first_seen_sec"]),
        "last_seen": iso(row["last_seen_sec"]),
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


def query_devices(
    conn,
    mac: Optional[str] = None,
    ssid: Optional[str] = None,
    device_type: Optional[str] = None,
    phy: Optional[str] = None,
    node_id: Optional[str] = None,
    since_minutes: Optional[int] = None,
    include_adsb: bool = False,
) -> list:
    """Devices matching the filters, newest first, slimmed for the model."""
    clauses = []
    params: list = []
    if mac is not None:
        clauses.append("mac LIKE ?")
        params.append(f"%{mac}%")
    if ssid is not None:
        clauses.append("ssid LIKE ?")
        params.append(f"%{ssid}%")
    if device_type is not None:
        # Kismet's real types are "Wi-Fi AP", "Wi-Fi Client", etc.; accept
        # the bare shorthand ("AP", "client") and any capitalization.
        clauses.append(
            "(LOWER(device_type) = LOWER(?) OR LOWER(device_type) = LOWER(?))"
        )
        params.extend([device_type, f"Wi-Fi {device_type}"])
    if phy is not None:
        clauses.append("phy = ?")
        params.append(phy)
    elif not include_adsb and device_type is None:
        clauses.append("(phy IS NULL OR phy != ?)")
        params.append(ADSB_PHY)
    if node_id is not None:
        clauses.append("node_id = ?")
        params.append(node_id)
    if since_minutes is not None:
        clauses.append("last_seen_sec >= ?")
        params.append(int(time.time()) - int(since_minutes) * 60)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM devices {where} ORDER BY last_seen_sec DESC LIMIT ?",
        (*params, MAX_RESULTS),
    ).fetchall()
    return [slim_device(dict(r)) for r in rows]


def summarize_devices(conn) -> dict:
    """Whole-mirror counts, time span, and contributing nodes."""
    device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    span = conn.execute(
        "SELECT MIN(first_seen_sec), MAX(last_seen_sec) FROM devices"
    ).fetchone()
    by_type = conn.execute(
        "SELECT device_type, COUNT(*) FROM devices GROUP BY device_type"
    ).fetchall()
    by_phy = conn.execute("SELECT phy, COUNT(*) FROM devices GROUP BY phy").fetchall()
    nodes = conn.execute(
        "SELECT DISTINCT node_id FROM devices ORDER BY node_id"
    ).fetchall()
    by_phy_counts = {p: c for p, c in by_phy}
    adsb_count = by_phy_counts.get(ADSB_PHY, 0)
    return {
        "device_count": device_count,
        "adsb_count": adsb_count,
        "non_adsb_count": device_count - adsb_count,
        "note": "query_wifi_devices excludes ADSB unless phy='ADSB' or include_adsb=true",
        "first_seen": iso(span[0]),
        "last_seen": iso(span[1]),
        "by_type": {t or "unknown": c for t, c in by_type},
        "by_phy": {p or "unknown": c for p, c in by_phy},
        "nodes": [n[0] for n in nodes],
    }
