"""
title: SIGINT Kismet Bridge
author: SIGliere
description: Query the local Kismet device mirror — which WiFi, Bluetooth,
    and ADS-B devices a standalone Kismet server has seen, and when. Native
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
# (never touching Kismet's own REST API or capture files directly — see KISMET-BRIDGE.md). This tool only reads that
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
#   reads; kismet_bridge_producer.py writes on the host in rollback-journal
#   mode, not WAL — WAL can't be opened from a read-only mount between
#   polls.)

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

MAX_RESULTS = 50

# ADS-B aircraft dominate a typical mirror (~88%) and update constantly, so
# they would crowd Wi-Fi/Bluetooth devices out of the MAX_RESULTS window.
# Excluded by default; ask for them explicitly with phy="ADSB" or
# include_adsb=True. Naming a device_type (e.g. "Airplane") also opts in.
ADSB_PHY = "ADSB"


def _iso(sec) -> Optional[str]:
    """Epoch seconds -> UTC ISO-8601; small models can't read raw epochs."""
    if sec is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(sec)))


def _slim(row: dict) -> dict:
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
        "first_seen": _iso(row["first_seen_sec"]),
        "last_seen": _iso(row["last_seen_sec"]),
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


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
        # Read-only URI connection: this tool never writes. The producer's
        # brief write locks are waited out via the connect timeout.
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
        include_adsb: bool = False,
    ) -> str:
        """
        List devices Kismet has seen, from the local device mirror. Despite
        the name (kept for continuity with the reference design this was
        ported from), this covers every PHY Kismet tracks — WiFi, Bluetooth,
        and ADS-B devices — not only WiFi; use the phy parameter
        to narrow to one. ADS-B aircraft (phy "ADSB") are EXCLUDED by default
        because they vastly outnumber everything else; set phy="ADSB" or
        include_adsb=true to query them. Use for "what APs have we seen",
        "find device AA:BB:CC", or "what's shown up in the last hour".

        :param mac: Substring match against device MAC address (e.g. "AA:BB:CC"). Omit to skip.
        :param ssid: Substring match against AP SSID (dot11 access points only). Omit to skip.
        :param device_type: Kismet device type, case-insensitive (e.g. "Wi-Fi AP", "Wi-Fi Client", "Wi-Fi Bridged", "BTLE Device"). "AP" and "client" are accepted as shorthand for the Wi-Fi types. Omit to skip.
        :param phy: Exact match against Kismet's PHY name (e.g. "IEEE802.11", "BTLE", "ADSB"). Omit to skip.
        :param node_id: Restrict to devices observed by this SIGedge node_id. Omit for all nodes.
        :param since_minutes: Only include devices last seen within this many minutes.
        :param include_adsb: Include ADS-B aircraft in an otherwise unfiltered query. Default false. Ignored if phy or device_type is set.
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

        if not rows:
            return "No devices matched those criteria in the kismet bridge database."
        hits = [_slim(dict(r)) for r in rows]
        return json.dumps({"count": len(hits), "devices": hits}, separators=(",", ":"))

    # -- tool 2: quick database-wide summary --------------------------------
    def kismet_summary(self) -> str:
        """
        Summarize the Kismet device mirror as a whole: total devices tracked,
        breakdowns by device type and PHY, the overall time span covered, and
        which SIGedge nodes have contributed data. Use to orient before a more
        specific query_wifi_devices call, or to answer "how many devices have
        we seen". Counts include ADS-B aircraft, reported separately as
        adsb_count so they don't swamp the Wi-Fi/Bluetooth picture.

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
        by_phy_counts = {p: c for p, c in by_phy}
        return json.dumps({
            "device_count": device_count,
            "adsb_count": by_phy_counts.get(ADSB_PHY, 0),
            "non_adsb_count": device_count - by_phy_counts.get(ADSB_PHY, 0),
            "note": "query_wifi_devices excludes ADSB unless phy='ADSB' or include_adsb=true",
            "first_seen": _iso(span[0]),
            "last_seen": _iso(span[1]),
            "by_type": {t or "unknown": c for t, c in by_type},
            "by_phy": {p or "unknown": c for p, c in by_phy},
            "nodes": [n[0] for n in nodes],
        }, indent=2)
