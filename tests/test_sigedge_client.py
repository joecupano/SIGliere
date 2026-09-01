import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway" / "src"))

from sigedge_client import SigedgeClient, SigedgeNode


NODE = SigedgeNode(
    node_id="test",
    label="Test",
    status_address="239.1.2.3",
    min_hz=1_000_000,
    max_hz=30_000_000,
    modes=("am", "usb"),
    control_enabled=True,
)


class SigedgeClientTests(unittest.TestCase):
    def test_dry_run_tune(self):
        result = SigedgeClient(dry_run=True).tune(
            NODE, frequency_hz=10_000_000, mode="am"
        )
        self.assertEqual(
            result,
            {
                "dry_run": True,
                "node_id": "test",
                "frequency_hz": 10_000_000,
                "mode": "am",
            },
        )

    def test_tune_validates_contract(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            SigedgeClient(dry_run=True).tune(
                NODE, frequency_hz=10_000_000, mode="nfm"
            )

    def test_status_uses_explicit_multicast_address(self):
        calls = []

        class SDK:
            @staticmethod
            def discover_channels_native(address, listen_duration):
                calls.append((address, listen_duration))
                return [{"ssrc": 7, "frequency": 10_000_000}]

        with patch("sigedge_client.ka9q", SDK):
            result = SigedgeClient(discovery_seconds=0.25).status(NODE)
        self.assertEqual(calls, [("239.1.2.3", 0.25)])
        self.assertTrue(result["reachable"])
        self.assertEqual(result["channel_count"], 1)


if __name__ == "__main__":
    unittest.main()

