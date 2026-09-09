import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway" / "src"))

from sigedge_client import KismetClient, SigedgeNode


NODE = SigedgeNode(
    node_id="sigedge-vhf-uhf",
    label="Test",
    status_address="239.1.2.3",
    min_hz=30_000_000,
    max_hz=6_000_000_000,
    modes=("nfm",),
    kismet_host="192.0.2.10",
    kismet_port=2501,
)

NODE_NO_KISMET = SigedgeNode(
    node_id="sigedge-hf",
    label="Test HF",
    status_address="239.1.2.4",
    min_hz=1_000_000,
    max_hz=30_000_000,
    modes=("usb",),
)


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
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, data=None, cookies=None, timeout=None):
        self.calls.append({"url": url, "data": data, "cookies": cookies, "timeout": timeout})
        return FakeResponse(self.payload)


DEVICES_PAYLOAD = [
    {
        "mac": "AA:BB:CC:00:00:01",
        "phy": "IEEE802.11",
        "type": "AP",
        "manuf": "Acme",
        "signal_dbm": -40,
        "first_time": 1000,
        "last_time": 2000,
        "ssid": "coffeeshop",
    },
    {
        "mac": "AA:BB:CC:00:00:02",
        "phy": "IEEE802.11",
        "type": "client",
        "manuf": "Acme",
        "signal_dbm": -70,
        "first_time": 1500,
        "last_time": 1800,
        "ssid": "",
    },
    {
        "mac": "11:22:33:00:00:03",
        "phy": "Bluetooth",
        "type": "BR/EDR",
        "manuf": None,
        "signal_dbm": -60,
        "first_time": 500,
        "last_time": 2500,
        "ssid": "",
    },
]


class KismetClientAuthTests(unittest.TestCase):
    def test_missing_credential_raises(self):
        client = KismetClient(credentials={}, session=FakeSession([]))
        with self.assertRaisesRegex(RuntimeError, "no Kismet API key"):
            client.devices(NODE)

    def test_missing_kismet_host_raises(self):
        client = KismetClient(
            credentials={"sigedge-hf": "tok"}, session=FakeSession([])
        )
        with self.assertRaisesRegex(RuntimeError, "no kismet_host"):
            client.devices(NODE_NO_KISMET)

    def test_apikey_sent_as_kismet_cookie(self):
        session = FakeSession([])
        client = KismetClient(
            credentials={"sigedge-vhf-uhf": "secret-key"}, session=session
        )
        client.devices(NODE)
        self.assertEqual(session.calls[0]["cookies"], {"KISMET": "secret-key"})
        self.assertTrue(session.calls[0]["url"].startswith("http://192.0.2.10:2501/"))
        posted = json.loads(session.calls[0]["data"]["json"])
        self.assertIn("fields", posted)


class KismetClientDevicesTests(unittest.TestCase):
    def test_devices_passes_through_list(self):
        client = KismetClient(
            credentials={"sigedge-vhf-uhf": "tok"},
            session=FakeSession(DEVICES_PAYLOAD),
        )
        result = client.devices(NODE)
        self.assertEqual(result["node_id"], "sigedge-vhf-uhf")
        self.assertEqual(len(result["devices"]), 3)

    def test_devices_tolerates_non_list_response(self):
        client = KismetClient(
            credentials={"sigedge-vhf-uhf": "tok"}, session=FakeSession({"error": "bad"})
        )
        result = client.devices(NODE)
        self.assertEqual(result["devices"], [])


class KismetClientSummaryTests(unittest.TestCase):
    def test_summary_aggregates_counts_and_time_range(self):
        client = KismetClient(
            credentials={"sigedge-vhf-uhf": "tok"},
            session=FakeSession(DEVICES_PAYLOAD),
        )
        result = client.summary(NODE)
        self.assertEqual(result["node_id"], "sigedge-vhf-uhf")
        self.assertEqual(result["device_count"], 3)
        self.assertEqual(result["by_type"], {"AP": 1, "client": 1, "BR/EDR": 1})
        self.assertEqual(result["by_phy"], {"IEEE802.11": 2, "Bluetooth": 1})
        self.assertEqual(result["first_seen_sec"], 500)
        self.assertEqual(result["last_seen_sec"], 2500)

    def test_summary_handles_no_devices(self):
        client = KismetClient(
            credentials={"sigedge-vhf-uhf": "tok"}, session=FakeSession([])
        )
        result = client.summary(NODE)
        self.assertEqual(result["device_count"], 0)
        self.assertIsNone(result["first_seen_sec"])
        self.assertIsNone(result["last_seen_sec"])


if __name__ == "__main__":
    unittest.main()
