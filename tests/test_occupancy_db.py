import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "occupancy"))

from occupancy_db import OccupancyDB, make_signal_key


class MakeSignalKeyTests(unittest.TestCase):
    def test_bins_nearby_frequencies_together(self):
        # Within FREQUENCY_BIN_HZ (1000) of each other, same mode -> same key.
        self.assertEqual(
            make_signal_key(14_074_050, "usb"),
            make_signal_key(14_074_400, "usb"),
        )

    def test_distinct_frequencies_get_distinct_keys(self):
        self.assertNotEqual(
            make_signal_key(14_074_000, "usb"),
            make_signal_key(14_200_000, "usb"),
        )

    def test_null_mode_normalizes_to_unknown(self):
        self.assertTrue(make_signal_key(10_000_000, None).endswith(":unknown"))


class OccupancyDBTests(unittest.TestCase):
    def test_record_sighting_creates_signal_and_sighting(self):
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")

            signal_key = db.record_sighting(
                frequency_hz=14_074_000,
                source_type="sigedge_gateway_status",
                source_device="sigedge-hf",
                mode="usb",
                metadata_json='{"ssrc": 7, "snr_db": 12.5}',
            )

            signal = db.get_signal(signal_key)
            self.assertIsNotNone(signal)
            self.assertEqual(signal["total_sightings"], 1)

            sightings = db.get_sightings(signal_key)
            self.assertEqual(len(sightings), 1)
            self.assertEqual(sightings[0]["source_device"], "sigedge-hf")

    def test_repeat_sightings_aggregate_not_duplicate_signal_rows(self):
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")

            key_a = db.record_sighting(
                frequency_hz=14_074_000, source_type="sigedge_gateway_status",
                source_device="sigedge-hf", mode="usb",
            )
            key_b = db.record_sighting(
                frequency_hz=14_074_300, source_type="sigedge_gateway_status",
                source_device="sigedge-hf", mode="usb",
            )

            self.assertEqual(key_a, key_b)
            signal = db.get_signal(key_a)
            self.assertEqual(signal["total_sightings"], 2)
            self.assertEqual(len(db.get_sightings(key_a)), 2)

    def test_query_signals_filters_by_frequency_range(self):
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")
            db.record_sighting(
                frequency_hz=10_000_000, source_type="sigedge_gateway_status",
                source_device="sigedge-hf", mode="usb",
            )
            db.record_sighting(
                frequency_hz=144_390_000, source_type="sigedge_gateway_status",
                source_device="sigedge-vhf-aprs", mode="fm",
            )

            hits = db.query_signals(min_hz=140_000_000, max_hz=150_000_000)

            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["mode"], "fm")

    def test_summary_counts_distinct_source_devices(self):
        with TemporaryDirectory() as tmpdir:
            db = OccupancyDB(Path(tmpdir) / "occupancy.db")
            db.record_sighting(
                frequency_hz=10_000_000, source_type="sigedge_gateway_status",
                source_device="sigedge-hf", mode="usb",
            )
            db.record_sighting(
                frequency_hz=144_390_000, source_type="sigedge_gateway_status",
                source_device="sigedge-vhf-aprs", mode="fm",
            )

            summary = db.summary()

            self.assertEqual(summary["signal_count"], 2)
            self.assertEqual(summary["sighting_count"], 2)
            self.assertEqual(
                sorted(summary["source_devices"]), ["sigedge-hf", "sigedge-vhf-aprs"]
            )


if __name__ == "__main__":
    unittest.main()
