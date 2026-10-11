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
# SOURCE vs GENERATED: this file (openwebui-tools/src/) is the thin wrapper —
# docstrings, valves, error text. The query logic lives in
# sigliere_core/kismet.py. scripts/build-owui-tools.py inlines it to produce
# the self-contained openwebui-tools/kismet_tool.py that is pasted into Open
# WebUI. Edit here, then rebuild; never edit the generated file.
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
from typing import Optional

from pydantic import BaseModel, Field

from sigliere_core.kismet import query_devices, summarize_devices
from sigliere_core.sqlite_ro import connect_ro


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
        try:
            with connect_ro(self.valves.KISMET_BRIDGE_DB_PATH) as conn:
                hits = query_devices(
                    conn, mac=mac, ssid=ssid, device_type=device_type, phy=phy,
                    node_id=node_id, since_minutes=since_minutes,
                    include_adsb=include_adsb,
                )
        except Exception as e:
            return (f"Error reading kismet bridge database at "
                    f"'{self.valves.KISMET_BRIDGE_DB_PATH}': {e.__class__.__name__}: {e}. "
                    f"Check the valve and that the data dir is mounted in.")

        if not hits:
            return "No devices matched those criteria in the kismet bridge database."
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
            with connect_ro(self.valves.KISMET_BRIDGE_DB_PATH) as conn:
                summary = summarize_devices(conn)
        except Exception as e:
            return (f"Error reading kismet bridge database at "
                    f"'{self.valves.KISMET_BRIDGE_DB_PATH}': {e.__class__.__name__}: {e}.")
        return json.dumps(summary, indent=2)
