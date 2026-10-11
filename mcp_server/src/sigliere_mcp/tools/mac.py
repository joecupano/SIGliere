"""MAC vendor (IEEE OUI/CID) lookup tools."""

from typing import Annotated

from pydantic import Field

from sigliere_core.mac import (
    MAX_RESULTS,
    mac_format_entry,
    mac_load_index,
    mac_lookup_prefix,
    mac_normalize_hex,
    mac_search_vendors,
)

from . import READ_ONLY, dumps, read_error


def register(mcp, cfg):
    def index():
        try:
            return mac_load_index(cfg.mac_db)
        except Exception as e:
            raise read_error("MAC vendor database", cfg.mac_db, e) from e

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def lookup_mac_vendor(
        mac_address: Annotated[str, Field(description="A MAC address or MAC prefix, any common separator style (or none).")],
    ) -> str:
        """Look up the manufacturer/vendor that owns a MAC address, using the
        local mirror of the IEEE OUI/CID registry (no external API call). Accepts
        a full MAC ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", Cisco dotted
        "aabb.ccdd.eeff") or just its leading prefix/OUI ("AA:BB:CC"). Use when
        the user asks "who makes this device", "what vendor is <mac>", or wants a
        Kismet-seen MAC identified."""
        hex_digits = mac_normalize_hex(mac_address)
        if len(hex_digits) < 6:
            return (f"Error: '{mac_address}' doesn't look like a MAC address or prefix — "
                    "need at least 6 hex digits (a 24-bit OUI) to look up.")
        by_len = index()
        found = mac_lookup_prefix(by_len, hex_digits)
        if found:
            hit, n = found
            return dumps({"queried": mac_address,
                          "match": mac_format_entry(hit, matched_prefix_len_hex=n)})
        return (f"No vendor found for '{mac_address}' in the local MAC vendor mirror "
                f"({len(by_len['all'])} entries searched). Either it's not an "
                "IEEE-registered prefix (could be a randomized/locally-administered "
                "MAC — check if bit 2 of the first octet is set) or the local mirror "
                "is stale; see reference/mac_mirror.py.")

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def search_mac_vendors(
        vendor_name: Annotated[str, Field(description="Vendor/company name or a distinctive substring (case-insensitive).")],
    ) -> str:
        """Search the local MAC vendor mirror by manufacturer name and list the
        MAC prefixes/OUIs registered to matching vendors (capped at 50). Use for
        "what MAC prefixes does <vendor> own" or to confirm how a vendor's name is
        actually spelled in the registry."""
        if not vendor_name or not vendor_name.strip():
            return "Error: provide a vendor name to search for."
        by_len = index()
        all_hits = mac_search_vendors(by_len, vendor_name)
        if not all_hits:
            return (f"No vendor matching '{vendor_name}' found in the local MAC vendor "
                    f"mirror ({len(by_len['all'])} entries searched).")
        hits = all_hits[:MAX_RESULTS]
        return dumps({"total_matches": len(all_hits), "shown": len(hits),
                      "prefixes": [mac_format_entry(h) for h in hits]})
