from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mailmerge_app.browser_profiles import _safe_profile_dir, launch_url


class BrowserProfileSecurityTests(unittest.TestCase):
    def test_profile_directory_must_be_direct_child(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Default").mkdir()
            self.assertEqual(_safe_profile_dir(root, "Default"), "Default")
            self.assertIsNone(_safe_profile_dir(root, "../Default"))
            self.assertIsNone(_safe_profile_dir(root, str((root / "Default").resolve())))
            self.assertIsNone(_safe_profile_dir(root, "missing"))

    def test_browser_launcher_rejects_non_gmail_urls(self):
        profile = {"executable": "browser.exe", "profile_dir": "Default"}
        with patch("mailmerge_app.browser_profiles.subprocess.Popen") as popen:
            with self.assertRaises(ValueError):
                launch_url(profile, "https://example.com/")
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
