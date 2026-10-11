"""Unit tests for sigliere_core (stdlib only, no Open WebUI or pydantic)."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import fixtures
from sigliere_core import kismet, mac, occupancy, sigid
from sigliere_core.sqlite_ro import connect_ro


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)


class SqliteRoTests(TempDirCase):
    def test_missing_file_raises_with_path(self):
        with self.assertRaisesRegex(FileNotFoundError, "nope.db does not exist"):
            connect_ro(self.dir / "nope.db")

    def test_connection_is_read_only(self):
        conn = connect_ro(fixtures.make_kismet_db(self.dir / "k.db"))
        with self.assertRaises(Exception):
            conn.execute("DELETE FROM devices")
        conn.close()


class KismetTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.conn = connect_ro(fixtures.make_kismet_db(self.dir / "k.db"))
        self.addCleanup(self.conn.close)

    def macs(self, **kw):
        return {d["mac"] for d in kismet.query_devices(self.conn, **kw)}

    def test_adsb_excluded_by_default(self):
        self.assertNotIn("A1:B2:C3", self.macs())

    def test_adsb_opt_in_by_flag_phy_or_device_type(self):
        self.assertIn("A1:B2:C3", self.macs(include_adsb=True))
        self.assertIn("A1:B2:C3", self.macs(phy="ADSB"))
        self.assertIn("A1:B2:C3", self.macs(device_type="Airplane"))

    def test_device_type_shorthand_and_case(self):
        self.assertEqual(self.macs(device_type="ap"), {"AA:BB:CC:00:00:01"})
        self.assertEqual(self.macs(device_type="CLIENT"), {"AA:BB:CC:00:00:02"})

    def test_filters(self):
        self.assertEqual(self.macs(ssid="coffee"), {"AA:BB:CC:00:00:01"})
        self.assertEqual(self.macs(node_id="sigedge-hf"), {"11:22:33:44:55:66"})
        self.assertEqual(self.macs(mac="ZZ"), set())

    def test_since_minutes_uses_last_seen(self):
        self.assertNotIn("AA:BB:CC:00:00:02", self.macs(since_minutes=5))
        self.assertIn("AA:BB:CC:00:00:01", self.macs(since_minutes=5))

    def test_slim_drops_empty_fields_and_renders_iso_times(self):
        row = next(d for d in kismet.query_devices(self.conn, mac="11:22"))
        self.assertNotIn("ssid", row)
        self.assertNotIn("manufacturer", row)  # "" is dropped
        self.assertRegex(row["last_seen"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_summary_separates_adsb(self):
        s = kismet.summarize_devices(self.conn)
        self.assertEqual((s["device_count"], s["adsb_count"], s["non_adsb_count"]), (4, 1, 3))
        self.assertEqual(s["nodes"], ["sigedge-hf", "sigedge-vhf"])

    def test_iso_none(self):
        self.assertIsNone(kismet.iso(None))


class OccupancyTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.conn = connect_ro(fixtures.make_occupancy_db(self.dir / "o.db"))
        self.addCleanup(self.conn.close)

    def keys(self, **kw):
        return [s["signal_key"] for s in occupancy.query_signals(self.conn, **kw)]

    def test_frequency_window_default_and_custom_tolerance(self):
        self.assertEqual(self.keys(near_frequency_hz=14074000), ["14074000:usb"])
        self.assertEqual(self.keys(near_frequency_hz=14068000), [])  # 6 kHz > default 5 kHz
        self.assertEqual(self.keys(near_frequency_hz=14068000, tolerance_hz=10000), ["14074000:usb"])

    def test_mode_and_since(self):
        self.assertEqual(self.keys(mode="nfm"), ["162550000:nfm"])
        self.assertEqual(self.keys(since_minutes=5), ["14074000:usb"])

    def test_sightings_oldest_first(self):
        rows = occupancy.list_sightings(self.conn, "14074000:usb")
        self.assertEqual(len(rows), 2)
        self.assertLess(rows[0]["first_seen_sec"], rows[1]["first_seen_sec"])
        self.assertEqual(occupancy.list_sightings(self.conn, "nope"), [])

    def test_summary(self):
        s = occupancy.summarize_occupancy(self.conn)
        self.assertEqual((s["signal_count"], s["sighting_count"]), (2, 2))
        self.assertEqual(s["source_devices"], ["sigedge-hf"])


class SigidTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.signals = sigid.sigid_load_signals(str(fixtures.make_sigid_dir(self.dir / "s")))

    def titles(self, signals):
        return [s["title"] for s in signals]

    def test_redirects_nonsignal_pages_and_bad_json_are_skipped(self):
        self.assertEqual(sorted(self.titles(self.signals)), ["10-tone signal", "LoRa"])

    def test_infobox_parsing_strips_wiki_markup(self):
        f = sigid.sigid_parse_infobox("{{Signal\n|Mode=[[AM|amplitude]]\n|Modulation='''8PSK'''\n}}")
        self.assertEqual(f, {"Mode": "AM", "Modulation": "8PSK"})

    def test_frequency_units(self):
        self.assertEqual(
            sigid.sigid_extract_freqs_hz("6115 kHz, 14.074 MHz, 1.2 GHz, 1,500 Hz"),
            [6115e3, 14.074e6, 1.2e9, 1500.0],
        )
        self.assertEqual(sigid.sigid_extract_freqs_hz(""), [])

    def test_find_by_name_exact_before_partial(self):
        self.assertEqual(self.titles(sigid.sigid_find_by_name(self.signals, " lora ")), ["LoRa"])
        self.assertEqual(sigid.sigid_find_by_name(self.signals, "zzz"), [])

    def test_search_keyword_and_frequency(self):
        self.assertEqual(self.titles(sigid.sigid_search(self.signals, keyword="8psk")), ["10-tone signal"])
        self.assertEqual(self.titles(sigid.sigid_search(self.signals, near_frequency_hz=6115000)), ["10-tone signal"])
        self.assertEqual(sigid.sigid_search(self.signals, near_frequency_hz=867e6, tolerance_hz=1), [])
        self.assertEqual(self.titles(sigid.sigid_search(self.signals, near_frequency_hz=868e6, tolerance_hz=1)), ["LoRa"])
        self.assertEqual(self.titles(sigid.sigid_search(self.signals, keyword="chirp", near_frequency_hz=915e6)), ["LoRa"])


class MacTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.by_len = mac.mac_load_index(str(fixtures.make_mac_json(self.dir / "m.json")))

    def vendor(self, text):
        found = mac.mac_lookup_prefix(self.by_len, mac.mac_normalize_hex(text))
        return found and (found[0]["vendorName"], found[1])

    def test_normalize_accepts_any_separator(self):
        for s in ("aa:bb:cc", "AA-BB-CC", "aabb.cc", "aabbcc"):
            self.assertEqual(mac.mac_normalize_hex(s), "AABBCC")

    def test_longest_prefix_wins(self):
        self.assertEqual(self.vendor("AA:BB:CC:DD:EE:FF"), ("Acme Small", 9))
        self.assertEqual(self.vendor("AA:BB:CC:D1:22:33"), ("Acme Micro", 7))
        self.assertEqual(self.vendor("AA:BB:CC:00:00:00"), ("Acme Corp", 6))

    def test_miss(self):
        self.assertIsNone(self.vendor("FF:FF:FF"))

    def test_private_block_has_placeholder_vendor(self):
        entry, n = mac.mac_lookup_prefix(self.by_len, "001122")
        out = mac.mac_format_entry(entry, n)
        self.assertTrue(out["private"])
        self.assertIn("private assignment", out["vendor"])
        self.assertEqual(out["prefix_bits"], 24)

    def test_vendor_search(self):
        self.assertEqual(len(mac.mac_search_vendors(self.by_len, "acme")), 3)
        self.assertEqual(mac.mac_search_vendors(self.by_len, "nope"), [])

    def test_index_cache_reloads_when_file_changes(self):
        path = self.dir / "m.json"
        first = mac.mac_load_index(str(path))
        self.assertIs(first, mac.mac_load_index(str(path)))
        path.write_text("[]")
        self.assertEqual(mac.mac_load_index(str(path))["all"], [])

    def test_non_array_json_rejected(self):
        bad = self.dir / "bad.json"
        bad.write_text("{}")
        with self.assertRaises(ValueError):
            mac.mac_load_index(str(bad))


if __name__ == "__main__":
    unittest.main()
