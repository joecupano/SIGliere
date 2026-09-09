"""
title: SIGINT Kismet Bridge
author: SIGliere
description: Query the local Kismet device mirror — which WiFi, Bluetooth,
    and ISM-band devices SIGedge's Kismet capture has seen, and when. Native
    in-process Open WebUI tool, read-only against the host-side
    kismet_bridge.db mirror.
version: 1.0.0
license: AGPL-3.0
"""
#
# THE THIRD AI SOURCE (see sigid_reference_tool.py for the full three-way
# split):
#   occupancy = what frequencies are active (our own capture)
#   kismet    = what devices are present (our own capture) <- this tool
#   sigid     = what signals ARE — the reference catalog to identify them
#
# kismet_bridge.db is written host-side by
# kismet_bridge/kismet_bridge_producer.py, polling the SIGedge gateway's
# curated /kismet/summary/{node} and /kismet/devices/{node} endpoints
# (never touching Kismet's own REST API, SIGedge configuration, or capture
# files directly — see KISMET-BRIDGE.md). This tool only reads that
# SQLite file from inside the Open WebUI container, using plain sqlite3
# rather than importing kismet_bridge_db.py — same as every other native
# tool here, this file is self-contained so it can be pasted straight
# into Workspace -> Tools with no repo checkout inside the container. It
# makes no gateway calls of its own and needs no bearer token.
#
# OPTIONAL DEPLOYMENT:
#   Mount the kismet-bridge data dir in read-only, e.g.:
#     Volume=/data/kismet-bridge:/data/kismet-bridge-ref:ro
#   Then set the KISMET_BRIDGE_DB_PATH valve to
#   /data/kismet-bridge-ref/kismet_bridge.db. (:ro is fine — the tool only
#   reads; kismet_bridge_producer.py writes on the host, in WAL mode, so
#   reads here don't block it.)

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

MAX_RESULTS = 50


class Tools:
    class Valves(BaseModel):
        KISMET_BRIDGE_DB_PATH: str = Field(
            default="/data/kismet-bridge-ref/kismet_bridge.db",
            description="Path to kismet_bridge.db AS SEEN FROM INSIDE the Open "
            "WebUI container. Mount kismet_bridge_producer.py's output dir in "
            "and point this at it.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    def _connect(self) -> sqlite3.Connection:
        path = Path(self.valves.KISMET_BRIDGE_DB_PATH)
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist")
        # Read-only URI connection: this tool never writes, and the
        # producer may hold the file open (WAL mode) concurrently.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    # -- tool 1: device list, filterable ------------------------------------
    def query_wifi_devices(
        self,
        mac: Optional[str] = None,
        ssid: Optional[str] = None,
        device_type: Optional[str] = None,
        phy: Optional[str] = None,
        node_id: Optional[str] = None,
        since_minutes: Optional[int] = None,
    ) -> str:
        """
        List devices Kismet has seen, from the local device mirror. Despite
        the name (kept for continuity with the reference design this was
        ported from), this covers every PHY Kismet tracks — WiFi, Bluetooth,
        and ISM-band RTL-SDR devices — not only WiFi; use the phy parameter
        to narrow to one. Use for "what APs have we seen", "find device
        AA:BB:CC", or "what's shown up in the last hour".

        :param mac: Substring match against device MAC address (e.g. "AA:BB:CC"). Omit to skip.
        :param ssid: Substring match against AP SSID (dot11 access points only). Omit to skip.
        :param device_type: Exact match against Kismet's device type (e.g. "AP", "client", "Wi-Fi Bridged"). Omit to skip.
        :param phy: Exact match against Kismet's PHY name (e.g. "IEEE802.11", "Bluetooth", "RTL433"). Omit to skip.
        :param node_id: Restrict to devices observed by this SIGedge node_id. Omit for all nodes.
        :param since_minutes: Only include devices last seen within this many minutes.
        :return: A JSON string of matching devices, or a not-found message.
        """
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
        if since_minutes is not None:
            clauses.append("last_seen_sec >= ?")
            params.append(int(time.time()) - int(since_minutes) * 60)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM devices {where} ORDER BY last_seen_sec DESC LIMIT ?",
                    (*params, MAX_RESULTS),
                ).fetchall()
        except Exception as e:
            return (f"Error reading kismet bridge database at "
                    f"'{self.valves.KISMET_BRIDGE_DB_PATH}': {e.__class__.__name__}: {e}. "
                    f"Check the valve and that the data dir is mounted in.")

        hits = [dict(r) for r in rows]
        if not hits:
            return "No devices matched those criteria in the kismet bridge database."
        return json.dumps({"count": len(hits), "devices": hits}, indent=2)

    # -- tool 2: quick database-wide summary --------------------------------
    def kismet_summary(self) -> str:
        """
        Summarize the Kismet device mirror as a whole: total devices tracked,
        breakdowns by device type and PHY, the overall time span covered, and
        which SIGedge nodes have contributed data. Use to orient before a more
        specific query_wifi_devices call, or to answer "how many devices have
        we seen".

        :return: A JSON string with the summary counts.
        """
        try:
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
        except Exception as e:
            return (f"Error reading kismet bridge database at "
                    f"'{self.valves.KISMET_BRIDGE_DB_PATH}': {e.__class__.__name__}: {e}.")
        return json.dumps({
            "device_count": device_count,
            "first_seen_sec": span[0],
            "last_seen_sec": span[1],
            "by_type": {t or "unknown": c for t, c in by_type},
            "by_phy": {p or "unknown": c for p, c in by_phy},
            "nodes": [n[0] for n in nodes],
        }, indent=2)
