import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kismet_bridge"))

from kismet_bridge_db import KismetBridgeDB
from kismet_bridge_producer import KismetBridgeProducer, load_analyst_token


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        for suffix, payload in self.responses.items():
            if url.endswith(suffix):
                return FakeResponse(payload)
        raise AssertionError(f"unexpected URL: {url}")


class LoadAnalystTokenTests(unittest.TestCase):
    def test_extracts_analyst_token(self):
        with TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "gateway.env"
            env_path.write_text(
                'SIGLIERE_GATEWAY_TOKENS_JSON={"tok-a":"analyst","tok-o":"operator"}\n'
            )
            self.assertEqual(load_analyst_token(env_path), "tok-a")

    def test_missing_file_raises(self):
        with self.assertRaises(RuntimeError):
            load_analyst_token(Path("/nonexistent/gateway.env"))


class KismetBridgeProducerTests(unittest.TestCase):
    def test_discover_nodes_filters_kismet_enabled(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            session = FakeSession({
                "/nodes": {"nodes": [
                    {"node_id": "sigedge-hf", "kismet_enabled": False},
                    {"node_id": "sigedge-vhf-uhf", "kismet_enabled": True},
                ]}
            })
            producer = KismetBridgeProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=session,
            )
            self.assertEqual(producer.discover_nodes(), ["sigedge-vhf-uhf"])

    def test_explicit_nodes_override_discovery(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            session = FakeSession({})
            producer = KismetBridgeProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=session, nodes=["sigedge-vhf-uhf"],
            )
            self.assertEqual(producer.discover_nodes(), ["sigedge-vhf-uhf"])
            self.assertEqual(session.calls, [])

    def test_poll_once_upserts_devices(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            session = FakeSession({
                "/nodes": {"nodes": [{"node_id": "sigedge-vhf-uhf", "kismet_enabled": True}]},
                "/kismet/devices/sigedge-vhf-uhf": {
                    "node_id": "sigedge-vhf-uhf",
                    "devices": [
                        {
                            "mac": "AA:BB:CC:00:00:01", "phy": "IEEE802.11", "type": "AP",
                            "manuf": "Acme", "signal_dbm": -40, "first_time": 1000,
                            "last_time": 2000, "ssid": "coffeeshop",
                        },
                    ],
                },
            })
            producer = KismetBridgeProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=session,
            )

            recorded = producer.poll_once()

            self.assertEqual(recorded, 1)
            device = db.get_device("sigedge-vhf-uhf", "AA:BB:CC:00:00:01")
            self.assertIsNotNone(device)
            self.assertEqual(device["ssid"], "coffeeshop")

    def test_device_fetch_failure_for_one_node_does_not_abort_poll(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            session = FakeSession({
                "/nodes": {"nodes": [
                    {"node_id": "sigedge-vhf-uhf", "kismet_enabled": True},
                ]},
                # No /kismet/devices/... entry -> FakeSession raises AssertionError,
                # which is not a requests.RequestException, so simulate the real
                # failure mode with a session that raises RequestException instead.
            })

            class FailingSession(FakeSession):
                def get(self, url, headers=None, timeout=None):
                    if url.endswith("/nodes"):
                        return super().get(url, headers=headers, timeout=timeout)
                    import requests

                    raise requests.ConnectionError("unreachable")

            producer = KismetBridgeProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=FailingSession(session.responses),
            )

            recorded = producer.poll_once()

            self.assertEqual(recorded, 0)


if __name__ == "__main__":
    unittest.main()
