import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "decode" / "radiod_occupancy_producer.py"
SPEC = importlib.util.spec_from_file_location("radiod_occupancy_producer", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_selects_explicit_multicast_iface(monkeypatch):
    monkeypatch.setenv("RADIOD_MULTICAST_IFACE", "192.0.2.10")
    assert MODULE._select_multicast_iface() == "192.0.2.10"


def test_falls_back_to_loopback_when_no_interface_candidates(monkeypatch):
    monkeypatch.delenv("RADIOD_MULTICAST_IFACE", raising=False)
    monkeypatch.setattr(MODULE.socket, "getaddrinfo", lambda *args, **kwargs: [])
    assert MODULE._select_multicast_iface() == "127.0.0.1"
