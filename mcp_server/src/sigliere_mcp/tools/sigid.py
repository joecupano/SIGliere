"""SigID (sigidwiki) reference catalog tools."""

from typing import Annotated, Optional

from pydantic import Field

from sigliere_core.sigid import (
    sigid_find_by_name,
    sigid_format_signal,
    sigid_load_signals,
    sigid_search,
)

from . import READ_ONLY, dumps, read_error


def register(mcp, cfg):
    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def lookup_signal(
        name: Annotated[str, Field(description="The signal name or a distinctive part of it (case-insensitive substring match).")],
    ) -> str:
        """Look up a signal in the SigID reference catalog by name or title (e.g.
        "OTH Radar", "STANAG 4285", "10-tone signal"). Returns the signal's known
        characteristics (frequencies, mode, modulation, bandwidth, location, and
        description) from the local sigidwiki mirror. Use when the user asks
        "what is <signal>" or "tell me about <signal>"."""
        if not name or not name.strip():
            return "Error: provide a signal name to look up."
        try:
            signals = sigid_load_signals(cfg.sigid_dir)
        except Exception as e:
            raise read_error("SigID mirror", cfg.sigid_dir, e) from e
        hits = sigid_find_by_name(signals, name)
        if not hits:
            return (f"No signal named like '{name}' found in the SigID mirror "
                    f"({len(signals)} catalog entries searched).")
        return dumps({"count": len(hits), "signals": [sigid_format_signal(s) for s in hits]})

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def search_signals(
        keyword: Annotated[Optional[str], Field(description="Text to match in mode, modulation, location, or description (case-insensitive). Omit to match all.")] = None,
        near_frequency_hz: Annotated[Optional[float], Field(description="Center frequency in Hz to search near (e.g. 6115000 for 6115 kHz). Omit to skip frequency filtering.")] = None,
        tolerance_hz: Annotated[Optional[float], Field(description="How far from near_frequency_hz counts as a match (default 100000 = 100 kHz).")] = None,
    ) -> str:
        """Search the SigID reference catalog by keyword and/or frequency. Use for
        "what signals use 8PSK", "what's known around 6 MHz", or "find military HF
        signals". Keyword matches the description/mode/modulation text; frequency
        matches signals documented near that frequency."""
        try:
            signals = sigid_load_signals(cfg.sigid_dir)
        except Exception as e:
            raise read_error("SigID mirror", cfg.sigid_dir, e) from e
        hits = sigid_search(signals, keyword=keyword,
                            near_frequency_hz=near_frequency_hz,
                            tolerance_hz=tolerance_hz)
        if not hits:
            return "No signals matched those criteria in the SigID mirror."
        return dumps({"count": len(hits), "signals": [sigid_format_signal(s) for s in hits]})
