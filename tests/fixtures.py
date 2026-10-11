"""Shared on-disk fixtures for the tool/core tests.

Builds small kismet_bridge.db / occupancy.db files from the real schema SQL,
a SigID metadata directory, and a MAC vendor mirror, so tests exercise the
same read-only paths the tools use in production.
"""
import json
import sqlite3
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Far enough from "now" that since_minutes filters are deterministic.
RECENT = int(time.time()) - 60
OLD = 1_000_000


def make_kismet_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript((REPO / "kismet_bridge" / "kismet_bridge_schema.sql").read_text())
    rows = [
        ("sigedge-vhf", "AA:BB:CC:00:00:01", "Wi-Fi AP", "IEEE802.11", "coffeeshop", "Acme", -40, OLD, RECENT),
        ("sigedge-vhf", "AA:BB:CC:00:00:02", "Wi-Fi Client", "IEEE802.11", None, "Acme", -70, OLD, OLD + 10),
        ("sigedge-hf", "11:22:33:44:55:66", "BTLE Device", "BTLE", None, "", -80, OLD, RECENT),
        ("sigedge-hf", "A1:B2:C3", "Airplane", "ADSB", None, None, None, OLD, RECENT),
    ]
    conn.executemany(
        "INSERT INTO devices (node_id, mac, device_type, phy, ssid, manufacturer,"
        " signal_dbm, first_seen_sec, last_seen_sec) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return path


def make_occupancy_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript((REPO / "occupancy" / "occupancy_schema.sql").read_text())
    conn.executemany(
        "INSERT INTO signals (signal_key, frequency_hz, mode, first_seen_sec,"
        " last_seen_sec, total_sightings) VALUES (?,?,?,?,?,?)",
        [
            ("14074000:usb", 14074000.0, "usb", OLD, RECENT, 5),
            ("162550000:nfm", 162550000.0, "nfm", OLD, OLD + 5, 2),
        ],
    )
    conn.executemany(
        "INSERT INTO sightings (signal_key, frequency_hz, first_seen_sec, last_seen_sec,"
        " source_type, source_device, mode) VALUES (?,?,?,?,?,?,?)",
        [
            ("14074000:usb", 14074010.0, OLD, OLD + 1, "sigedge_gateway_status", "sigedge-hf", "usb"),
            ("14074000:usb", 14073990.0, RECENT, RECENT, "sigedge_gateway_status", "sigedge-hf", "usb"),
        ],
    )
    conn.commit()
    conn.close()
    return path


def make_sigid_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    pages = {
        "LoRa": (
            "{{Unidentified Signal\n|Title=LoRa\n|Frequencies=868 MHz, 915 MHz\n"
            "|Mode=CSS\n|Modulation=Chirp spread spectrum\n|Bandwidth=125 kHz\n"
            "|Location=Worldwide\n|Signal description=Low power long range IoT.\n}}"
        ),
        "10-tone signal": (
            "{{Unidentified Signal\n|Title=10-tone signal\n|Frequencies=6115 kHz\n"
            "|Mode=AM\n|Modulation=8PSK\n|Bandwidth=7 kHz\n"
            "|Location=Europe\n|Signal description=Odd military HF tone set.\n}}"
        ),
        "Old Name": "#REDIRECT [[LoRa]]",
        "Category page": "Just prose, nothing structured.",
    }
    for title, wikitext in pages.items():
        (path / f"{title}.json").write_text(json.dumps({"title": title, "wikitext": wikitext}))
    (path / "broken.json").write_text("{not json")
    return path


def make_mac_json(path: Path) -> Path:
    entries = [
        {"macPrefix": "AA:BB:CC", "vendorName": "Acme Corp", "blockType": "MA-L",
         "private": False, "lastUpdate": "2024-01-01"},
        {"macPrefix": "AA:BB:CC:D", "vendorName": "Acme Micro", "blockType": "MA-M",
         "private": False, "lastUpdate": "2024-02-01"},
        {"macPrefix": "AA:BB:CC:DD:E", "vendorName": "Acme Small", "blockType": "MA-S",
         "private": False, "lastUpdate": "2024-03-01"},
        {"macPrefix": "00:11:22", "vendorName": "", "blockType": "MA-L",
         "private": True, "lastUpdate": "2024-01-01"},
    ]
    path.write_text(json.dumps(entries))
    return path
