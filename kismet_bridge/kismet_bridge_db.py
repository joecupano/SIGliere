"""
kismet_bridge/kismet_bridge_db.py

Kismet bridge DB access layer — device-centric local mirror, matching
occupancy_db.py's access-layer pattern (schema applied on init, one
write path, read-side query/summary helpers) but a different shape: see
kismet_bridge_schema.sql's header for why this is a device-presence
cache (one row per node_id+mac, upserted) rather than an event log.

Zero dependencies beyond the standard library, same reasoning as
occupancy_db.py: importable from kismet_bridge_producer.py's own venv
and, via plain sqlite3, from kismet_tool.py running inside the Open
WebUI container.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "kismet_bridge_schema.sql"
CURRENT_SCHEMA_VERSION = 1


def _now_sec() -> int:
    return int(datetime.now(timezone.utc).timestamp())


class KismetBridgeDB:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(SCHEMA_PATH.read_text())
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            if row[0] is None:
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at_sec) VALUES (?, ?)",
                    (CURRENT_SCHEMA_VERSION, _now_sec()),
                )

    @contextmanager
    def _connect(self):
        # See occupancy_db.py's identical pattern: timeout= for a blocked
        # writer, WAL so occupancy_tool-style readers never block the
        # producer's writes.
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_device(
        self,
        node_id: str,
        mac: str,
        device_type: str = None,
        phy: str = None,
        ssid: str = None,
        manufacturer: str = None,
        signal_dbm: float = None,
        first_seen_sec: int = None,
        last_seen_sec: int = None,
        metadata_json: str = None,
    ) -> None:
        """Record one device sighting from a producer poll. Inserts a new
        row for a device never seen from this node before, or refreshes
        the mutable fields (type/ssid/manuf/signal/last_seen) and bumps
        total_polls otherwise. first_seen_sec/last_seen_sec should be
        Kismet's own first_time/last_time for the device — the mirror
        trusts Kismet's timestamps rather than ingestion time.
        """
        now = _now_sec()
        first_seen_sec = first_seen_sec if first_seen_sec is not None else now
        last_seen_sec = last_seen_sec if last_seen_sec is not None else now

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT total_polls FROM devices WHERE node_id = ? AND mac = ?",
                (node_id, mac),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO devices
                        (node_id, mac, device_type, phy, ssid, manufacturer,
                         signal_dbm, first_seen_sec, last_seen_sec, total_polls,
                         metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (node_id, mac, device_type, phy, ssid, manufacturer,
                     signal_dbm, first_seen_sec, last_seen_sec, metadata_json),
                )
            else:
                conn.execute(
                    """
                    UPDATE devices
                    SET device_type = ?, phy = ?, ssid = ?, manufacturer = ?,
                        signal_dbm = ?, last_seen_sec = ?, total_polls = total_polls + 1,
                        metadata_json = ?
                    WHERE node_id = ? AND mac = ?
                    """,
                    (device_type, phy, ssid, manufacturer, signal_dbm,
                     last_seen_sec, metadata_json, node_id, mac),
                )

    def get_device(self, node_id: str, mac: str) -> dict | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM devices WHERE node_id = ? AND mac = ?",
                (node_id, mac),
            ).fetchone()
        return dict(row) if row else None

    def query_devices(
        self,
        mac: str = None,
        ssid: str = None,
        device_type: str = None,
        phy: str = None,
        node_id: str = None,
        since_sec: int = None,
        limit: int = 50,
    ) -> list[dict]:
        """Read-side query used by kismet_tool.py's query_wifi_devices —
        despite the name, this filters across all PHYs, not only WiFi."""
        clauses = []
        params: list = []
        if mac is not None:
            clauses.append("mac LIKE ?")
            params.append(f"%{mac}%")
        if ssid is not None:
            clauses.append("ssid LIKE ?")
            params.append(f"%{ssid}%")
        if device_type is not None:
            clauses.append("device_type = ?")
            params.append(device_type)
        if phy is not None:
            clauses.append("phy = ?")
            params.append(phy)
        if node_id is not None:
            clauses.append("node_id = ?")
            params.append(node_id)
        if since_sec is not None:
            clauses.append("last_seen_sec >= ?")
            params.append(since_sec)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM devices {where} ORDER BY last_seen_sec DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict:
        """Coarse counts for kismet_tool.py's kismet_summary()."""
        with self._connect() as conn:
            device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            span = conn.execute(
                "SELECT MIN(first_seen_sec), MAX(last_seen_sec) FROM devices"
            ).fetchone()
            by_type = conn.execute(
                "SELECT device_type, COUNT(*) FROM devices GROUP BY device_type"
            ).fetchall()
            by_phy = conn.execute(
                "SELECT phy, COUNT(*) FROM devices GROUP BY phy"
            ).fetchall()
            nodes = conn.execute(
                "SELECT DISTINCT node_id FROM devices ORDER BY node_id"
            ).fetchall()
        return {
            "device_count": device_count,
            "first_seen_sec": span[0],
            "last_seen_sec": span[1],
            "by_type": {t or "unknown": c for t, c in by_type},
            "by_phy": {p or "unknown": c for p, c in by_phy},
            "nodes": [n[0] for n in nodes],
        }
