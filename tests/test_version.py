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

    def test_version_display_fields_formats_baked_value(self):
        version_date, version_time, version_sha = main.version_display_fields(
            "2026-05-07T13:55:00Z|1210fdf"
        )
        self.assertEqual(version_date, "May 7, 2026")
        self.assertEqual(version_time, "1:55 PM UTC")
        self.assertEqual(version_sha, "1210fdf")

    def test_version_display_fields_handles_placeholder(self):
        version_date, version_time, version_sha = main.version_display_fields(
            "__VERSION_NUMBER__"
        )
        self.assertEqual(version_date, "unknown")
        self.assertEqual(version_time, "unknown")
        self.assertEqual(version_sha, "unknown")

    def test_version_endpoint_renders_server_formatted_fields(self):
        original_version_number = main.__VERSION_NUMBER__
        main.__VERSION_NUMBER__ = "2026-05-07T13:55:00Z|1210fdf"
        try:
            response = main.app.test_client().get("/version")
        finally:
            main.__VERSION_NUMBER__ = original_version_number

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        html = response.get_data(as_text=True)
        self.assertIn("May 7, 2026", html)
        self.assertIn("1:55 PM UTC", html)
        self.assertIn("1210fdf", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("rawVersion", html)


if __name__ == "__main__":
    unittest.main()
