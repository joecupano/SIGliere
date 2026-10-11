"""Tests for the SIGliere MCP server (mcp_server/): config, auth, tools, parity."""
import contextlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "mcp_server" / "src"))
sys.path.insert(0, str(REPO / "tests"))

import fixtures

try:
    import httpx
    from mcp.shared.memory import create_connected_server_and_client_session
    from sigliere_mcp.auth import BearerAuth
    from sigliere_mcp.config import Config, ConfigError
    from sigliere_mcp.server import build_app, create_server
    HAVE_MCP = True
except ImportError:  # the mcp SDK is only in the MCP image / Open WebUI image
    HAVE_MCP = False

try:
    import pydantic  # noqa: F401
    HAVE_PYDANTIC = True
except ImportError:
    HAVE_PYDANTIC = False

TOKEN = "t" * 40
EXPECTED_TOOLS = {
    "query_wifi_devices", "kismet_summary",
    "query_occupancy", "occupancy_sightings", "occupancy_summary",
    "lookup_signal", "search_signals",
    "lookup_mac_vendor", "search_mac_vendors",
}


@unittest.skipUnless(HAVE_MCP, "mcp SDK / httpx not installed")
class McpTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = Path(self._tmp.name)
        self.cfg = Config(
            token=TOKEN,
            kismet_db=str(fixtures.make_kismet_db(d / "k.db")),
            occupancy_db=str(fixtures.make_occupancy_db(d / "o.db")),
            sigid_dir=str(fixtures.make_sigid_dir(d / "sigid")),
            mac_db=str(fixtures.make_mac_json(d / "mac.json")),
        )
        self.missing = str(d / "missing")

    async def call(self, name, args=None, cfg=None):
        server = create_server(cfg or self.cfg)
        async with create_connected_server_and_client_session(server._mcp_server) as c:
            return await c.call_tool(name, args or {})

    @staticmethod
    def text(result):
        assert len(result.content) == 1, result
        return result.content[0].text


class ConfigTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_MCP, "mcp SDK not installed")
    def test_token_required_and_long_enough(self):
        with self.assertRaises(ConfigError):
            Config.from_env({})
        with self.assertRaises(ConfigError):
            Config.from_env({"SIGLIERE_MCP_TOKEN": "short"})

    @unittest.skipUnless(HAVE_MCP, "mcp SDK not installed")
    def test_refuses_non_loopback_bind(self):
        for host in ("0.0.0.0", "192.168.1.5", "::"):
            with self.assertRaises(ConfigError):
                Config.from_env({"SIGLIERE_MCP_TOKEN": TOKEN, "SIGLIERE_MCP_HOST": host})

    @unittest.skipUnless(HAVE_MCP, "mcp SDK not installed")
    def test_defaults_and_overrides(self):
        c = Config.from_env({"SIGLIERE_MCP_TOKEN": TOKEN})
        self.assertEqual((c.host, c.port), ("127.0.0.1", 8150))
        self.assertEqual(c.kismet_db, "/data/kismet-bridge-ref/kismet_bridge.db")
        c = Config.from_env({"SIGLIERE_MCP_TOKEN": TOKEN, "SIGLIERE_MCP_PORT": "9000",
                             "MAC_VENDOR_DB_PATH": "/x.json",
                             "SIGLIERE_MCP_ALLOWED_HOSTS": "a:1, b:2"})
        self.assertEqual((c.port, c.mac_db, c.allowed_hosts), (9000, "/x.json", ("a:1", "b:2")))

    @unittest.skipUnless(HAVE_MCP, "mcp SDK not installed")
    def test_token_not_in_repr(self):
        self.assertNotIn(TOKEN, repr(Config(token=TOKEN)))


class ToolSurfaceTests(McpTestCase):
    async def test_exact_tool_set_all_read_only(self):
        server = create_server(self.cfg)
        async with create_connected_server_and_client_session(server._mcp_server) as c:
            tools = (await c.list_tools()).tools
        self.assertEqual({t.name for t in tools}, EXPECTED_TOOLS)
        for t in tools:
            self.assertTrue(t.annotations.readOnlyHint, t.name)
            self.assertFalse(t.annotations.destructiveHint, t.name)
            self.assertTrue(t.description and len(t.description) > 40, t.name)

    async def test_parameters_are_described_for_the_model(self):
        server = create_server(self.cfg)
        async with create_connected_server_and_client_session(server._mcp_server) as c:
            tool = next(t for t in (await c.list_tools()).tools if t.name == "query_wifi_devices")
        props = tool.inputSchema["properties"]
        for p in ("mac", "ssid", "device_type", "phy", "node_id", "since_minutes", "include_adsb"):
            self.assertIn("description", props[p], p)

    async def test_results_are_text_only_not_doubled_as_structured(self):
        r = await self.call("kismet_summary")
        self.assertFalse(r.isError)
        self.assertIsNone(r.structuredContent)
        self.assertEqual(len(r.content), 1)


class KismetToolTests(McpTestCase):
    async def test_default_excludes_adsb_and_is_compact(self):
        txt = self.text(await self.call("query_wifi_devices"))
        data = json.loads(txt)
        self.assertEqual(data["count"], 3)
        self.assertNotIn("A1:B2:C3", txt)
        self.assertNotIn(": ", txt)  # compact separators

    async def test_filters(self):
        data = json.loads(self.text(await self.call("query_wifi_devices", {"device_type": "ap"})))
        self.assertEqual([d["mac"] for d in data["devices"]], ["AA:BB:CC:00:00:01"])
        data = json.loads(self.text(await self.call("query_wifi_devices", {"phy": "ADSB"})))
        self.assertEqual(data["count"], 1)

    async def test_no_match_is_a_normal_result(self):
        r = await self.call("query_wifi_devices", {"mac": "ZZ"})
        self.assertFalse(r.isError)
        self.assertIn("No devices matched", self.text(r))

    async def test_summary(self):
        data = json.loads(self.text(await self.call("kismet_summary")))
        self.assertEqual((data["device_count"], data["adsb_count"]), (4, 1))

    async def test_missing_database_is_a_protocol_error(self):
        from dataclasses import replace
        r = await self.call("query_wifi_devices", cfg=replace(self.cfg, kismet_db=self.missing))
        self.assertTrue(r.isError)
        self.assertIn("Error reading kismet bridge database", self.text(r))


class OccupancyToolTests(McpTestCase):
    async def test_query_sightings_summary(self):
        data = json.loads(self.text(await self.call("query_occupancy", {"near_frequency_hz": 14074000})))
        self.assertEqual(data["signals"][0]["signal_key"], "14074000:usb")
        data = json.loads(self.text(await self.call("occupancy_sightings", {"signal_key": "14074000:usb"})))
        self.assertEqual(data["count"], 2)
        self.assertEqual(json.loads(self.text(await self.call("occupancy_summary")))["signal_count"], 2)

    async def test_blank_signal_key_and_unknown_key(self):
        self.assertIn("provide a signal_key", self.text(await self.call("occupancy_sightings", {"signal_key": " "})))
        self.assertIn("No sightings found", self.text(await self.call("occupancy_sightings", {"signal_key": "nope"})))


class SigidToolTests(McpTestCase):
    async def test_lookup_and_search(self):
        data = json.loads(self.text(await self.call("lookup_signal", {"name": "lora"})))
        self.assertEqual(data["signals"][0]["title"], "LoRa")
        data = json.loads(self.text(await self.call("search_signals", {"keyword": "8psk"})))
        self.assertEqual(data["signals"][0]["title"], "10-tone signal")
        self.assertIn("2 catalog entries searched", self.text(await self.call("lookup_signal", {"name": "zzz"})))


class MacToolTests(McpTestCase):
    async def test_longest_prefix_and_search(self):
        data = json.loads(self.text(await self.call("lookup_mac_vendor", {"mac_address": "AA:BB:CC:DD:EE:FF"})))
        self.assertEqual(data["match"]["vendor"], "Acme Small")
        self.assertEqual(data["match"]["prefix_bits"], 36)
        data = json.loads(self.text(await self.call("search_mac_vendors", {"vendor_name": "acme"})))
        self.assertEqual(data["total_matches"], 3)

    async def test_short_input_and_missing_db(self):
        from dataclasses import replace
        self.assertIn("at least 6 hex digits", self.text(await self.call("lookup_mac_vendor", {"mac_address": "AA:BB"})))
        r = await self.call("lookup_mac_vendor", {"mac_address": "AA:BB:CC"}, cfg=replace(self.cfg, mac_db=self.missing))
        self.assertTrue(r.isError)


class HttpAuthTests(McpTestCase):
    """The real HTTP path: bearer gate, host validation, JSON-RPC over POST."""
    HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"}}}

    @contextlib.asynccontextmanager
    async def served(self):
        """Run the app's lifespan (the MCP session manager's task group must
        start and stop in the same task, so this wraps each test body)."""
        inner = create_server(self.cfg).streamable_http_app()
        async with inner.router.lifespan_context(inner):
            transport = httpx.ASGITransport(app=BearerAuth(inner, TOKEN))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8150") as client:
                yield client

    @staticmethod
    async def post(client, body, token=TOKEN, extra=None):
        headers = dict(HttpAuthTests.HEADERS, **(extra or {}))
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return await client.post("/", json=body, headers=headers)

    async def test_missing_and_wrong_token_rejected_before_mcp(self):
        async with self.served() as c:
            for token in (None, "wrong", TOKEN[:-1], TOKEN + "x", ""):
                r = await self.post(c, self.INIT, token=token)
                self.assertEqual(r.status_code, 401, token)
                self.assertEqual(r.headers["www-authenticate"], "Bearer")
                self.assertNotIn(TOKEN, r.text)

    async def test_non_bearer_scheme_rejected(self):
        async with self.served() as c:
            r = await c.post("/", json=self.INIT, headers=dict(self.HEADERS, Authorization=f"Basic {TOKEN}"))
            self.assertEqual(r.status_code, 401)

    async def test_valid_token_initialize_and_list_and_call(self):
        async with self.served() as c:
            r = await self.post(c, self.INIT)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["result"]["serverInfo"]["name"], "sigliere")
            r = await self.post(c, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            self.assertEqual({t["name"] for t in r.json()["result"]["tools"]}, EXPECTED_TOOLS)
            r = await self.post(c, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                    "params": {"name": "kismet_summary", "arguments": {}}})
            self.assertFalse(r.json()["result"]["isError"])

    async def test_unexpected_host_header_rejected(self):
        async with self.served() as c:
            for host in ("evil.example", "192.168.1.9:8150"):
                r = await self.post(c, self.INIT, extra={"Host": host})
                self.assertIn(r.status_code, (400, 421), host)

    async def test_caddy_forwarded_host_accepted(self):
        async with self.served() as c:
            r = await self.post(c, self.INIT, extra={"Host": "127.0.0.1:8180"})
            self.assertEqual(r.status_code, 200, r.text)

    def test_empty_token_cannot_build_gate(self):
        with self.assertRaises(ValueError):
            BearerAuth(lambda *a: None, "")


@unittest.skipUnless(HAVE_MCP and HAVE_PYDANTIC, "needs mcp SDK and pydantic")
class NativeParityTests(McpTestCase):
    """MCP results must match the native Open WebUI tools on the same data."""

    def native(self, name):
        spec = importlib.util.spec_from_file_location(f"nat_{name}", REPO / "openwebui-tools" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.Tools()

    async def same(self, mcp_name, native_fn, args):
        mcp_out = self.text(await self.call(mcp_name, args))
        nat_out = native_fn(**args)
        try:
            self.assertEqual(json.loads(mcp_out), json.loads(nat_out), mcp_name)
        except json.JSONDecodeError:
            self.assertEqual(mcp_out, nat_out, mcp_name)  # prose results are identical text

    async def test_parity(self):
        k = self.native("kismet_tool"); k.valves.KISMET_BRIDGE_DB_PATH = self.cfg.kismet_db
        for args in ({}, {"mac": "AA:BB"}, {"device_type": "ap"}, {"phy": "ADSB"}, {"include_adsb": True},
                     {"since_minutes": 5}, {"mac": "ZZ"}):
            await self.same("query_wifi_devices", k.query_wifi_devices, args)
        await self.same("kismet_summary", k.kismet_summary, {})
        o = self.native("occupancy_tool"); o.valves.OCCUPANCY_DB_PATH = self.cfg.occupancy_db
        for args in ({}, {"near_frequency_hz": 14074000}, {"mode": "nfm"}, {"since_minutes": 5}):
            await self.same("query_occupancy", o.query_occupancy, args)
        await self.same("occupancy_sightings", o.occupancy_sightings, {"signal_key": "14074000:usb"})
        await self.same("occupancy_sightings", o.occupancy_sightings, {"signal_key": "nope"})
        await self.same("occupancy_summary", o.occupancy_summary, {})
        s = self.native("sigid_reference_tool"); s.valves.SIGID_METADATA_DIR = self.cfg.sigid_dir
        for n in ("lora", "tone", "zzz"):
            await self.same("lookup_signal", s.lookup_signal, {"name": n})
        for args in ({"keyword": "8psk"}, {"near_frequency_hz": 6115000}, {"keyword": "nothing"}):
            await self.same("search_signals", s.search_signals, args)
        m = self.native("mac_lookup_tool"); m.valves.MAC_VENDOR_DB_PATH = self.cfg.mac_db
        for q in ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-d1-22-33", "AA:BB:CC", "00:11:22:33:44:55", "FF:FF:FF", "AA:BB"):
            await self.same("lookup_mac_vendor", m.lookup_mac_vendor, {"mac_address": q})
        for q in ("acme", "nope"):
            await self.same("search_mac_vendors", m.search_mac_vendors, {"vendor_name": q})


if __name__ == "__main__":
    unittest.main()
