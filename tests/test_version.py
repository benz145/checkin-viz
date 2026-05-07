import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import main


class VersionEndpointTests(unittest.TestCase):
    def test_get_version_number_returns_baked_value(self):
        self.assertEqual(main.get_version_number(), main.__VERSION_NUMBER__)

    def test_version_endpoint_embeds_baked_value_for_browser_display(self):
        original_version_number = main.__VERSION_NUMBER__
        main.__VERSION_NUMBER__ = "2026-05-07T13:55:00Z|1210fdf"
        try:
            response = main.app.test_client().get("/version")
        finally:
            main.__VERSION_NUMBER__ = original_version_number

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        html = response.get_data(as_text=True)
        self.assertIn('"2026-05-07T13:55:00Z|1210fdf"', html)
        self.assertIn('rawVersion.split("|")', html)
        self.assertIn('month: "long"', html)
        self.assertIn('day: "numeric"', html)
        self.assertIn('year: "numeric"', html)
        self.assertIn('timeZoneName: "shortGeneric"', html)
        self.assertIn('id="version-date"', html)
        self.assertIn('id="version-time"', html)
        self.assertIn('id="version-sha"', html)


if __name__ == "__main__":
    unittest.main()
