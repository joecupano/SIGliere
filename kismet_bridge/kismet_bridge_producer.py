#!/usr/bin/env python3
"""
kismet_bridge/kismet_bridge_producer.py

Kismet bridge producer — polls the SIGedge gateway's curated
/kismet/summary/{node} and /kismet/devices/{node} endpoints and upserts
into the local kismet_bridge.db device mirror (see KISMET-BRIDGE.md).
Shape matches occupancy_producer.py closely: argparse + requests against
the gateway, --once/continuous/--node flags, bearer token from the same
gateway.env analyst role occupancy_producer.py already uses (read-only
access is sufficient — this never needs "operator").

Real difference from occupancy_producer.py, not just a rename: there is
no file-staging race here to inherit an interval from (sovereign-sigint's
15-minute cadence existed specifically to safely stage a live .kismet
SQLite file — see KISMET-BRIDGE.md's "Real opportunity, not just a port").
The gateway makes a live HTTP call to Kismet's REST API every poll, so
there's no copy-in-progress file to avoid reading. DEFAULT_INTERVAL_SEC
below is chosen deliberately smaller than that inherited number, but is
still a placeholder sized to "reasonable," not to any measured Kismet
REST load on real hardware — revisit once real polling data exists,
the same posture occupancy_db.py takes with FREQUENCY_BIN_HZ.

Usage:
  python3 kismet_bridge_producer.py                     # run continuously
  python3 kismet_bridge_producer.py --once               # one poll cycle, then exit
  python3 kismet_bridge_producer.py --node sigedge-vhf-uhf  # restrict to one node
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

from kismet_bridge_db import KismetBridgeDB

DEFAULT_GATEWAY_BASE_URL = "http://127.0.0.1:8180/gateway"
DEFAULT_DB_PATH = Path("/data/kismet-bridge/kismet_bridge.db")
DEFAULT_GATEWAY_ENV = Path.home() / ".config" / "sigliere" / "gateway.env"
DEFAULT_INTERVAL_SEC = 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kismet_bridge_producer")


def load_analyst_token(env_path: Path) -> str:
    """Same extraction occupancy_producer.py uses — kept as a small local
    copy rather than a cross-domain import, matching this repo's pattern
    of each producer being independently runnable from its own venv."""
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


class KismetBridgeProducer:
    def __init__(
        self,
        db: KismetBridgeDB,
        gateway_base_url: str,
        analyst_token: str,
        nodes: list[str] | None = None,
        timeout_sec: float = 15.0,
        session: requests.Session | None = None,
    ):
        self.db = db
        self.gateway_base_url = gateway_base_url.rstrip("/")
        self.analyst_token = analyst_token
        self.nodes = nodes
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

    def discover_nodes(self) -> list[str]:
        """--node overrides always win; otherwise ask the gateway which
        configured nodes have Kismet enabled at all, rather than trying
        every node and treating 409 as routine — mirrors occupancy's
        "default: all configured nodes" convention (see
        KISMET-BRIDGE.md's open question on multi-node default)."""
        if self.nodes:
            return self.nodes
        try:
            nodes = self._get("/nodes").get("nodes", [])
        except requests.RequestException as exc:
            logger.warning("node discovery failed: %s", exc)
            return []
        return [n["node_id"] for n in nodes if n.get("kismet_enabled")]

    def poll_once(self) -> int:
        """One full poll cycle: for every Kismet-enabled node, fetch
        /kismet/devices/{node} and upsert each device. Returns the number
        of devices upserted."""
        recorded = 0
        for node_id in self.discover_nodes():
            try:
                result = self._get(f"/kismet/devices/{node_id}")
            except requests.RequestException as exc:
                logger.warning("device fetch failed for %s: %s", node_id, exc)
                continue
            for device in result.get("devices", []):
                mac = device.get("mac")
                if not mac:
                    continue
                self.db.upsert_device(
                    node_id=node_id,
                    mac=mac,
                    device_type=device.get("type"),
                    phy=device.get("phy"),
                    ssid=device.get("ssid") or None,
                    manufacturer=device.get("manuf") or None,
                    signal_dbm=device.get("signal_dbm"),
                    first_seen_sec=device.get("first_time"),
                    last_seen_sec=device.get("last_time"),
                    metadata_json=json.dumps(device),
                )
                recorded += 1
        logger.info("poll complete: %d device(s) recorded", recorded)
        return recorded

    def run_forever(self, interval_sec: float) -> None:
        while True:
            try:
                self.poll_once()
            except Exception:
                logger.exception("poll cycle failed; will retry after interval")
            time.sleep(interval_sec)


def main() -> int:
    parser = argparse.ArgumentParser(description="SIGliere Kismet bridge producer")
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
        default=Path(os.environ.get("SIGLIERE_KISMET_BRIDGE_DB", str(DEFAULT_DB_PATH))),
        help=f"kismet bridge database path (default {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--node", action="append", dest="nodes",
        help="restrict polling to this SIGedge node_id (repeatable); "
        "default: every node the gateway reports as kismet_enabled",
    )
    args = parser.parse_args()

    token = load_analyst_token(args.gateway_env)
    db = KismetBridgeDB(args.db_path)
    producer = KismetBridgeProducer(
        db=db,
        gateway_base_url=args.gateway_url,
        analyst_token=token,
        nodes=args.nodes,
    )

    if args.once:
        producer.poll_once()
        return 0

    producer.run_forever(args.interval_sec)
    return 0  # pragma: no cover - run_forever loops until killed


if __name__ == "__main__":
    sys.exit(main())
