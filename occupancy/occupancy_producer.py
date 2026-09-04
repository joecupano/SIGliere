#!/usr/bin/env python3
"""
occupancy/occupancy_producer.py

Occupancy producer — logs signals heard into occupancy.db, in the
Kismet-derived schema ported from sovereign-sigint (see
docs/occupancy-guide.md). This is where that project and this one
genuinely diverge, not just a rename:

sovereign-sigint's producers (radiod_occupancy_producer.py,
vhf_uhf_key_freq_producer.py, the GNU Radio monitors) read raw IQ or
demodulator power directly off an SDR, on the same host, with a
hand-calibrated dBFS threshold per device+antenna. None of that is
legal here — docs/architecture.md is explicit that SIGliere "must not
... read SIGedge radiod configuration files ... invoke SIGedge systemd
units ... contain receiver models, gain settings, or device profiles
... mount collection databases or capture directories." SIGliere has
exactly one lawful window into SIGedge: the authenticated gateway's
/status endpoint (gateway/src/sigedge_gateway.py), itself backed by
KA9Q status multicast via ka9q-python.

What that endpoint actually returns per channel (ka9q.ChannelInfo):
ssrc, preset (mode), sample_rate, frequency, snr, multicast_address —
no raw samples, no dBFS, no gain/antenna knowledge. So the detection
question changes shape: sovereign-sigint asked "is the energy on this
frequency above a hand-calibrated noise floor" from raw samples this
tier is not allowed to see; this producer asks "does SIGedge currently
have a demodulator running on this frequency" — a channel only exists
in KA9Q status because something (an always-on config, or a prior
operator tune through this same gateway) asked radiod to run one
there, so a channel's mere presence in a poll IS a real occupancy
answer ("in use over this window"), not a proxy for one. SNR still
rides along in metadata_json for later filtering/query, and
--min-snr-db is available for sites that want a squelch-like cut, but
it is not a default gate — unlike the original project's dBFS
thresholds, there is no per-site calibration step to do here, because
this producer never sees anything calibration would apply to.

Usage:
  python3 occupancy_producer.py                  # run continuously
  python3 occupancy_producer.py --once            # one poll cycle, then exit
  python3 occupancy_producer.py --node sigedge-hf # restrict to one node
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from occupancy_db import OccupancyDB

DEFAULT_GATEWAY_BASE_URL = "http://127.0.0.1:8180/gateway"
DEFAULT_DB_PATH = Path("/data/occupancy/occupancy.db")
DEFAULT_GATEWAY_ENV = Path.home() / ".config" / "sigliere" / "gateway.env"
DEFAULT_INTERVAL_SEC = 30
SOURCE_TYPE = "sigedge_gateway_status"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("occupancy_producer")


def load_analyst_token(env_path: Path) -> str:
    """Pull the analyst-role bearer token out of
    ~/.config/sigliere/gateway.env's SIGLIERE_GATEWAY_TOKENS_JSON line —
    the same file scripts/install-sigedge-gateway.sh generates. Mirrors
    the sed pattern scripts/validate-tiered.sh already uses, in Python.
    """
    if not env_path.exists():
        raise RuntimeError(
            f"gateway env file not found at {env_path} — run "
            "scripts/install-sigedge-gateway.sh first"
        )
    for line in env_path.read_text().splitlines():
        if not line.startswith("SIGLIERE_GATEWAY_TOKENS_JSON="):
            continue
        raw = line.split("=", 1)[1].strip()
        try:
            tokens = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"malformed SIGLIERE_GATEWAY_TOKENS_JSON in {env_path}") from exc
        for token, role in tokens.items():
            if role == "analyst":
                return token
        raise RuntimeError(f"no analyst token found in {env_path}")
    raise RuntimeError(f"SIGLIERE_GATEWAY_TOKENS_JSON not set in {env_path}")


def _channel_list(channels) -> list:
    """The gateway's /status response nests channels per node as either
    a dict keyed by ssrc (ka9q-python's native Dict[int, ChannelInfo]
    shape, JSON-serialized with string keys) or a list — observed both
    in gateway/tests/test_sigedge_client.py's fakes. Normalize to a
    plain list of channel dicts either way.
    """
    if isinstance(channels, dict):
        return list(channels.values())
    if isinstance(channels, list):
        return channels
    return []


class OccupancyProducer:
    def __init__(
        self,
        db: OccupancyDB,
        gateway_base_url: str,
        analyst_token: str,
        nodes: list[str] | None = None,
        min_snr_db: float | None = None,
        timeout_sec: float = 15.0,
        session: requests.Session | None = None,
    ):
        self.db = db
        self.gateway_base_url = gateway_base_url.rstrip("/")
        self.analyst_token = analyst_token
        self.nodes = nodes
        self.min_snr_db = min_snr_db
        self.timeout_sec = timeout_sec
        self.session = session or requests.Session()

    def _get(self, path: str) -> dict:
        url = f"{self.gateway_base_url}{path}"
        response = self.session.get(
            url,
            headers={"Authorization": f"Bearer {self.analyst_token}"},
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return response.json()

    def fetch_status(self) -> list[dict]:
        """One /status (or per-node /status/<id>) round trip. Returns
        the gateway's per-node result list regardless of which path was
        used, so poll_once() doesn't need to care."""
        if self.nodes:
            results = []
            for node_id in self.nodes:
                try:
                    results.append(self._get(f"/status/{node_id}"))
                except requests.RequestException as exc:
                    logger.warning("status fetch failed for %s: %s", node_id, exc)
            return results
        try:
            return self._get("/status").get("nodes", [])
        except requests.RequestException as exc:
            logger.warning("status fetch failed: %s", exc)
            return []

    def poll_once(self) -> int:
        """One full poll cycle: fetch live gateway status for every
        configured node, record a sighting for every channel currently
        reported. Returns the number of sightings recorded."""
        recorded = 0
        for node_result in self.fetch_status():
            node_id = node_result.get("node_id", "unknown")
            if not node_result.get("reachable", False):
                logger.debug("node %s not reachable this poll", node_id)
                continue
            for channel in _channel_list(node_result.get("channels")):
                frequency_hz = channel.get("frequency")
                if not frequency_hz:
                    continue
                snr_db = channel.get("snr")
                if self.min_snr_db is not None and (
                    snr_db is None or snr_db < self.min_snr_db
                ):
                    continue
                mode = channel.get("preset")
                metadata = {
                    "ssrc": channel.get("ssrc"),
                    "snr_db": snr_db,
                    "sample_rate": channel.get("sample_rate"),
                    "multicast_address": channel.get("multicast_address"),
                }
                self.db.record_sighting(
                    frequency_hz=float(frequency_hz),
                    source_type=SOURCE_TYPE,
                    source_device=node_id,
                    mode=mode,
                    metadata_json=json.dumps(metadata),
                )
                recorded += 1
        logger.info("poll complete: %d sighting(s) recorded", recorded)
        return recorded

    def run_forever(self, interval_sec: float) -> None:
        while True:
            try:
                self.poll_once()
            except Exception:
                logger.exception("poll cycle failed; will retry after interval")
            time.sleep(interval_sec)


def main() -> int:
    parser = argparse.ArgumentParser(description="SIGliere occupancy producer")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument(
        "--interval-sec", type=float, default=DEFAULT_INTERVAL_SEC,
        help=f"seconds between polls in continuous mode (default {DEFAULT_INTERVAL_SEC})",
    )
    parser.add_argument(
        "--gateway-url", default=os.environ.get("SIGLIERE_GATEWAY_URL", DEFAULT_GATEWAY_BASE_URL),
        help="SIGedge gateway base URL (default: Caddy's loopback route)",
    )
    parser.add_argument(
        "--gateway-env", type=Path, default=DEFAULT_GATEWAY_ENV,
        help="path to gateway.env holding SIGLIERE_GATEWAY_TOKENS_JSON",
    )
    parser.add_argument(
        "--db-path", type=Path,
        default=Path(os.environ.get("SIGLIERE_OCCUPANCY_DB", str(DEFAULT_DB_PATH))),
        help=f"occupancy database path (default {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--node", action="append", dest="nodes",
        help="restrict polling to this SIGedge node_id (repeatable); default: all configured nodes",
    )
    parser.add_argument(
        "--min-snr-db", type=float, default=None,
        help="optional squelch-like SNR floor; omit to record every reported channel",
    )
    args = parser.parse_args()

    token = load_analyst_token(args.gateway_env)
    db = OccupancyDB(args.db_path)
    producer = OccupancyProducer(
        db=db,
        gateway_base_url=args.gateway_url,
        analyst_token=token,
        nodes=args.nodes,
        min_snr_db=args.min_snr_db,
    )

    if args.once:
        producer.poll_once()
        return 0

    producer.run_forever(args.interval_sec)
    return 0  # pragma: no cover - run_forever loops until killed


if __name__ == "__main__":
    sys.exit(main())
