"""Longest-prefix MAC vendor lookup over the local maclookup.app mirror.

The database is not uniformly 24-bit OUIs. Three prefix lengths appear:
  6 hex digits / 24 bits - MA-L, the classic OUI (most entries)
  7 hex digits / 28 bits - MA-M
  9 hex digits / 36 bits - MA-S, IAB
A MAC can fall inside both a 24-bit OUI's block and a more specific 28/36-bit
sub-delegation carved out of it, so lookup tries the longest prefix first.
"""

import json
import os
import re
import threading

MAX_RESULTS = 50
PREFIX_LENGTHS_HEX = (9, 7, 6)  # longest first - order lookup tries them in

_INDEX_LOCK = threading.Lock()
_INDEX_CACHE = {}  # path -> {"key": (mtime, size), "by_len": {...}}


def mac_normalize_hex(s: str) -> str:
    """Strip everything but hex digits, uppercase. Accepts colon/dash/dot
    separators (aa:bb:cc, aa-bb-cc, Cisco's aabb.ccdd.eeff) or none at all."""
    return re.sub(r"[^0-9A-Fa-f]", "", s or "").upper()


def mac_load_index(path: str) -> dict:
    """Build (or return cached) prefix-length -> {hex_prefix: entry} indices
    from the mirror JSON. The cache is invalidated by (mtime, size) change, so
    a weekly mac_mirror.py refresh is picked up without a process restart."""
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
        prefix_hex = mac_normalize_hex(e.get("macPrefix", ""))
        n = len(prefix_hex)
        if n in by_len:
            by_len[n][prefix_hex] = e

    with _INDEX_LOCK:
        _INDEX_CACHE[path] = {"key": key, "by_len": by_len}
    return by_len


def mac_format_entry(e: dict, matched_prefix_len_hex: int = None) -> dict:
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


def mac_lookup_prefix(by_len: dict, hex_digits: str):
    """Longest-prefix match. Returns (entry, prefix_len_hex) or None."""
    for n in PREFIX_LENGTHS_HEX:
        if len(hex_digits) < n:
            continue
        hit = by_len[n].get(hex_digits[:n])
        if hit:
            return hit, n
    return None


def mac_search_vendors(by_len: dict, vendor_name: str) -> list:
    """All entries whose vendor name contains vendor_name (case-insensitive)."""
    q = vendor_name.strip().lower()
    return [e for e in by_len["all"] if q in (e.get("vendorName") or "").lower()]
