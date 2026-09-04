import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_status_filters_cross_node_channels_by_data_address(self):
        # Reproduces what was live-confirmed on rubberduck 2026-09-04:
        # discover_channels_native's wildcard-bound listener socket can
        # return channels belonging to a *different* radiod instance's
        # multicast group than the one requested. A node that declares its
        # own data_address must not report those as its own.
        node = SigedgeNode(
            node_id="test",
            label="Test",
            status_address="239.1.2.3",
            data_address="239.1.64.3",
            min_hz=1_000_000,
            max_hz=30_000_000,
            modes=("am", "usb"),
            control_enabled=True,
        )

        class SDK:
            @staticmethod
            def discover_channels_native(address, listen_duration):
                return {
                    7: SimpleNamespace(multicast_address="239.1.64.3", frequency=10_000_000),
                    99: SimpleNamespace(multicast_address="239.1.64.9", frequency=144_390_000),
                }

        with patch("sigedge_client.ka9q", SDK):
            result = SigedgeClient(discovery_seconds=0.25).status(node)
        self.assertTrue(result["reachable"])
        self.assertEqual(result["channel_count"], 1)
        self.assertEqual(list(result["channels"].keys()), ["7"])

    def test_status_without_data_address_keeps_legacy_unfiltered_behavior(self):
        class SDK:
            @staticmethod
            def discover_channels_native(address, listen_duration):
                return {
                    7: SimpleNamespace(multicast_address="239.1.64.3", frequency=10_000_000),
                    99: SimpleNamespace(multicast_address="239.1.64.9", frequency=144_390_000),
                }

        with patch("sigedge_client.ka9q", SDK):
            result = SigedgeClient(discovery_seconds=0.25).status(NODE)
        self.assertEqual(result["channel_count"], 2)


if __name__ == "__main__":
    unittest.main()

