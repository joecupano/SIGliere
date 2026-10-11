"""
title: SIGINT SigID Reference
author: SIGliere
description: Look up signals in the local SigID (sigidwiki) reference mirror —
    by name, frequency, or characteristics. Native in-process Open WebUI tool,
    the optional reference source, giving the local LLM authoritative signal
    reference data without collection-tier access.
version: 1.0.0
license: AGPL-3.0
"""
#
# THE THIRD AI SOURCE — reference, not observation:
#   occupancy = what frequencies are active (our own capture)
#   kismet    = what devices are present (our own capture — see kismet_tool.py)
#   sigid     = what signals ARE — the reference catalog to identify them
#
#   This mirrors the occupancy/kismet native-tool pattern, but the SigID data
#   is NOT a single SQLite file. The SigID mirror stores one JSON per wiki
#   page under /data/reference/sigid/metadata/<title>.json, each containing the
#   page's MediaWiki `wikitext`. Real signal pages carry a structured infobox:
#     {{Unidentified Signal |Frequencies=6115 kHz |Mode=AM |Modulation=8PSK
#      |Bandwidth=7 kHz |Location=... |Signal description=...}}
#   Many pages (~150 of ~500) are #REDIRECT stubs — skipped. This tool parses
#   the infobox into fields so the model can do name lookup, keyword search,
#   and (best-effort) frequency-range search.
#
# OPTIONAL DEPLOYMENT:
#   The tool runs inside the Open WebUI container, so the SigID metadata dir
#   must be mounted in. Add to the quadlet, e.g.:
#     Volume=/data/reference/sigid:/data/sigid-ref:ro
#   (:ro is fine — the tool only reads; the mirror timer writes on the host.)
#   Then set the SIGID_METADATA_DIR valve to /data/sigid-ref/metadata.
#
# SOURCE vs GENERATED: this file (openwebui-tools/src/) is the thin wrapper —
#   docstrings, valves, error text. The parsing and search logic lives in
#   sigliere_core/sigid.py. scripts/build-owui-tools.py inlines it to produce
#   the self-contained openwebui-tools/sigid_reference_tool.py that is pasted
#   into Open WebUI. Edit here, then rebuild; never edit the generated file.
#
# PERFORMANCE: ~350 small JSON files. The tool builds a light in-memory index
#   once per call (parse infoboxes), which is fast enough at this scale. If the
#   catalog grows large, this is the point to switch to a prebuilt SQLite index.

import json
from typing import Optional

from pydantic import BaseModel, Field

from sigliere_core.sigid import (
    sigid_find_by_name,
    sigid_format_signal,
    sigid_load_signals,
    sigid_search,
)


class Tools:
    class Valves(BaseModel):
        SIGID_METADATA_DIR: str = Field(
            default="/data/sigid-ref/metadata",
            description="Directory of SigID mirror metadata JSON files AS SEEN "
            "FROM INSIDE the Open WebUI container. Mount the mirror's metadata "
            "dir in and point this at it.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    # -- tool 1: look up a signal by name ---------------------------------
    def lookup_signal(self, name: str) -> str:
        """
        Look up a signal in the SigID reference catalog by name or title (e.g.
        "OTH Radar", "LoRa", "STANAG 4285", "10-tone signal"). Returns the
        signal's known characteristics — frequencies, mode, modulation,
        bandwidth, location, and description — from the local sigidwiki mirror.
        Use when the user asks "what is <signal>" or "tell me about <signal>".

        :param name: The signal name or a distinctive part of it (case-insensitive substring match).
        :return: A JSON string with the matching signal(s)' details, or a not-found message.
        """
        if not name or not name.strip():
            return "Error: provide a signal name to look up."
        try:
            signals = sigid_load_signals(self.valves.SIGID_METADATA_DIR)
        except Exception as e:
            return (f"Error reading SigID mirror at "
                    f"'{self.valves.SIGID_METADATA_DIR}': {e.__class__.__name__}: {e}. "
                    f"Check the valve and that the mirror dir is mounted in.")
        hits = sigid_find_by_name(signals, name)
        if not hits:
            return (f"No signal named like '{name}' found in the SigID mirror "
                    f"({len(signals)} catalog entries searched).")
        return json.dumps({"count": len(hits),
                           "signals": [sigid_format_signal(s) for s in hits]}, indent=2)

    # -- tool 2: search signals by characteristic -------------------------
    def search_signals(
        self,
        keyword: Optional[str] = None,
        near_frequency_hz: Optional[float] = None,
        tolerance_hz: Optional[float] = None,
    ) -> str:
        """
        Search the SigID reference catalog by keyword and/or frequency. Use for
        "what signals use 8PSK", "what's known around 6 MHz", or "find military
        HF signals". Keyword matches the description/mode/modulation text;
        frequency matches signals documented near that frequency.

        :param keyword: Text to match in mode, modulation, location, or description (case-insensitive). Omit to match all.
        :param near_frequency_hz: Center frequency in Hz to search near (e.g. 6115000 for 6115 kHz). Omit to skip frequency filtering.
        :param tolerance_hz: How far from near_frequency_hz counts as a match (default 100000 = 100 kHz).
        :return: A JSON string of matching signals, or a not-found message.
        """
        try:
            signals = sigid_load_signals(self.valves.SIGID_METADATA_DIR)
        except Exception as e:
            return (f"Error reading SigID mirror at "
                    f"'{self.valves.SIGID_METADATA_DIR}': {e.__class__.__name__}: {e}.")
        hits = sigid_search(signals, keyword=keyword,
                            near_frequency_hz=near_frequency_hz,
                            tolerance_hz=tolerance_hz)
        if not hits:
            return "No signals matched those criteria in the SigID mirror."
        return json.dumps({"count": len(hits),
                           "signals": [sigid_format_signal(s) for s in hits]}, indent=2)
