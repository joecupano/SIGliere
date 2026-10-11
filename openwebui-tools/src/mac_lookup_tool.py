"""
title: MAC Vendor Lookup
author: SIGliere
description: Identify the manufacturer behind a MAC address (or search vendors
    by name) using the local sovereign mirror of maclookup.app's OUI/CID
    database — no MAC address or vendor query ever leaves this box. Native
    in-process Open WebUI tool.
version: 1.0.0
license: AGPL-3.0
"""
#
# "MAC lookup should be sovereign" — the Kismet tool (sigint_kismet_tool.py)
# hands the model a stream of real device MAC addresses seen over the air.
# Asking "who makes this device" for one of those shouldn't mean shipping
# that MAC out to a third-party lookup API at query time — this tool answers
# entirely from a local mirror instead. See reference/mac_mirror.py for how
# that mirror is built and kept current (weekly, via systemd/mac-mirror.timer).
#
# DEPLOYMENT (same pattern as the SigID tool):
#   The mirror lives on the host at /data/reference/mac-vendors/mac-vendors.json
#   and must be mounted into the Open WebUI container read-only:
#     Volume=/data/reference/mac-vendors:/data/mac-vendors-ref:ro
#   Then set the MAC_VENDOR_DB_PATH valve to /data/mac-vendors-ref/mac-vendors.json
#   (already the default — usually nothing to change).
#
# LOOKUP LOGIC: maclookup.app's database is not uniformly 24-bit OUIs. Three
# prefix lengths appear (confirmed against a live download):
#   6 hex digits / 24 bits — MA-L, the classic OUI (most entries)
#   7 hex digits / 28 bits — MA-M
#   9 hex digits / 36 bits — MA-S, IAB
# A given MAC can fall inside both a 24-bit OUI's block AND a more specific
# 28/36-bit sub-delegation carved out of it, so this tool always tries the
# longest (most specific) prefix length first and returns the first hit —
# standard longest-prefix-match, same principle as IP routing tables.
#
# SOURCE vs GENERATED: this file (openwebui-tools/src/) is the thin wrapper —
# docstrings, valves, error text. The lookup logic lives in sigliere_core/mac.py.
# scripts/build-owui-tools.py inlines it to produce the self-contained
# openwebui-tools/mac_lookup_tool.py that is pasted into Open WebUI. Edit here,
# then rebuild; never edit the generated file.
#
# PERFORMANCE: ~58k entries, ~7MB of JSON. Parsed once per process and kept
# in memory, keyed off the file's mtime so a mirror refresh (weekly) is
# picked up on the next call without restarting Open WebUI — no per-call
# reparse of the whole file like the (much smaller) SigID tool does.

import json

from pydantic import BaseModel, Field

from sigliere_core.mac import (
    MAX_RESULTS,
    mac_format_entry,
    mac_load_index,
    mac_lookup_prefix,
    mac_normalize_hex,
    mac_search_vendors,
)


class Tools:
    class Valves(BaseModel):
        MAC_VENDOR_DB_PATH: str = Field(
            default="/data/mac-vendors-ref/mac-vendors.json",
            description="Path to the mirrored maclookup.app JSON database AS SEEN "
            "FROM INSIDE the Open WebUI container. Mount reference/mac_mirror.py's "
            "output dir in and point this at mac-vendors.json inside it.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    def _index(self) -> dict:
        try:
            return mac_load_index(self.valves.MAC_VENDOR_DB_PATH)
        except FileNotFoundError:
            raise RuntimeError(
                f"No MAC vendor database at '{self.valves.MAC_VENDOR_DB_PATH}'. "
                "Check the valve and that reference/mac_mirror.py has run at least "
                "once (see systemd/mac-mirror.timer / scripts/install-mac-mirror.sh)."
            )

    # -- tool 1: identify the vendor for a MAC address ---------------------
    def lookup_mac_vendor(self, mac_address: str) -> str:
        """
        Look up the manufacturer/vendor that owns a MAC address, using the
        local sovereign mirror of the IEEE OUI/CID registry (no external API
        call). Accepts a full MAC ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff",
        Cisco dotted "aabb.ccdd.eeff") or just its leading prefix/OUI
        ("AA:BB:CC"). Use when the user asks "who makes this device", "what
        vendor is <mac>", or wants a Kismet-seen MAC identified.

        :param mac_address: A MAC address or MAC prefix, any common separator style (or none).
        :return: A JSON string with the matched vendor/block info, or a not-found message.
        """
        hex_digits = mac_normalize_hex(mac_address)
        if len(hex_digits) < 6:
            return (f"Error: '{mac_address}' doesn't look like a MAC address or prefix — "
                     "need at least 6 hex digits (a 24-bit OUI) to look up.")

        try:
            by_len = self._index()
        except RuntimeError as e:
            return f"Error: {e}"

        found = mac_lookup_prefix(by_len, hex_digits)
        if found:
            hit, n = found
            return json.dumps({
                "queried": mac_address,
                "match": mac_format_entry(hit, matched_prefix_len_hex=n),
            }, indent=2)

        return (f"No vendor found for '{mac_address}' in the local MAC vendor mirror "
                f"({len(by_len['all'])} entries searched). Either it's not an "
                "IEEE-registered prefix (could be a randomized/locally-administered "
                "MAC — check if bit 2 of the first octet is set) or the local mirror "
                "is stale; see reference/mac_mirror.py.")

    # -- tool 2: search vendors by name -------------------------------------
    def search_mac_vendors(self, vendor_name: str) -> str:
        """
        Search the local MAC vendor mirror by manufacturer name and list the
        MAC prefixes/OUIs registered to matching vendors. Use for "what MAC
        prefixes does <vendor> own" or to confirm how a vendor's name is
        actually spelled in the registry before other filtering.

        :param vendor_name: Vendor/company name or a distinctive substring (case-insensitive).
        :return: A JSON string of matching prefixes (capped at 50), or a not-found message.
        """
        if not vendor_name or not vendor_name.strip():
            return "Error: provide a vendor name to search for."

        try:
            by_len = self._index()
        except RuntimeError as e:
            return f"Error: {e}"

        all_hits = mac_search_vendors(by_len, vendor_name)
        if not all_hits:
            return (f"No vendor matching '{vendor_name}' found in the local MAC vendor "
                     f"mirror ({len(by_len['all'])} entries searched).")

        hits = all_hits[:MAX_RESULTS]
        return json.dumps({
            "total_matches": len(all_hits),
            "shown": len(hits),
            "prefixes": [mac_format_entry(h) for h in hits],
        }, indent=2)
