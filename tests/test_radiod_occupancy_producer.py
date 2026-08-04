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


def test_prefers_non_loopback_interface_address(monkeypatch):
    monkeypatch.delenv("RADIOD_MULTICAST_IFACE", raising=False)
    monkeypatch.setattr(MODULE.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.1.1", 0))])
    monkeypatch.setattr(MODULE.socket, "if_nameindex", lambda: [(1, "lo"), (2, "eno1")])
    monkeypatch.setattr(MODULE, "_get_interface_ipv4", lambda name: "192.168.173.65" if name == "eno1" else None)
    assert MODULE._select_multicast_iface() == "192.168.173.65"
