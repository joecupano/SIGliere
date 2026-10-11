"""Kismet device-presence mirror tools (kismet_bridge.db)."""

from typing import Annotated, Optional

from pydantic import Field

from sigliere_core.kismet import query_devices, summarize_devices
from sigliere_core.sqlite_ro import connect_ro

from . import READ_ONLY, dumps, read_error


def register(mcp, cfg):
    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def query_wifi_devices(
        mac: Annotated[Optional[str], Field(description='Substring match against device MAC address (e.g. "AA:BB:CC"). Omit to skip.')] = None,
        ssid: Annotated[Optional[str], Field(description="Substring match against AP SSID (dot11 access points only). Omit to skip.")] = None,
        device_type: Annotated[Optional[str], Field(description='Kismet device type, case-insensitive (e.g. "Wi-Fi AP", "Wi-Fi Client", "Wi-Fi Bridged", "BTLE Device"). "AP" and "client" are accepted as shorthand for the Wi-Fi types. Omit to skip.')] = None,
        phy: Annotated[Optional[str], Field(description='Exact match against Kismet\'s PHY name (e.g. "IEEE802.11", "BTLE", "ADSB"). Omit to skip.')] = None,
        node_id: Annotated[Optional[str], Field(description="Restrict to devices observed by this SIGedge node_id. Omit for all nodes.")] = None,
        since_minutes: Annotated[Optional[int], Field(description="Only include devices last seen within this many minutes.")] = None,
        include_adsb: Annotated[bool, Field(description="Include ADS-B aircraft in an otherwise unfiltered query. Default false. Ignored if phy or device_type is set.")] = False,
    ) -> str:
        """List devices Kismet has seen, from the local device mirror. Despite
        the name (kept for continuity), this covers every PHY Kismet tracks
        (WiFi, Bluetooth, and ADS-B), not only WiFi; use phy to narrow to one.
        ADS-B aircraft (phy "ADSB") are EXCLUDED by default because they vastly
        outnumber everything else; set phy="ADSB" or include_adsb=true to query
        them. Call kismet_summary first to orient. Use for "what APs have we
        seen", "find device AA:BB:CC", or "what's shown up in the last hour"."""
        try:
            with connect_ro(cfg.kismet_db) as conn:
                hits = query_devices(
                    conn, mac=mac, ssid=ssid, device_type=device_type, phy=phy,
                    node_id=node_id, since_minutes=since_minutes,
                    include_adsb=include_adsb,
                )
        except Exception as e:
            raise read_error("kismet bridge database", cfg.kismet_db, e) from e
        if not hits:
            return "No devices matched those criteria in the kismet bridge database."
        return dumps({"count": len(hits), "devices": hits})

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def kismet_summary() -> str:
        """Summarize the Kismet device mirror as a whole: total devices tracked,
        breakdowns by device type and PHY, the overall time span covered, and
        which SIGedge nodes have contributed data. Use to orient before a more
        specific query_wifi_devices call, or to answer "how many devices have we
        seen". Counts include ADS-B aircraft, reported separately as adsb_count
        so they don't swamp the Wi-Fi/Bluetooth picture."""
        try:
            with connect_ro(cfg.kismet_db) as conn:
                return dumps(summarize_devices(conn))
        except Exception as e:
            raise read_error("kismet bridge database", cfg.kismet_db, e) from e
