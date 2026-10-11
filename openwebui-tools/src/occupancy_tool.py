"""
title: SIGINT Occupancy
author: SIGliere
description: Query the local occupancy database — which frequencies SIGedge
    has actively demodulated, when, and how recently. Native in-process
    Open WebUI tool, read-only against the host-side occupancy.db mirror.
version: 1.0.0
license: AGPL-3.0
"""
#
# THE THIRD AI SOURCE (see sigid_reference_tool.py for the full three-way
# split):
#   occupancy = what frequencies are active (our own capture) <- this tool
#   kismet    = what devices are present (our own capture — see kismet_tool.py)
#   sigid     = what signals ARE — the reference catalog to identify them
#
# occupancy.db is written host-side by occupancy/occupancy_producer.py,
# polling the SIGedge gateway's /status endpoint (never touching SIGedge
# hardware or radiod directly — see docs/occupancy-guide.md). This tool
# only reads that SQLite file from inside the Open WebUI container, using
# plain sqlite3 rather than importing occupancy_db.py — same as every
# other native tool here, this file is self-contained so it can be pasted
# straight into Workspace -> Tools with no repo checkout inside the
# container. It makes no gateway calls of its own and needs no bearer token.
#
# SOURCE vs GENERATED: this file (openwebui-tools/src/) is the thin wrapper —
# docstrings, valves, error text. The query logic lives in
# sigliere_core/occupancy.py. scripts/build-owui-tools.py inlines it to
# produce the self-contained openwebui-tools/occupancy_tool.py that is pasted
# into Open WebUI. Edit here, then rebuild; never edit the generated file.
#
# OPTIONAL DEPLOYMENT:
#   Mount the occupancy data dir in read-only, e.g.:
#     Volume=/data/occupancy:/data/occupancy-ref:ro
#   Then set the OCCUPANCY_DB_PATH valve to /data/occupancy-ref/occupancy.db.
#   (:ro is fine — the tool only reads; occupancy_producer.py writes on the
#   host in rollback-journal mode, not WAL — WAL can't be opened from a
#   read-only mount between writes.)

import json
from typing import Optional

from pydantic import BaseModel, Field

from sigliere_core.occupancy import list_sightings, query_signals, summarize_occupancy
from sigliere_core.sqlite_ro import connect_ro


class Tools:
    class Valves(BaseModel):
        OCCUPANCY_DB_PATH: str = Field(
            default="/data/occupancy-ref/occupancy.db",
            description="Path to occupancy.db AS SEEN FROM INSIDE the Open "
            "WebUI container. Mount occupancy_producer.py's output dir in "
            "and point this at it.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    # -- tool 1: aggregate signals in a range ------------------------------
    def query_occupancy(
        self,
        near_frequency_hz: Optional[float] = None,
        tolerance_hz: Optional[float] = None,
        mode: Optional[str] = None,
        since_minutes: Optional[int] = None,
    ) -> str:
        """
        List signals SIGedge has actively demodulated, from the local
        occupancy database. Each result is an aggregate: a frequency+mode
        pair with first/last-seen times and a total sighting count — not a
        single detection event. Use for "what's active around 14 MHz", "what
        FM traffic have we seen", or "what's been active in the last hour".

        :param near_frequency_hz: Center frequency in Hz to search near (e.g. 14074000). Omit to skip frequency filtering.
        :param tolerance_hz: How far from near_frequency_hz counts as a match (default 5000 = 5 kHz).
        :param mode: Filter by radiod preset/mode (e.g. "usb", "nfm"). Case-sensitive match against what was recorded.
        :param since_minutes: Only include signals last seen within this many minutes.
        :return: A JSON string of matching signals, or a not-found message.
        """
        try:
            with connect_ro(self.valves.OCCUPANCY_DB_PATH) as conn:
                hits = query_signals(
                    conn, near_frequency_hz=near_frequency_hz,
                    tolerance_hz=tolerance_hz, mode=mode, since_minutes=since_minutes,
                )
        except Exception as e:
            return (f"Error reading occupancy database at "
                    f"'{self.valves.OCCUPANCY_DB_PATH}': {e.__class__.__name__}: {e}. "
                    f"Check the valve and that the data dir is mounted in.")

        if not hits:
            return "No signals matched those criteria in the occupancy database."
        return json.dumps({"count": len(hits), "signals": hits}, indent=2)

    # -- tool 2: raw detection events for one signal -----------------------
    def occupancy_sightings(self, signal_key: str) -> str:
        """
        List individual detection events for one aggregate signal, oldest
        first. Use after query_occupancy identifies a signal_key of interest
        and the user wants the underlying history rather than just the
        aggregate.

        :param signal_key: The signal_key from a query_occupancy result (e.g. "14074000:usb").
        :return: A JSON string of sighting events, or a not-found message.
        """
        if not signal_key or not signal_key.strip():
            return "Error: provide a signal_key from query_occupancy."
        try:
            with connect_ro(self.valves.OCCUPANCY_DB_PATH) as conn:
                hits = list_sightings(conn, signal_key.strip())
        except Exception as e:
            return (f"Error reading occupancy database at "
                    f"'{self.valves.OCCUPANCY_DB_PATH}': {e.__class__.__name__}: {e}.")
        if not hits:
            return f"No sightings found for signal_key '{signal_key}'."
        return json.dumps({"count": len(hits), "sightings": hits}, indent=2)

    # -- tool 3: quick database-wide summary -------------------------------
    def occupancy_summary(self) -> str:
        """
        Summarize the occupancy database as a whole: total signals and
        sightings tracked, the overall time span covered, and which SIGedge
        nodes have contributed data. Use to orient before a more specific
        query_occupancy call, or to answer "how much occupancy data do we
        have".

        :return: A JSON string with the summary counts.
        """
        try:
            with connect_ro(self.valves.OCCUPANCY_DB_PATH) as conn:
                summary = summarize_occupancy(conn)
        except Exception as e:
            return (f"Error reading occupancy database at "
                    f"'{self.valves.OCCUPANCY_DB_PATH}': {e.__class__.__name__}: {e}.")
        return json.dumps(summary, indent=2)
