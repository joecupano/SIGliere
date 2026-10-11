"""Static guards on the MCP deployment files (no podman or MCP SDK needed)."""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
QUADLET = (REPO / "containers" / "sigliere-mcp.container").read_text()
INSTALL_WEBUI = (REPO / "scripts" / "install-open-webui.sh").read_text()
INSTALL_MCP = (REPO / "scripts" / "install-sigliere-mcp.sh").read_text()
CONTAINERFILE = (REPO / "mcp_server" / "Containerfile").read_text()


def lines(key):
    return re.findall(rf"^{key}=(.*)$", QUADLET, re.M)


class QuadletTests(unittest.TestCase):
    def test_every_volume_is_read_only(self):
        vols = lines("Volume")
        self.assertTrue(vols)
        for v in vols:
            self.assertTrue(v.endswith(":ro"), v)

    def test_only_expected_data_is_mounted(self):
        sources = {v.split(":")[0] for v in lines("Volume")}
        self.assertEqual(sources, {"/data/kismet-bridge", "/data/occupancy",
                                   "/data/reference/sigid", "/data/reference/mac-vendors"})

    def test_no_audio_collection_or_state_mounts(self):
        for forbidden in ("/data/audio", "open-webui-state", "/data/corpus", "/data/models"):
            self.assertNotIn(forbidden, QUADLET)

    def test_hardening_flags(self):
        self.assertEqual(lines("ReadOnly"), ["true"])
        self.assertEqual(lines("NoNewPrivileges"), ["true"])
        self.assertEqual(lines("DropCapability"), ["ALL"])

    def test_never_publishes_ports_or_loads_gateway_credentials(self):
        self.assertFalse(lines("PublishPort"))
        self.assertEqual(lines("EnvironmentFile"), ["%h/.config/sigliere/mcp.env"])
        self.assertNotIn("gateway.env", QUADLET.replace("never gateway.env", ""))

    def test_image_is_local(self):
        self.assertEqual(lines("Image"), ["localhost/sigliere-mcp:latest"])


class CaddyRouteTests(unittest.TestCase):
    def test_mcp_route_on_private_router_only(self):
        private = INSTALL_WEBUI.split("http://127.0.0.1:8180 {", 1)[1]
        self.assertIn("@mcp path /mcp /mcp/*", private)
        self.assertIn("reverse_proxy 127.0.0.1:8150", private)
        self.assertIn("flush_interval -1", private)
        # the LAN-facing site block (before the private one) must not proxy it
        public = INSTALL_WEBUI.split("http://127.0.0.1:8180 {", 1)[0]
        self.assertNotIn("8150", public)
        self.assertNotIn("/mcp", public)


class InstallerTests(unittest.TestCase):
    def test_token_file_has_only_mcp_settings(self):
        self.assertIn("SIGLIERE_MCP_TOKEN", INSTALL_MCP)
        self.assertNotIn("gateway.env", INSTALL_MCP)
        self.assertNotIn("TOKENS_JSON", INSTALL_MCP)

    def test_env_file_is_private_and_preserved(self):
        self.assertIn("chmod 0600", INSTALL_MCP)
        self.assertIn("umask 077", INSTALL_MCP)
        self.assertIn("Preserving existing MCP token", INSTALL_MCP)

    def test_refuses_root(self):
        self.assertIn('"$(id -u)" -eq 0', INSTALL_MCP)


class ImageTests(unittest.TestCase):
    def test_sdk_pinned_and_only_core_copied(self):
        self.assertIn("mcp==1.27.2", (REPO / "mcp_server" / "requirements.txt").read_text())
        copies = re.findall(r"^COPY (\S+)", CONTAINERFILE, re.M)
        self.assertEqual(sorted(copies), ["mcp_server/requirements.txt",
                                          "mcp_server/src/sigliere_mcp", "sigliere_core"])
        self.assertIn("SIGLIERE_MCP_HOST=127.0.0.1", CONTAINERFILE)


if __name__ == "__main__":
    unittest.main()
