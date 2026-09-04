import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "occupancy"))

from occupancy_db import OccupancyDB
from occupancy_producer import OccupancyProducer, load_analyst_token


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
    """Records requests, returns canned /status responses keyed by URL suffix."""

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

    def test_missing_analyst_role_raises(self):
        with TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "gateway.env"
            env_path.write_text('SIGLIERE_GATEWAY_TOKENS_JSON={"tok-o":"operator"}\n')
            with self.assertRaises(RuntimeError):
                load_analyst_token(env_path)


class OccupancyProducerTests(unittest.TestCase):
    def test_poll_once_records_channels_as_dict(self):
        # ka9q-python's native shape: Dict[int, ChannelInfo], JSON-serialized
        # with string keys (see gateway/tests/test_sigedge_client.py).
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")
            session = FakeSession({
                "/status": {
                    "nodes": [{
                        "node_id": "sigedge-hf",
                        "reachable": True,
                        "channels": {
                            "7": {
                                "ssrc": 7, "frequency": 10_000_000, "preset": "usb",
                                "snr": 12.5, "sample_rate": 12000,
                                "multicast_address": "239.1.64.3",
                            }
                        },
                    }]
                }
            })
            producer = OccupancyProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=session,
            )

            recorded = producer.poll_once()

            self.assertEqual(recorded, 1)
            signal = db.get_signal("10000000:usb")
            self.assertIsNotNone(signal)
            sighting = db.get_sightings("10000000:usb")[0]
            self.assertEqual(sighting["source_device"], "sigedge-hf")
            metadata = json.loads(sighting["metadata_json"])
            self.assertEqual(metadata["ssrc"], 7)
            self.assertEqual(metadata["snr_db"], 12.5)

    def test_poll_once_records_channels_as_list(self):
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")
            session = FakeSession({
                "/status": {
                    "nodes": [{
                        "node_id": "sigedge-vhf-aprs",
                        "reachable": True,
                        "channels": [
                            {"ssrc": 99, "frequency": 144_390_000, "preset": "fm", "snr": 8.0},
                        ],
                    }]
                }
            })
            producer = OccupancyProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=session,
            )

            recorded = producer.poll_once()

            self.assertEqual(recorded, 1)
            self.assertIsNotNone(db.get_signal("144390000:fm"))

    def test_unreachable_node_is_skipped_not_errored(self):
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")
            session = FakeSession({
                "/status": {"nodes": [{"node_id": "sigedge-hf", "reachable": False}]}
            })
            producer = OccupancyProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=session,
            )

            recorded = producer.poll_once()

            self.assertEqual(recorded, 0)
            self.assertEqual(db.summary()["signal_count"], 0)

    def test_min_snr_db_filters_out_weak_channels(self):
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")
            session = FakeSession({
                "/status": {
                    "nodes": [{
                        "node_id": "sigedge-hf",
                        "reachable": True,
                        "channels": [
                            {"ssrc": 1, "frequency": 10_000_000, "preset": "usb", "snr": 2.0},
                            {"ssrc": 2, "frequency": 20_000_000, "preset": "usb", "snr": 15.0},
                        ],
                    }]
                }
            })
            producer = OccupancyProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=session, min_snr_db=10.0,
            )

            recorded = producer.poll_once()

            self.assertEqual(recorded, 1)
            self.assertIsNone(db.get_signal("10000000:usb"))
            self.assertIsNotNone(db.get_signal("20000000:usb"))

    def test_per_node_status_used_when_nodes_specified(self):
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")
            session = FakeSession({
                "/status/sigedge-hf": {
                    "node_id": "sigedge-hf",
                    "reachable": True,
                    "channels": [{"ssrc": 1, "frequency": 10_000_000, "preset": "usb", "snr": 5.0}],
                },
            })
            producer = OccupancyProducer(
                db=db, gateway_base_url="http://127.0.0.1:8180/gateway",
                analyst_token="tok-a", session=session, nodes=["sigedge-hf"],
            )

            recorded = producer.poll_once()

            self.assertEqual(recorded, 1)
            self.assertEqual(len(session.calls), 1)
            self.assertTrue(session.calls[0][0].endswith("/status/sigedge-hf"))
            self.assertEqual(session.calls[0][1]["Authorization"], "Bearer tok-a")


if __name__ == "__main__":
    unittest.main()
