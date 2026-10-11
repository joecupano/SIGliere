"""Static guards for readiness and hostname handling in the install scripts."""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALL = (REPO / "scripts" / "install-open-webui.sh").read_text()
TIERED = (REPO / "scripts" / "validate-tiered.sh").read_text()


class ReadinessTests(unittest.TestCase):
    def test_waits_for_the_backend_before_declaring_ready(self):
        backend = INSTALL.index("http://127.0.0.1:8080/api/version")
        caddy_probe = INSTALL.index("PROBE=(")
        self.assertLess(backend, caddy_probe)

    def test_backend_wait_fails_the_install_on_timeout(self):
        self.assertRegex(INSTALL, r'backend_ready.*\n(?:.*\n)*?.*exit 1')

    def test_probes_fail_on_http_errors(self):
        # Caddy answers 502 while the backend starts; without -f, curl exits 0.
        for line in re.findall(r"PROBE=\((.*)\)", INSTALL):
            self.assertRegex(line, r"curl -\w*f\w*\b", line)
        self.assertRegex(INSTALL, r"curl -fsS http://127\.0\.0\.1:8080/api/version")


class HostnameTests(unittest.TestCase):
    def test_validator_reads_the_hostname_back_from_the_installed_caddyfile(self):
        self.assertIn("containers/systemd/Caddyfile", TIERED)
        self.assertIn(":8443 {", TIERED)
        # an explicit SIGLIERE_HOSTNAME still wins
        self.assertRegex(TIERED, r'-z "\$\{SIGLIERE_HOSTNAME:-\}"')

    def test_falls_back_to_the_old_default_only_when_nothing_is_known(self):
        self.assertIn('HOSTNAME_TLS="${SIGLIERE_HOSTNAME:-$(hostname -s).local}"', TIERED)


if __name__ == "__main__":
    unittest.main()
