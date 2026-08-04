import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reference"))

from sigid_manifest import SigidManifest


class SigidManifestTests(unittest.TestCase):
    def test_last_successful_run_time_falls_back_to_latest_page_sync(self):
        with TemporaryDirectory() as tmpdir:
            manifest = SigidManifest(Path(tmpdir) / "manifest.db")
            manifest.record_page_synced("Example Page", 42)

            last_run = manifest.last_successful_run_time()

            self.assertIsNotNone(last_run)


if __name__ == "__main__":
    unittest.main()
