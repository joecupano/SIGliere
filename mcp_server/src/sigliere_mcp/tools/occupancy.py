"""Occupancy (signals-heard) database tools (occupancy.db)."""

from typing import Annotated, Optional

from pydantic import Field

from sigliere_core.occupancy import list_sightings, query_signals, summarize_occupancy
from sigliere_core.sqlite_ro import connect_ro

from . import READ_ONLY, dumps, read_error


def register(mcp, cfg):
    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def query_occupancy(
        near_frequency_hz: Annotated[Optional[float], Field(description="Center frequency in Hz to search near (e.g. 14074000). Omit to skip frequency filtering.")] = None,
        tolerance_hz: Annotated[Optional[float], Field(description="How far from near_frequency_hz counts as a match (default 5000 = 5 kHz).")] = None,
        mode: Annotated[Optional[str], Field(description='Filter by radiod preset/mode (e.g. "usb", "nfm"). Case-sensitive match against what was recorded.')] = None,
        since_minutes: Annotated[Optional[int], Field(description="Only include signals last seen within this many minutes.")] = None,
    ) -> str:
        """List signals SIGedge has actively demodulated, from the local occupancy
        database. Each result is an aggregate: a frequency+mode pair with
        first/last-seen times and a total sighting count, not a single detection
        event. Use for "what's active around 14 MHz", "what FM traffic have we
        seen", or "what's been active in the last hour"."""
        try:
            with connect_ro(cfg.occupancy_db) as conn:
                hits = query_signals(
                    conn, near_frequency_hz=near_frequency_hz,
                    tolerance_hz=tolerance_hz, mode=mode, since_minutes=since_minutes,
                )
        except Exception as e:
            raise read_error("occupancy database", cfg.occupancy_db, e) from e
        if not hits:
            return "No signals matched those criteria in the occupancy database."
        return dumps({"count": len(hits), "signals": hits})

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def occupancy_sightings(
        signal_key: Annotated[str, Field(description='The signal_key from a query_occupancy result (e.g. "14074000:usb").')],
    ) -> str:
        """List individual detection events for one aggregate signal, oldest
        first. Use after query_occupancy identifies a signal_key of interest and
        the user wants the underlying history rather than just the aggregate."""
        if not signal_key or not signal_key.strip():
            return "Error: provide a signal_key from query_occupancy."
        try:
            with connect_ro(cfg.occupancy_db) as conn:
                hits = list_sightings(conn, signal_key.strip())
        except Exception as e:
            raise read_error("occupancy database", cfg.occupancy_db, e) from e
        if not hits:
            return f"No sightings found for signal_key '{signal_key}'."
        return dumps({"count": len(hits), "sightings": hits})

    @mcp.tool(annotations=READ_ONLY, structured_output=False)
    def occupancy_summary() -> str:
        """Summarize the occupancy database as a whole: total signals and
        sightings tracked, the overall time span covered, and which SIGedge nodes
        have contributed data. Use to orient before a more specific
        query_occupancy call, or to answer "how much occupancy data do we have"."""
        try:
            with connect_ro(cfg.occupancy_db) as conn:
                return dumps(summarize_occupancy(conn))
        except Exception as e:
            raise read_error("occupancy database", cfg.occupancy_db, e) from e
