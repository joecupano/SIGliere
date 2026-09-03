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
# PERFORMANCE: ~58k entries, ~7MB of JSON. Parsed once per process and kept
# in memory, keyed off the file's mtime so a mirror refresh (weekly) is
# picked up on the next call without restarting Open WebUI — no per-call
# reparse of the whole file like the (much smaller) SigID tool does.

import json
import os
import re
import threading
from typing import Optional

from pydantic import BaseModel, Field

MAX_RESULTS = 50
PREFIX_LENGTHS_HEX = (9, 7, 6)  # longest first — order lookup tries them in

_INDEX_LOCK = threading.Lock()
_INDEX_CACHE = {}  # path -> {"mtime": float, "size": int, "by_len": {6: {...}, 7: {...}, 9: {...}}}


def _normalize_hex(s: str) -> str:
    """Strip everything but hex digits, uppercase. Accepts colon/dash/dot
    separators (aa:bb:cc, aa-bb-cc, Cisco's aabb.ccdd.eeff) or none at all."""
    return re.sub(r"[^0-9A-Fa-f]", "", s or "").upper()


def _load_index(path: str) -> dict:
    """Build (or return cached) prefix-length -> {hex_prefix: entry} indices
    from the mirror JSON. Cache is invalidated by (mtime, size) change, so a
    weekly mac_mirror.py refresh is picked up without a process restart."""
    st = os.stat(path)  # raises FileNotFoundError / PermissionError to caller
    key = (st.st_mtime, st.st_size)

    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(path)
        if cached is not None and cached["key"] == key:
            return cached["by_len"]

    with open(path, encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        raise ValueError(f"Expected a JSON array in {path}, got {type(entries).__name__}")

    by_len = {n: {} for n in PREFIX_LENGTHS_HEX}
    by_len["all"] = entries
    for e in entries:
        prefix_hex = _normalize_hex(e.get("macPrefix", ""))
        n = len(prefix_hex)
        if n in by_len:
            by_len[n][prefix_hex] = e

    with _INDEX_LOCK:
        _INDEX_CACHE[path] = {"key": key, "by_len": by_len}
    return by_len


def _format_entry(e: dict, matched_prefix_len_hex: int = None) -> dict:
    out = {
        "mac_prefix": e.get("macPrefix"),
        "vendor": e.get("vendorName") or None,
        "block_type": e.get("blockType") or None,
        "private": bool(e.get("private", False)),
        "last_update": e.get("lastUpdate"),
    }
    if matched_prefix_len_hex is not None:
        out["prefix_bits"] = matched_prefix_len_hex * 4
    if out["private"] and not out["vendor"]:
        out["vendor"] = "(private assignment — vendor not publicly disclosed by IEEE)"
    return out


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
            return _load_index(self.valves.MAC_VENDOR_DB_PATH)
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
        hex_digits = _normalize_hex(mac_address)
        if len(hex_digits) < 6:
            return (f"Error: '{mac_address}' doesn't look like a MAC address or prefix — "
                     "need at least 6 hex digits (a 24-bit OUI) to look up.")

        try:
            by_len = self._index()
        except RuntimeError as e:
            return f"Error: {e}"

        for n in PREFIX_LENGTHS_HEX:
            if len(hex_digits) < n:
                continue
            candidate = hex_digits[:n]
            hit = by_len[n].get(candidate)
            if hit:
                return json.dumps({
                    "queried": mac_address,
                    "match": _format_entry(hit, matched_prefix_len_hex=n),
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
        q = vendor_name.strip().lower()

        try:
            by_len = self._index()
        except RuntimeError as e:
            return f"Error: {e}"

        all_hits = [e for e in by_len["all"] if q in (e.get("vendorName") or "").lower()]
        if not all_hits:
            return (f"No vendor matching '{vendor_name}' found in the local MAC vendor "
                     f"mirror ({len(by_len['all'])} entries searched).")

        hits = all_hits[:MAX_RESULTS]
        return json.dumps({
            "total_matches": len(all_hits),
            "shown": len(hits),
            "prefixes": [_format_entry(h) for h in hits],
        }, indent=2)
