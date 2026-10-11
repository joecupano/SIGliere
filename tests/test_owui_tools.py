"""The generated, self-contained Open WebUI tools: freshness, isolation, behavior."""
import ast
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

import fixtures

try:
    import pydantic  # noqa: F401
    HAVE_PYDANTIC = True
except ImportError:  # pydantic lives in the Open WebUI container, not the host
    HAVE_PYDANTIC = False

TOOLS = ["kismet_tool", "occupancy_tool", "sigid_reference_tool", "mac_lookup_tool"]
OUT = REPO / "openwebui-tools"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_owui_tools", REPO / "scripts" / "build-owui-tools.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GeneratedToolTests(unittest.TestCase):
    def test_generated_tools_are_up_to_date(self):
        builder = load_builder()
        for name in TOOLS:
            built = builder.build(builder.SRC_DIR / f"{name}.py")
            self.assertEqual((OUT / f"{name}.py").read_text(), built,
                             f"{name}.py is stale: run scripts/build-owui-tools.py")

    def test_every_source_wrapper_is_covered(self):
        self.assertEqual(sorted(p.stem for p in (OUT / "src").glob("*.py")), sorted(TOOLS))

    def test_generated_tools_do_not_import_the_repo(self):
        # Open WebUI has no repo checkout: any sigliere_core import would fail there.
        for name in TOOLS:
            tree = ast.parse((OUT / f"{name}.py").read_text())
            for node in ast.walk(tree):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for m in mods:
                    self.assertFalse(m.startswith("sigliere_core"), f"{name} imports {m}")

    def test_docstring_frontmatter_is_first(self):
        for name in TOOLS:
            text = (OUT / f"{name}.py").read_text()
            self.assertTrue(text.startswith('"""\ntitle: '), name)


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed (it is in the Open WebUI image)")
class GeneratedToolBehaviorTests(unittest.TestCase):
    """Run the generated files exactly as Open WebUI would: no repo on sys.path."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        cls.kdb = fixtures.make_kismet_db(d / "k.db")
        cls.odb = fixtures.make_occupancy_db(d / "o.db")
        cls.sig = fixtures.make_sigid_dir(d / "sigid")
        cls.mac = fixtures.make_mac_json(d / "mac.json")
        cls.missing = d / "missing"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @staticmethod
    def tool(name):
        spec = importlib.util.spec_from_file_location(f"gen_{name}", OUT / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.Tools()

    def test_kismet(self):
        t = self.tool("kismet_tool")
        t.valves.KISMET_BRIDGE_DB_PATH = str(self.kdb)
        self.assertIn('"count":3', t.query_wifi_devices())
        self.assertIn("adsb_count", t.kismet_summary())
        self.assertIn("No devices matched", t.query_wifi_devices(mac="ZZ"))
        t.valves.KISMET_BRIDGE_DB_PATH = str(self.missing)
        self.assertIn("Error reading kismet bridge database", t.query_wifi_devices())

    def test_occupancy(self):
        t = self.tool("occupancy_tool")
        t.valves.OCCUPANCY_DB_PATH = str(self.odb)
        self.assertIn("14074000:usb", t.query_occupancy(near_frequency_hz=14074000))
        self.assertIn('"count": 2', t.occupancy_sightings("14074000:usb"))
        self.assertIn("provide a signal_key", t.occupancy_sightings(" "))
        self.assertIn("signal_count", t.occupancy_summary())

    def test_sigid(self):
        t = self.tool("sigid_reference_tool")
        t.valves.SIGID_METADATA_DIR = str(self.sig)
        self.assertIn("Chirp spread spectrum", t.lookup_signal("lora"))
        self.assertIn("2 catalog entries searched", t.lookup_signal("zzz"))
        self.assertIn("10-tone signal", t.search_signals(keyword="8psk"))

    def test_mac(self):
        t = self.tool("mac_lookup_tool")
        t.valves.MAC_VENDOR_DB_PATH = str(self.mac)
        self.assertIn("Acme Small", t.lookup_mac_vendor("AA:BB:CC:DD:EE:FF"))
        self.assertIn("need at least 6 hex digits", t.lookup_mac_vendor("AA:BB"))
        self.assertIn('"total_matches": 3', t.search_mac_vendors("acme"))
        t.valves.MAC_VENDOR_DB_PATH = str(self.missing)
        self.assertIn("No MAC vendor database", t.lookup_mac_vendor("AA:BB:CC"))


if __name__ == "__main__":
    unittest.main()
