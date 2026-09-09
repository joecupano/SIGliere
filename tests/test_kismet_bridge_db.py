import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kismet_bridge"))

from kismet_bridge_db import KismetBridgeDB


class KismetBridgeDBTests(unittest.TestCase):
    def test_upsert_creates_new_device(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            db.upsert_device(
                node_id="sigedge-vhf-uhf", mac="AA:BB:CC:00:00:01",
                device_type="AP", phy="IEEE802.11", ssid="coffeeshop",
                manufacturer="Acme", signal_dbm=-40,
                first_seen_sec=1000, last_seen_sec=2000,
            )
            device = db.get_device("sigedge-vhf-uhf", "AA:BB:CC:00:00:01")
            self.assertIsNotNone(device)
            self.assertEqual(device["total_polls"], 1)
            self.assertEqual(device["ssid"], "coffeeshop")

    def test_repeat_upsert_bumps_polls_not_duplicate_rows(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            db.upsert_device(
                node_id="sigedge-vhf-uhf", mac="AA:BB:CC:00:00:01",
                device_type="AP", signal_dbm=-40,
                first_seen_sec=1000, last_seen_sec=2000,
            )
            db.upsert_device(
                node_id="sigedge-vhf-uhf", mac="AA:BB:CC:00:00:01",
                device_type="AP", signal_dbm=-35,
                first_seen_sec=1000, last_seen_sec=3000,
            )
            device = db.get_device("sigedge-vhf-uhf", "AA:BB:CC:00:00:01")
            self.assertEqual(device["total_polls"], 2)
            self.assertEqual(device["last_seen_sec"], 3000)
            self.assertEqual(device["signal_dbm"], -35)

            devices = db.query_devices(mac="AA:BB:CC:00:00:01")
            self.assertEqual(len(devices), 1)

    def test_same_mac_different_nodes_are_distinct_rows(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            db.upsert_device(
                node_id="sigedge-vhf-uhf", mac="AA:BB:CC:00:00:01",
                first_seen_sec=1000, last_seen_sec=2000,
            )
            db.upsert_device(
                node_id="sigedge-hf", mac="AA:BB:CC:00:00:01",
                first_seen_sec=1500, last_seen_sec=2500,
            )
            devices = db.query_devices(mac="AA:BB:CC:00:00:01")
            self.assertEqual(len(devices), 2)

    def test_query_devices_filters_by_ssid(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            db.upsert_device(
                node_id="sigedge-vhf-uhf", mac="AA:BB:CC:00:00:01",
                ssid="coffeeshop", first_seen_sec=1000, last_seen_sec=2000,
            )
            db.upsert_device(
                node_id="sigedge-vhf-uhf", mac="AA:BB:CC:00:00:02",
                ssid="homewifi", first_seen_sec=1000, last_seen_sec=2000,
            )
            hits = db.query_devices(ssid="coffee")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["mac"], "AA:BB:CC:00:00:01")

    def test_summary_counts_by_type_and_phy(self):
        with TemporaryDirectory() as tmpdir:
            db = KismetBridgeDB(Path(tmpdir) / "kismet_bridge.db")
            db.upsert_device(
                node_id="sigedge-vhf-uhf", mac="AA:BB:CC:00:00:01",
                device_type="AP", phy="IEEE802.11",
                first_seen_sec=1000, last_seen_sec=2000,
            )
            db.upsert_device(
                node_id="sigedge-vhf-uhf", mac="11:22:33:00:00:02",
                device_type="BR/EDR", phy="Bluetooth",
                first_seen_sec=500, last_seen_sec=2500,
            )
            summary = db.summary()
            self.assertEqual(summary["device_count"], 2)
            self.assertEqual(summary["by_type"], {"AP": 1, "BR/EDR": 1})
            self.assertEqual(summary["by_phy"], {"IEEE802.11": 1, "Bluetooth": 1})
            self.assertEqual(summary["first_seen_sec"], 500)
            self.assertEqual(summary["last_seen_sec"], 2500)
            self.assertEqual(summary["nodes"], ["sigedge-vhf-uhf"])


if __name__ == "__main__":
    unittest.main()
